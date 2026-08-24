"""Pipecat Voice AI Agent implementation with Sarvam AI, Local LLM / OpenRouter, and SmallWebRTC."""

import re
from loguru import logger

from pipecat.adapters.services.open_ai_adapter import OpenAILLMInvocationParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMAssistantAggregatorParams,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.utils.context.llm_context_summarization import LLMAutoContextSummarizationConfig
from pipecat.workers.runner import WorkerRunner

from config import AppConfig
from consultation import consultation_manager
from latency import LatencyTracker, metrics_store

# OpenRouter attribution headers (required/recommended by OpenRouter)
OPENROUTER_EXTRA_HEADERS = {
    "HTTP-Referer": "https://github.com/maaki-voice-assistant",
    "X-Title": "Maaki Voice Assistant",
}

# Regex to match complete or partial thinking / reasoning XML-like tags and unused tokens
THINK_TAG_OPEN_RE = re.compile(r"<(?:think|thought|unused94)>", re.IGNORECASE)
THINK_TAG_CLOSE_RE = re.compile(r"</(?:think|thought)>|<unused95>", re.IGNORECASE)
UNUSED_TOKENS_RE = re.compile(r"<unused\d+>", re.IGNORECASE)


def merge_consecutive_role_messages(messages: list[dict]) -> list[dict]:
    """Merge consecutive messages of the same role to satisfy strict chat templates (e.g. Gemma, MedGemma, vLLM)."""
    if not messages:
        return []

    merged = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")

        if not content and not msg.get("tool_calls"):
            continue

        if merged and merged[-1].get("role") == role:
            prev_content = merged[-1].get("content", "")
            if isinstance(prev_content, str) and isinstance(content, str):
                merged[-1]["content"] = f"{prev_content}\n{content}".strip()
            else:
                merged.append(dict(msg))
        else:
            merged.append(dict(msg))

    return merged


class RobustDoctorLLMService(OpenAILLMService):
    """OpenAILLMService that:
    1. Enforces strict message role alternating & consecutive merging for all providers.
    2. Filters internal reasoning/thought tags seamlessly across streaming chunk boundaries.
    3. Disables reasoning effort on OpenRouter for ultra-low first token latency.
    """

    def __init__(self, *args, is_openrouter: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._is_openrouter = is_openrouter

    def build_chat_completion_params(self, params_from_context: OpenAILLMInvocationParams) -> dict:
        params = super().build_chat_completion_params(params_from_context)

        # Merge consecutive messages for all LLM backends (OpenRouter, Gemma, Ollama, etc.)
        if "messages" in params and isinstance(params["messages"], list):
            params["messages"] = merge_consecutive_role_messages(params["messages"])

        if self._is_openrouter:
            # Turn off reasoning on OpenRouter models for instant streaming
            params["extra_body"] = {
                **params.get("extra_body", {}),
                "reasoning": {
                    "effort": "none",
                    "exclude": True,
                    "enabled": False,
                },
            }
        return params

    async def get_chat_completions(self, context: LLMContext):
        raw_stream = await super().get_chat_completions(context)

        async def clean_chunk_generator():
            in_thinking = False
            stream_buffer = ""

            async for chunk in raw_stream:
                if not chunk.choices:
                    yield chunk
                    continue

                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                if not content:
                    yield chunk
                    continue

                stream_buffer += content

                while stream_buffer:
                    if not in_thinking:
                        # Check for opening thinking tags
                        open_match = THINK_TAG_OPEN_RE.search(stream_buffer)
                        if open_match:
                            # Yield any clean text before the opening tag
                            pre_text = stream_buffer[:open_match.start()]
                            pre_clean = UNUSED_TOKENS_RE.sub("", pre_text)
                            if pre_clean:
                                delta.content = pre_clean
                                yield chunk
                            # Enter thinking state
                            in_thinking = True
                            stream_buffer = stream_buffer[open_match.end():]
                            logger.debug("Suppressing model thinking stream...")
                        else:
                            # Check if the end of stream_buffer might be a partial opening tag (e.g. '<th')
                            partial_tag_match = re.search(r"<[a-zA-Z0-9_]*$", stream_buffer)
                            if partial_tag_match and len(stream_buffer) - partial_tag_match.start() < 12:
                                # Hold potential opening tag fragment
                                emit_text = stream_buffer[:partial_tag_match.start()]
                                stream_buffer = stream_buffer[partial_tag_match.start():]
                            else:
                                emit_text = stream_buffer
                                stream_buffer = ""

                            clean_emit = UNUSED_TOKENS_RE.sub("", emit_text)
                            if clean_emit:
                                delta.content = clean_emit
                                yield chunk
                            break
                    else:
                        # In thinking state, look for closing tag
                        close_match = THINK_TAG_CLOSE_RE.search(stream_buffer)
                        if close_match:
                            in_thinking = False
                            stream_buffer = stream_buffer[close_match.end():]
                            logger.debug("Thinking closed; resuming spoken response stream...")
                        else:
                            # Still inside thinking block, keep buffering/discarding
                            if len(stream_buffer) > 20:
                                stream_buffer = stream_buffer[-12:]
                            break

            # Flush any remaining buffer if not in thinking
            if stream_buffer and not in_thinking:
                clean_final = UNUSED_TOKENS_RE.sub("", stream_buffer).strip()
                if clean_final:
                    logger.info(f"Final spoken chunk emitted: '{clean_final}'")
                    delta.content = clean_final
                    yield chunk

        return clean_chunk_generator()


class RobustSarvamTTSService(SarvamTTSService):
    """SarvamTTSService subclass that guards against sending empty/whitespace-only
    strings to Sarvam's WebSocket and disables the false pause watchdog.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pause_frame_processing = False

    async def _send_text(self, text: str):
        if not text or not text.strip():
            return
        await super()._send_text(text)


async def create_and_run_agent(
    connection: SmallWebRTCConnection,
    config: AppConfig,
    voice: str | None = None,
):
    """Build and execute the real-time voice pipeline for an active WebRTC session."""
    active_voice = voice.strip() if voice and voice.strip() else config.sarvam_tts_voice
    logger.info(f"Initializing Dr. Maaki pipeline components for new WebRTC peer (voice: {active_voice})...")

    # Start or attach active consultation session
    consultation_manager._start_new_session_if_needed()

    # 1. WebRTC Audio Transport
    transport_params = TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        audio_in_sample_rate=16000,
        audio_out_sample_rate=24000,
    )
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=transport_params,
    )

    # 2. Sarvam Streaming STT (WebSocket Saaras with native VAD signals)
    stt_settings = SarvamSTTService.Settings(
        language=config.sarvam_language,
        model=config.sarvam_stt_model,
        vad_signals=True,
        high_vad_sensitivity=True,
    )
    stt = SarvamSTTService(
        api_key=config.sarvam_api_key,
        settings=stt_settings,
    )

    # 3. LLM Service with Injected Historical Context
    historical_context = consultation_manager.get_historical_context_prompt()
    effective_system_prompt = f"{config.system_prompt}\n{historical_context}".strip()

    llm_settings = RobustDoctorLLMService.Settings(
        model=config.active_llm_model,
        system_instruction=effective_system_prompt,
        temperature=0.6,
        max_completion_tokens=512,
    )

    if config.is_openrouter:
        logger.info(f"Connecting to OpenRouter at {config.openrouter_base_url} with model '{config.openrouter_model}' (reasoning disabled)")
        llm = RobustDoctorLLMService(
            api_key=config.active_llm_api_key,
            base_url=config.active_llm_base_url,
            settings=llm_settings,
            default_headers=OPENROUTER_EXTRA_HEADERS,
            is_openrouter=True,
            retry_on_timeout=True,
            retry_timeout_secs=5.0,
        )
    else:
        logger.info(f"Connecting to local LLM at {config.local_llm_base_url} with model '{config.local_llm_model}'")
        llm = RobustDoctorLLMService(
            api_key=config.active_llm_api_key,
            base_url=config.active_llm_base_url,
            settings=llm_settings,
            is_openrouter=False,
            retry_on_timeout=True,
            retry_timeout_secs=5.0,
        )

    # 4. Sarvam Streaming TTS (WebSocket Bulbul v3 with Real-time Streaming)
    tts_settings = RobustSarvamTTSService.Settings(
        model=config.sarvam_tts_model,
        voice=active_voice,
        language=config.sarvam_language,
        pace=config.sarvam_tts_pace,
        temperature=config.sarvam_tts_temperature,
        enable_preprocessing=True,
        min_buffer_size=50,
        max_chunk_length=150,
    )
    tts = RobustSarvamTTSService(
        api_key=config.sarvam_api_key,
        settings=tts_settings,
    )

    # 5. Conversation Context & Turn Aggregators with Auto-Summarization
    context = LLMContext()
    context_summarization_config = LLMAutoContextSummarizationConfig(
        max_context_tokens=4000,
        max_unsummarized_messages=14,
    )
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(),
        assistant_params=LLMAssistantAggregatorParams(
            enable_auto_context_summarization=True,
            auto_context_summarization_config=context_summarization_config,
        ),
    )

    # 6. Latency Tracker & Observer
    latency_tracker = LatencyTracker()

    @user_aggregator.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped(aggregator, strategy, message):
        if message and message.content:
            logger.info(f"Patient turn: '{message.content}'")
            metrics_store.add_transcript("user", message.content)

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn_stopped(aggregator, message):
        if message and message.content:
            logger.info(f"Doctor turn: '{message.content}'")
            metrics_store.add_transcript("assistant", message.content)

    # 7. Assembled Pipeline:
    # transport.input -> STT -> UserAggregator -> LLM -> TTS -> transport.output -> AssistantAggregator -> LatencyTracker
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
            latency_tracker,
        ]
    )

    # 8. Pipeline Worker with clean idle management and metrics
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=600,
        cancel_on_idle_timeout=True,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("WebRTC client audio stream connected. Pipeline listening...")
        metrics_store.set_status("Listening (Ready)...", state="listening")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("WebRTC client disconnected. Finalizing consultation record...")
        metrics_store.set_status("Disconnected")
        consultation_manager.finalize_active_consultation()
        await worker.cancel()

    # Run the worker with WorkerRunner without hijacking process SIGINT/SIGTERM
    runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)
    logger.info("Starting Pipecat worker runner...")
    try:
        await runner.run(worker)
    except Exception as e:
        logger.error(f"Error during agent pipeline execution: {e}")
        metrics_store.set_status(f"Error: {e}")
    finally:
        logger.info("Agent pipeline runner finished.")
        consultation_manager.finalize_active_consultation()
