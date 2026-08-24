# ⚡ Ultra-Low-Latency Local LLM Voice Assistant

An ultra-low-latency, real-time voice assistant built with **Pipecat**, **Sarvam AI** streaming STT & TTS, a **local OpenAI-compatible LLM**, and a minimal **Gradio** web UI powered by **SmallWebRTC**.

Designed specifically for **minimum time-to-first-audio** through streaming audio, streaming speech-to-text, streaming LLM token generation, and streaming text-to-speech without sequential buffering.

---

## 🏛️ Pipeline Architecture

```text
Browser Microphone
        ↓ (Real-time 16kHz PCM audio stream)
SmallWebRTC Transport
        ↓ (Zero-upload / direct peer-to-peer connection)
Sarvam Saaras STT (Streaming WebSocket)
        ↓ (Interim & final transcripts)
LLM Context Aggregator
        ↓ (Prompt & conversation turn tracking)
Local OpenAI-Compatible LLM (Streaming Tokens)
        ↓ (vLLM / Ollama / llama.cpp / LM Studio)
Sarvam Bulbul TTS (Streaming WebSocket)
        ↓ (Immediate 24kHz audio chunks)
SmallWebRTC Transport
        ↓ (Instant playback on arrival)
Browser Speaker
```

---

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.11+
- `uv` (recommended) or standard `python3 -m venv`
- A running local LLM server (e.g. Ollama, vLLM, llama.cpp)
- A [Sarvam AI API Key](https://www.sarvam.ai)

### 2. Installation

Using `uv`:
```bash
# Clone or navigate to the backend directory
cd backend

# Install all dependencies with uv
uv sync
```

Or using standard `pip`:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Configuration

Copy `.env.example` to `.env` and fill in your settings:

```bash
cp .env.example .env
```

Edit `.env`:
```env
# Sarvam AI API Key
SARVAM_API_KEY=your_sarvam_api_key_here

# Sarvam Models & Voice
SARVAM_STT_MODEL=saaras:v3
SARVAM_TTS_MODEL=bulbul:v3
SARVAM_LANGUAGE=en-IN
SARVAM_TTS_VOICE=shubh

# Local LLM (OpenAI-Compatible endpoint)
LOCAL_LLM_BASE_URL=http://localhost:8000/v1
LOCAL_LLM_API_KEY=local
LOCAL_LLM_MODEL=qwen2.5:7b

# System Prompt
SYSTEM_PROMPT=You are a fast, natural voice assistant. Speak conversationally and concisely in 1 to 2 short sentences. Do not use markdown, bullet points, or emojis. Answer directly.

# Server Host & Port
HOST=127.0.0.1
PORT=7860
```

### 4. Running the Assistant

```bash
# Using uv
uv run python app.py

# Or with activated venv
source venv/bin/activate
python app.py
```

Open your browser at **[http://localhost:7860](http://localhost:7860)**.

---

## 🦙 Starting Your Local LLM

You can use any OpenAI-compatible server. Examples:

### Option A: Ollama
```bash
# Start Ollama with OpenAI compatibility (default port 11434)
ollama run qwen2.5:7b

# Set in .env:
# LOCAL_LLM_BASE_URL=http://localhost:11434/v1
# LOCAL_LLM_MODEL=qwen2.5:7b
```

### Option B: vLLM
```bash
# Start vLLM server
vllm serve Qwen/Qwen2.5-7B-Instruct --port 8000

# Set in .env:
# LOCAL_LLM_BASE_URL=http://localhost:8000/v1
# LOCAL_LLM_MODEL=Qwen/Qwen2.5-7B-Instruct
```

### Option C: llama.cpp / llama-server
```bash
# Start llama-server
./llama-server -m models/qwen2.5-7b-instruct.gguf --port 8000

# Set in .env:
# LOCAL_LLM_BASE_URL=http://localhost:8000/v1
# LOCAL_LLM_MODEL=default
```

---

## 📊 Latency Instrumentation

The application tracks timestamps across all pipeline stages:

- **$t_0$**: User starts speaking (VAD speech onset detection)
- **$t_1$**: First STT partial transcript received
- **$t_2$**: Final speech transcript received
- **$t_3$**: LLM completion request dispatched
- **$t_4$**: First LLM token streamed (TTFT)
- **$t_5$**: First TTS text chunk sent
- **$t_6$**: First synthesized audio chunk received from Sarvam (TTFB)
- **$t_7$**: Audio output sent to WebRTC speaker

### Real-Time Terminal Output Example
```text
[VOICE LATENCY - Turn #1]
  • STT first partial   :   142 ms
  • STT final transcript:   280 ms
  • LLM first token     :    91 ms
  • TTS first audio     :   188 ms
  ---------------------------------
  ⚡ E2E FIRST AUDIO    :   421 ms
```

The metrics are also rendered live in the Gradio web dashboard for each turn.

---

## 🛑 Interruption / Barge-In Handling

When the assistant is speaking and you start talking:
1. Silero VAD detects user speech.
2. An immediate `CancelFrame` is dispatched upstream.
3. Current audio playback in the browser stops immediately.
4. Pending LLM token generation and TTS audio synthesis are flushed.
5. The pipeline processes the new utterance without delay.

---

## 📁 Project Structure

```
backend/
├── app.py                # FastAPI server, WebRTC signaling & Gradio UI mount
├── agent.py              # Pipecat real-time voice pipeline assembly
├── config.py             # Configuration loading & startup validation
├── latency.py            # Real-time latency tracking processor & logging
├── ui.py                 # Gradio Blocks UI with embedded WebRTC client
├── pyproject.toml        # uv / project metadata
├── requirements.txt      # Dependency list
├── .env.example          # Sample environment variables
└── README.md             # Documentation
```

---

## 🔧 Troubleshooting

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| **`Local LLM unavailable`** | LLM server not started or wrong port | Verify `LOCAL_LLM_BASE_URL` in `.env` and test `curl http://localhost:8000/v1/models`. |
| **`Missing SARVAM_API_KEY`** | Empty API key in `.env` | Add your Sarvam API key to `SARVAM_API_KEY` in `.env`. |
| **Microphone Permission Denied** | Browser blocked mic access | Allow microphone permissions in browser settings for `localhost`. |
| **No audio output** | WebRTC autoplay blocked | Click anywhere on the webpage or press `Start Conversation` to enable audio playback context. |
