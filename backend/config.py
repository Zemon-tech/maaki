"""Configuration management and startup validation for Voice AI Assistant."""

import os
from dataclasses import dataclass, field
import httpx
from dotenv import load_dotenv
from loguru import logger

# Load environment variables
load_dotenv()

# ---------------------------------------------------------------------------
# LLM Provider constants
# ---------------------------------------------------------------------------
LLM_PROVIDER_LOCAL = "local"
LLM_PROVIDER_OPENROUTER = "openrouter"
VALID_LLM_PROVIDERS = {LLM_PROVIDER_LOCAL, LLM_PROVIDER_OPENROUTER}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class AppConfig:
    # -----------------------------------------------------------------------
    # LLM Provider Selection: "local" (default) or "openrouter"
    # -----------------------------------------------------------------------
    llm_provider: str = os.getenv("LLM_PROVIDER", LLM_PROVIDER_LOCAL).strip().lower()

    # -----------------------------------------------------------------------
    # Sarvam AI Settings
    # -----------------------------------------------------------------------
    sarvam_api_key: str = os.getenv("SARVAM_API_KEY", "").strip()
    sarvam_stt_model: str = os.getenv("SARVAM_STT_MODEL", "saaras:v3").strip()
    sarvam_tts_model: str = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3").strip()
    sarvam_language: str = os.getenv("SARVAM_LANGUAGE", "en-IN").strip()
    sarvam_tts_voice: str = os.getenv("SARVAM_TTS_VOICE", "ratan").strip()
    # Pace: 0.5–2.0 for bulbul:v3. 0.9 = relaxed/measured (ideal for doctor consultation)
    sarvam_tts_pace: float = float(os.getenv("SARVAM_TTS_PACE", "0.9"))
    # Temperature: 0.01–1.0 for bulbul:v3. 0.7 = warm, expressive, conversational
    sarvam_tts_temperature: float = float(os.getenv("SARVAM_TTS_TEMPERATURE", "0.7"))

    # -----------------------------------------------------------------------
    # Local OpenAI-Compatible LLM Settings (Ollama, vLLM, llama.cpp, etc.)
    # -----------------------------------------------------------------------
    local_llm_base_url: str = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:8000/v1").strip().rstrip("/")
    local_llm_api_key: str = os.getenv("LOCAL_LLM_API_KEY", "local").strip()
    local_llm_model: str = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b").strip()

    # -----------------------------------------------------------------------
    # OpenRouter Settings (https://openrouter.ai)
    # -----------------------------------------------------------------------
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "").strip()
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()
    # Override base URL only if you need a proxy; leave blank to use the default
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL).strip().rstrip("/")

    # -----------------------------------------------------------------------
    # Prompt & Behavior
    # -----------------------------------------------------------------------
    system_prompt: str = os.getenv(
        "SYSTEM_PROMPT",
        """You are Nikul Mistry, Chief Business Officer at SAVA Info Systems Pvt. Ltd., taking a live vendor pitch call. You speak in natural, sharp Hinglish like a Bangalore startup founder / tech executive — mixing English with casual Hindi tech lingo (words like 'yaar', 'matlab', 'bro', 'boss', 'scene kya hai', 'sorted hai', 'dekh', 'bandwidth', 'ROI', 'stack', 'basically'). Founded in 2016, SAVA is an 11-50 person, ISO9001-certified software agency with 100+ projects delivered for 50+ global clients (US, UK, Germany, Australia) across Angular, Node.js, Java, Fastify, MongoDB and MySQL. SAVA also builds its own products like API Maker (low-code backend) and SAVA Printing SaaS, positioning itself as 'Development with AI. Faster Growth With AI Automation'. As CBO, you own revenue growth, pipeline, client delivery, and unit economics. You picked up expecting a routine vendor call; open with a quick, natural Hinglish greeting (e.g. 'Hey, Nikul here, batao what's up?') and let the caller lead into their pitch. Conduct yourself as a busy, sharp, moderately skeptical but fair founder/CBO who takes calls like this constantly and has seen plenty of vendors overpromise. Follow these principles strictly:

1. LISTEN AND SYNTHESIZE, DON'T RESET: Absorb everything the caller has told you about their product (what it does, who it's for, problem solved) and never ask them to repeat something they already said.

2. ONE SHARP, FOUNDER-ROOTED QUESTION OR OBJECTION AT A TIME IN HINGLISH: Instead of generic 'tell me more', react in Hinglish with the single most relevant concern a real tech executive would raise next — pricing and ROI ('ROI ka scene kya hai?'), migration bandwidth ('hamare dev team ka kitna bandwidth jayega?'), ISO9001 security and data privacy, cross-timezone client coordination, how CRM/projects/finance/docs actually talk to each other instead of just being separate tabs, how this is different from an all-in-one suite like Zoho or Asana, agency case studies, and — most importantly — why SAVA, which literally builds AI-integrated software for clients, should buy this instead of building it in-house. Surface these one at a time, depending on what has or hasn't been addressed.

3. LET CONVICTION MOVE NATURALLY: Don't fold on the first good answer, and don't stay rigidly skeptical if they handle objections cleanly. Let your tone warm up gradually ('Fair point yaar, that makes sense') if they genuinely understand agency workflows, and cool down ('Matlab, that sounds a bit too vague boss') if they dodge questions or get defensive. Give them a realistic, challenging practice call.

4. NATURAL SPOKEN HINGLISH: Speak the way a Bangalore tech executive talks on a real call — always in 1 to 2 short, crisp, natural sentences using standard English letters (Latin script). Never use markdown, bullet points, numbered lists, or emojis. Acknowledge naturally ('Right, got it,' 'Fair enough yaar,' 'Okay, interesting hai,') before hitting them with your question or objection.

5. NEVER LOOP: Every response must build on previous context and move the call forward — toward either next steps (demo, team connect) if convinced, or a polite but direct pass if not.

6. STAY IN CHARACTER: You are Nikul on a live call, not an AI describing a role. Never break character or provide meta-coaching unless explicitly asked to step out of the roleplay.""",
    ).strip()

    # -----------------------------------------------------------------------
    # Web & Server Settings
    # -----------------------------------------------------------------------
    host: str = os.getenv("HOST", "127.0.0.1").strip()
    port: int = int(os.getenv("PORT", "7860"))

    # -----------------------------------------------------------------------
    # Derived helpers (set post-init so dataclass fields are available)
    # -----------------------------------------------------------------------
    def __post_init__(self):
        # Normalise local LLM base URL to always end with /v1
        if not self.local_llm_base_url.endswith("/v1"):
            self.local_llm_base_url = f"{self.local_llm_base_url}/v1"

        # Warn early if an unknown provider is set
        if self.llm_provider not in VALID_LLM_PROVIDERS:
            logger.warning(
                f"Unknown LLM_PROVIDER '{self.llm_provider}'. "
                f"Falling back to '{LLM_PROVIDER_LOCAL}'. Valid options: {sorted(VALID_LLM_PROVIDERS)}"
            )
            self.llm_provider = LLM_PROVIDER_LOCAL

    # -----------------------------------------------------------------------
    # Convenience accessors – returns the active LLM parameters regardless
    # of which provider is selected.
    # -----------------------------------------------------------------------
    @property
    def active_llm_base_url(self) -> str:
        """Base URL of the currently selected LLM provider."""
        if self.llm_provider == LLM_PROVIDER_OPENROUTER:
            return self.openrouter_base_url
        return self.local_llm_base_url

    @property
    def active_llm_api_key(self) -> str:
        """API key for the currently selected LLM provider."""
        if self.llm_provider == LLM_PROVIDER_OPENROUTER:
            return self.openrouter_api_key
        return self.local_llm_api_key

    @property
    def active_llm_model(self) -> str:
        """Model name/slug for the currently selected LLM provider."""
        if self.llm_provider == LLM_PROVIDER_OPENROUTER:
            return self.openrouter_model
        return self.local_llm_model

    @property
    def is_openrouter(self) -> bool:
        return self.llm_provider == LLM_PROVIDER_OPENROUTER


def get_config() -> AppConfig:
    return AppConfig()


def check_local_llm_reachability(base_url: str, api_key: str = "local") -> tuple[bool, str]:
    """Check if the local OpenAI-compatible LLM endpoint is active and reachable."""
    models_url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(timeout=2.5) as client:
            resp = client.get(models_url, headers=headers)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    available_models = [m.get("id") for m in data.get("data", []) if "id" in m]
                    model_list_str = ", ".join(available_models[:4]) if available_models else "models detected"
                    return True, f"Reachable ({model_list_str})"
                except Exception:
                    return True, "Reachable"
            elif resp.status_code in (401, 403):
                return True, "Endpoint reachable (authentication required)"
            else:
                return True, f"Endpoint responded with status {resp.status_code}"
    except httpx.ConnectError:
        return False, f"Could not connect to {base_url}. Ensure your local LLM (Ollama, vLLM, llama.cpp, etc.) is running."
    except Exception as e:
        return False, f"Connection error: {e}"


def check_openrouter_reachability(api_key: str) -> tuple[bool, str]:
    """Check if the OpenRouter API key is set and the endpoint is reachable."""
    if not api_key:
        return False, "OPENROUTER_API_KEY is not set. Add it to backend/.env"
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/maaki-voice-assistant",
            "X-Title": "Maaki Voice Assistant",
        }
        with httpx.Client(timeout=4.0) as client:
            resp = client.get(f"{OPENROUTER_BASE_URL}/models", headers=headers)
            if resp.status_code == 200:
                return True, "OpenRouter API reachable ✓"
            elif resp.status_code in (401, 403):
                return False, "Invalid or expired OPENROUTER_API_KEY"
            else:
                return True, f"OpenRouter responded with status {resp.status_code}"
    except httpx.ConnectError:
        return False, "Could not connect to openrouter.ai – check your network connection."
    except Exception as e:
        return False, f"Connection error: {e}"


def check_llm_reachability(config: AppConfig) -> tuple[bool, str]:
    """Dispatch to the correct reachability check based on the active provider."""
    if config.is_openrouter:
        return check_openrouter_reachability(config.openrouter_api_key)
    return check_local_llm_reachability(config.local_llm_base_url, config.local_llm_api_key)


def print_startup_banner(config: AppConfig, llm_reachable: bool, llm_message: str):
    """Print clean diagnostic banner at startup."""
    print("=" * 60)
    print("       ⚡ Ultra-Low-Latency Voice Assistant (Maaki)")
    print("=" * 60)
    print("\n[Configuration]")

    provider_label = "OpenRouter" if config.is_openrouter else "Local LLM"
    print(f"  LLM Provider : {provider_label.upper()} (LLM_PROVIDER={config.llm_provider})")

    if config.is_openrouter:
        print(f"  OpenRouter:")
        print(f"    • Base URL : {config.openrouter_base_url}")
        print(f"    • Model    : {config.openrouter_model}")
        print(f"    • API Key  : {'🟢 Configured' if config.openrouter_api_key else '🔴 Missing (Set OPENROUTER_API_KEY in .env)'}")
        print(f"    • Status   : {'🟢 ' + llm_message if llm_reachable else '⚠️  ' + llm_message}")
    else:
        print(f"  Local LLM:")
        print(f"    • Base URL : {config.local_llm_base_url}")
        print(f"    • Model    : {config.local_llm_model or '(default)'}")
        print(f"    • Status   : {'🟢 ' + llm_message if llm_reachable else '⚠️  ' + llm_message}")

    print(f"\n  Sarvam AI:")
    print(f"    • STT Model: {config.sarvam_stt_model} (Language: {config.sarvam_language})")
    print(f"    • TTS Model: {config.sarvam_tts_model} (Voice: {config.sarvam_tts_voice}, Pace: {config.sarvam_tts_pace}, Temp: {config.sarvam_tts_temperature})")
    print(f"    • API Key  : {'🟢 Configured' if config.sarvam_api_key else '🔴 Missing (Set SARVAM_API_KEY in .env)'}")

    print(f"\n  Transport & Web UI:")
    print(f"    • Transport: SmallWebRTC (Ultra-low latency peer-to-peer)")
    print(f"    • Interface: Gradio UI + FastAPI backend")
    print(f"    • Local URL: http://{config.host}:{config.port}")
    print("=" * 60 + "\n")
