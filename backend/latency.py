"""Latency instrumentation and real-time metrics tracking for Voice AI pipeline."""

import time
from dataclasses import dataclass, field
from collections.abc import Callable
from loguru import logger

from consultation import consultation_manager
from pipecat.frames.frames import (
    CancelFrame,
    Frame,
    InterimTranscriptionFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


@dataclass
class TurnMetrics:
    turn_id: int = 0
    t0_user_speech_start: float | None = None
    t1_stt_first_partial: float | None = None
    t2_stt_final: float | None = None
    t3_llm_start: float | None = None
    t4_llm_first_token: float | None = None
    t5_tts_first_chunk: float | None = None
    t6_tts_first_audio: float | None = None

    user_transcript: str = ""
    assistant_text: str = ""
    is_completed: bool = False
    interrupted: bool = False

    # Computed metrics (in milliseconds)
    stt_first_partial_ms: float | None = None
    stt_final_ms: float | None = None
    llm_first_token_ms: float | None = None
    tts_first_audio_ms: float | None = None
    e2e_first_audio_ms: float | None = None

    def calculate(self):
        t0 = self.t0_user_speech_start
        if t0 is not None:
            if self.t1_stt_first_partial is not None:
                self.stt_first_partial_ms = round((self.t1_stt_first_partial - t0) * 1000, 1)
            if self.t2_stt_final is not None:
                self.stt_final_ms = round((self.t2_stt_final - t0) * 1000, 1)
            if self.t6_tts_first_audio is not None:
                self.e2e_first_audio_ms = round((self.t6_tts_first_audio - t0) * 1000, 1)

        if self.t3_llm_start is not None and self.t4_llm_first_token is not None:
            self.llm_first_token_ms = round((self.t4_llm_first_token - self.t3_llm_start) * 1000, 1)
        elif self.t2_stt_final is not None and self.t4_llm_first_token is not None:
            self.llm_first_token_ms = round((self.t4_llm_first_token - self.t2_stt_final) * 1000, 1)

        if self.t4_llm_first_token is not None and self.t6_tts_first_audio is not None:
            self.tts_first_audio_ms = round((self.t6_tts_first_audio - self.t4_llm_first_token) * 1000, 1)
        elif self.t5_tts_first_chunk is not None and self.t6_tts_first_audio is not None:
            self.tts_first_audio_ms = round((self.t6_tts_first_audio - self.t5_tts_first_chunk) * 1000, 1)


class GlobalMetricsStore:
    """Singleton store to broadcast latest metrics, persona state, clinical context, and transcripts to UI / API."""

    def __init__(self):
        self.latest_metrics: TurnMetrics = TurnMetrics()
        self.history: list[TurnMetrics] = []
        self.conversation: list[dict[str, str]] = []
        self.status: str = "Ready"
        self.state: str = "idle"  # "idle" | "listening" | "thinking" | "speaking" | "asleep"
        self._listeners: list[Callable[[TurnMetrics], None]] = []

    def update(self, metrics: TurnMetrics):
        metrics.calculate()
        self.latest_metrics = metrics
        for listener in self._listeners:
            try:
                listener(metrics)
            except Exception as e:
                logger.debug(f"Metrics listener error: {e}")

    def add_transcript(self, role: str, text: str):
        if not text.strip():
            return
        if self.conversation and self.conversation[-1]["role"] == role:
            self.conversation[-1]["text"] = text
        else:
            self.conversation.append({"role": role, "text": text})

    def set_status(self, status: str, state: str | None = None):
        self.status = status
        if state:
            self.state = state

    def get_clinical_state(self) -> dict:
        if consultation_manager.active_consultation:
            return consultation_manager.active_consultation.clinical_state.model_dump()
        return {}

    def get_active_consultation(self) -> dict:
        if consultation_manager.active_consultation:
            return consultation_manager.active_consultation.model_dump()
        return {}

    def reset(self):
        """Reset conversation, metrics and state for a fresh session."""
        self.latest_metrics = TurnMetrics()
        self.history = []
        self.conversation = []
        self.status = "Ready"
        self.state = "idle"

    def subscribe(self, listener: Callable[[TurnMetrics], None]):
        self._listeners.append(listener)


metrics_store = GlobalMetricsStore()


class LatencyTracker(FrameProcessor):
    """Pipeline processor that measures end-to-end latency and tracks persona states."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._turn_count = 0
        self._current_turn: TurnMetrics = TurnMetrics()
        self._logged_first_audio = False

    def _start_new_turn(self):
        self._turn_count += 1
        self._current_turn = TurnMetrics(
            turn_id=self._turn_count,
            t0_user_speech_start=time.perf_counter(),
        )
        self._logged_first_audio = False
        metrics_store.set_status("Listening...", state="listening")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        now = time.perf_counter()

        # 1. User starts speaking (t0)
        if isinstance(frame, (UserStartedSpeakingFrame, VADUserStartedSpeakingFrame)):
            if self._current_turn.t0_user_speech_start is None or self._current_turn.is_completed:
                self._start_new_turn()
            else:
                metrics_store.set_status("Listening...", state="listening")

        # User stopped speaking
        elif isinstance(frame, (UserStoppedSpeakingFrame, VADUserStoppedSpeakingFrame)):
            if self._current_turn.t0_user_speech_start is not None:
                metrics_store.set_status("Thinking...", state="thinking")
            else:
                metrics_store.set_status("Listening...", state="listening")

        # Interruption / Barge-in
        elif isinstance(frame, CancelFrame):
            if self._current_turn and not self._current_turn.is_completed:
                self._current_turn.interrupted = True
            metrics_store.set_status("Listening...", state="listening")

        # 2. First STT partial (t1)
        elif isinstance(frame, InterimTranscriptionFrame):
            if self._current_turn.t0_user_speech_start is not None and self._current_turn.t1_stt_first_partial is None:
                self._current_turn.t1_stt_first_partial = now
                self._current_turn.calculate()
                metrics_store.update(self._current_turn)
            metrics_store.set_status("Listening...", state="listening")

        # 3. Final STT transcript (t2)
        elif isinstance(frame, TranscriptionFrame):
            if self._current_turn.t0_user_speech_start is None:
                self._start_new_turn()
            if self._current_turn.t2_stt_final is None:
                self._current_turn.t2_stt_final = now
                self._current_turn.user_transcript = frame.text
                self._current_turn.calculate()
                metrics_store.add_transcript("user", frame.text)
                metrics_store.set_status("Thinking...", state="thinking")
                metrics_store.update(self._current_turn)

        # 4. LLM request starts (t3)
        elif isinstance(frame, LLMFullResponseStartFrame):
            if self._current_turn.t3_llm_start is None:
                self._current_turn.t3_llm_start = now
            metrics_store.set_status("Thinking...", state="thinking")

        # 5. First LLM token (t4)
        elif isinstance(frame, (LLMTextFrame, TextFrame)):
            if self._current_turn.t3_llm_start is None:
                self._current_turn.t3_llm_start = now
            if self._current_turn.t4_llm_first_token is None:
                self._current_turn.t4_llm_first_token = now
                self._current_turn.t5_tts_first_chunk = now
                self._current_turn.calculate()
                metrics_store.set_status("Generating voice...", state="thinking")
                metrics_store.update(self._current_turn)
            if frame.text:
                self._current_turn.assistant_text += frame.text
                metrics_store.add_transcript("assistant", self._current_turn.assistant_text)

        # LLM finished generating response tokens
        elif isinstance(frame, LLMFullResponseEndFrame):
            pass

        # 6. Assistant starts speaking
        elif isinstance(frame, (BotStartedSpeakingFrame, TTSStartedFrame)):
            metrics_store.set_status("Speaking", state="speaking")

        # TTS Audio chunks arrive
        elif isinstance(frame, TTSAudioRawFrame):
            if self._current_turn.t6_tts_first_audio is None:
                self._current_turn.t6_tts_first_audio = now
                self._current_turn.calculate()
                metrics_store.set_status("Speaking", state="speaking")
                metrics_store.update(self._current_turn)

                if not self._logged_first_audio:
                    self._logged_first_audio = True
                    self._log_metrics_banner(self._current_turn)
            else:
                metrics_store.set_status("Speaking", state="speaking")

        # 7. Assistant finished speaking -> Transition back to listening!
        elif isinstance(frame, (BotStoppedSpeakingFrame, TTSStoppedFrame)):
            self._current_turn.is_completed = True
            metrics_store.set_status("Listening...", state="listening")

        # Push frame to next processor in the pipeline
        await self.push_frame(frame, direction)

    def _log_metrics_banner(self, m: TurnMetrics):
        """Log real-time latency breakdown to the terminal."""
        p_ms = f"{m.stt_first_partial_ms:.0f} ms" if m.stt_first_partial_ms is not None else "N/A"
        f_ms = f"{m.stt_final_ms:.0f} ms" if m.stt_final_ms is not None else "N/A"
        l_ms = f"{m.llm_first_token_ms:.0f} ms" if m.llm_first_token_ms is not None else "N/A"
        t_ms = f"{m.tts_first_audio_ms:.0f} ms" if m.tts_first_audio_ms is not None else "N/A"
        e_ms = f"{m.e2e_first_audio_ms:.0f} ms" if m.e2e_first_audio_ms is not None else "N/A"

        logger.info(
            f"\n[VOICE LATENCY - Turn #{m.turn_id}]\n"
            f"  • STT first partial   : {p_ms:>8}\n"
            f"  • STT final transcript: {f_ms:>8}\n"
            f"  • LLM first token     : {l_ms:>8}\n"
            f"  • TTS first audio     : {t_ms:>8}\n"
            f"  ---------------------------------\n"
            f"  ⚡ E2E FIRST AUDIO    : {e_ms:>8}\n"
        )
