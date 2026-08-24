"""Interactive, ultra-responsive Gradio UI with WebRTC audio bridge, mic visualizer, and diagnostic console."""

import gradio as gr
from config import AppConfig

HEAD_CONTENT = """
<style>
.gradio-container { max-width: 950px !important; margin: 0 auto; }
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 16px;
    border-radius: 9999px;
    font-weight: 600;
    font-size: 0.9rem;
    color: #ffffff;
    transition: all 0.3s ease;
}
.metric-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin: 16px 0;
}
.metric-box {
    border-radius: 12px;
    padding: 14px;
    text-align: center;
    background: #111827;
    border: 1px solid #1f2937;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}
.metric-val {
    font-size: 1.6rem;
    font-weight: 800;
    color: #38bdf8;
    font-family: ui-monospace, monospace;
}
.metric-lbl {
    font-size: 0.75rem;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-top: 4px;
}
.e2e-box {
    background: linear-gradient(135deg, #0f172a, #1e293b);
    border: 1px solid #38bdf8;
}
.e2e-box .metric-val {
    color: #4ade80 !important;
}
.btn-action {
    padding: 12px 28px;
    border-radius: 10px;
    font-weight: 700;
    font-size: 1rem;
    cursor: pointer;
    border: none;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    transition: all 0.2s ease;
}
.btn-start {
    background: #16a34a;
    color: white;
}
.btn-start:hover:not(:disabled) {
    background: #15803d;
    transform: translateY(-1px);
}
.btn-stop {
    background: #dc2626;
    color: white;
}
.btn-stop:hover:not(:disabled) {
    background: #b91c1c;
}
.btn-action:disabled {
    opacity: 0.45;
    cursor: not-allowed;
}
.console-box {
    background: #030712;
    border: 1px solid #1f2937;
    border-radius: 8px;
    padding: 10px 14px;
    font-family: ui-monospace, monospace;
    font-size: 0.82rem;
    color: #a3e635;
    max-height: 120px;
    overflow-y: auto;
}
</style>
<script>
// Expose functions on window to guarantee click responsiveness
window.voiceAgent = {
    pc: null,
    localStream: null,
    pollTimer: null,
    audioCtx: null,
    analyser: null,
    animFrame: null,

    log: function(msg, isErr = false) {
        console.log("[VoiceAgent]", msg);
        const el = document.getElementById('debug-log');
        if (el) {
            const time = new Date().toLocaleTimeString();
            el.innerHTML += `<div style="color:${isErr ? '#f87171' : '#a3e635'}">[${time}] ${msg}</div>`;
            el.scrollTop = el.scrollHeight;
        }
    },

    setStatus: function(text, color = '#475569') {
        const el = document.getElementById('ui-status');
        if (el) {
            el.textContent = text;
            el.style.backgroundColor = color;
        }
    },

    startVisualizer: function(stream) {
        try {
            const canvas = document.getElementById('mic-canvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            const source = this.audioCtx.createMediaStreamSource(stream);
            this.analyser = this.audioCtx.createAnalyser();
            this.analyser.fftSize = 64;
            source.connect(this.analyser);
            const dataArray = new Uint8Array(this.analyser.frequencyBinCount);

            const draw = () => {
                this.animFrame = requestAnimationFrame(draw);
                this.analyser.getByteFrequencyData(dataArray);
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                let sum = 0;
                for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
                const avg = sum / dataArray.length;
                const barWidth = (canvas.width / dataArray.length);
                let x = 0;
                for (let i = 0; i < dataArray.length; i++) {
                    const barHeight = (dataArray[i] / 255) * canvas.height;
                    ctx.fillStyle = avg > 15 ? '#38bdf8' : '#334155';
                    ctx.fillRect(x, canvas.height - barHeight, barWidth - 1, barHeight);
                    x += barWidth;
                }
            };
            draw();
        } catch (e) {
            console.debug("Visualizer error:", e);
        }
    },

    start: async function() {
        const btnStart = document.getElementById('btn-start');
        const btnStop = document.getElementById('btn-stop');
        const remoteAudio = document.getElementById('remote-audio');

        if (btnStart) btnStart.disabled = true;
        if (btnStop) btnStop.disabled = false;
        if (remoteAudio) {
            remoteAudio.muted = false;
            remoteAudio.volume = 1.0;
            remoteAudio.play().catch(() => {});
        }

        this.log("Requesting microphone permissions...");
        this.setStatus("Requesting Mic...", "#eab308");

        try {
            this.localStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                    sampleRate: 16000
                },
                video: false
            });

            this.log("Microphone connected.");
            this.startVisualizer(this.localStream);
            this.setStatus("Connecting WebRTC...", "#eab308");

            this.pc = new RTCPeerConnection({
                iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
            });

            this.localStream.getTracks().forEach(track => this.pc.addTrack(track, this.localStream));

            this.pc.ontrack = (event) => {
                this.log("Received remote audio track (" + event.track.kind + ", state: " + event.track.readyState + ").");
                if (remoteAudio && event.track.kind === 'audio') {
                    const stream = (event.streams && event.streams[0]) ? event.streams[0] : new MediaStream([event.track]);
                    remoteAudio.srcObject = stream;
                    remoteAudio.muted = false;
                    remoteAudio.volume = 1.0;

                    const playAudio = () => {
                        const p = remoteAudio.play();
                        if (p !== undefined) {
                            p.then(() => this.log("🔊 Speaker output active."))
                             .catch(e => this.log("Playback notice: " + e.message, false));
                        }
                    };

                    playAudio();
                    event.track.onunmute = () => {
                        this.log("🔊 Audio track receiving data.");
                        playAudio();
                    };
                }
            };

            this.pc.onconnectionstatechange = () => {
                this.log("WebRTC state: " + this.pc.connectionState);
                if (this.pc.connectionState === 'connected') {
                    this.setStatus("🟢 Connected (Listening)", "#16a34a");
                } else if (['disconnected', 'failed', 'closed'].includes(this.pc.connectionState)) {
                    this.setStatus("⚪ Disconnected", "#475569");
                }
            };

            // Create WebRTC DataChannel for Pipecat RTVI messages
            this.dc = this.pc.createDataChannel('pipecat');
            this.dc.onopen = () => this.log("WebRTC DataChannel connected.");
            this.dc.onmessage = (event) => console.debug("[DataChannel]", event.data);

            const offer = await this.pc.createOffer();
            await this.pc.setLocalDescription(offer);

            this.log("Gathering ICE candidates...");
            await new Promise(resolve => {
                if (this.pc.iceGatheringState === 'complete') resolve();
                else {
                    const check = () => {
                        if (this.pc.iceGatheringState === 'complete') {
                            this.pc.removeEventListener('icegatheringstatechange', check);
                            resolve();
                        }
                    };
                    this.pc.addEventListener('icegatheringstatechange', check);
                    setTimeout(resolve, 800);
                }
            });

            this.log("Sending SDP Offer to /api/offer...");
            const res = await fetch('/api/offer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sdp: this.pc.localDescription.sdp,
                    type: this.pc.localDescription.type
                })
            });

            if (!res.ok) {
                const errText = await res.text();
                throw new Error("Server error (" + res.status + "): " + errText);
            }

            const answer = await res.json();
            this.log("Received SDP Answer from server.");
            await this.pc.setRemoteDescription(new RTCSessionDescription(answer));
            this.log("⚡ WebRTC Handshake complete! Pipeline is live.");

            this.startPolling();

        } catch (err) {
            this.log("Failed: " + err.message, true);
            this.setStatus("🔴 Error: " + err.message, "#dc2626");
            this.stop();
        }
    },

    stop: function() {
        this.log("Stopping voice session...");
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
        }
        if (this.animFrame) {
            cancelAnimationFrame(this.animFrame);
            this.animFrame = null;
        }
        if (this.audioCtx) {
            this.audioCtx.close().catch(() => {});
            this.audioCtx = null;
        }
        if (this.pc) {
            this.pc.close();
            this.pc = null;
        }
        if (this.localStream) {
            this.localStream.getTracks().forEach(t => t.stop());
            this.localStream = null;
        }
        const btnStart = document.getElementById('btn-start');
        const btnStop = document.getElementById('btn-stop');
        if (btnStart) btnStart.disabled = false;
        if (btnStop) btnStop.disabled = true;
        this.setStatus("⚪ Disconnected", "#475569");
        this.log("Session stopped.");
    },

    startPolling: function() {
        if (this.pollTimer) clearInterval(this.pollTimer);
        this.pollTimer = setInterval(async () => {
            try {
                const res = await fetch('/api/status');
                if (!res.ok) return;
                const data = await res.json();

                if (data.status && this.pc && this.pc.connectionState === 'connected') {
                    if (data.status.includes("Listening")) this.setStatus("🟢 Listening...", "#16a34a");
                    else if (data.status.includes("Thinking")) this.setStatus("🧠 Thinking...", "#2563eb");
                    else if (data.status.includes("Speaking")) this.setStatus("🗣️ Speaking...", "#7c3aed");
                    else if (data.status.includes("Interrupted")) this.setStatus("⚡ Interrupted", "#ea580c");
                }

                const m = data.metrics || {};
                const setM = (id, val) => {
                    const el = document.getElementById(id);
                    if (el) el.textContent = val != null ? val + ' ms' : '-- ms';
                };
                setM('m-stt-partial', m.stt_first_partial_ms);
                setM('m-stt-final', m.stt_final_ms);
                setM('m-llm-ttft', m.llm_first_token_ms);
                setM('m-tts-ttfb', m.tts_first_audio_ms);
                setM('m-e2e', m.e2e_first_audio_ms);

                const feed = document.getElementById('transcript-feed');
                if (feed && data.conversation && data.conversation.length > 0) {
                    feed.innerHTML = data.conversation.map(msg => {
                        const isUser = msg.role === 'user';
                        return `
                            <div style="display:flex; gap:10px; align-items:flex-start;">
                                <span style="font-weight:700; color:${isUser ? '#38bdf8' : '#4ade80'}; font-size:0.85rem; min-width:70px;">
                                    ${isUser ? '👤 User:' : '🤖 Bot:'}
                                </span>
                                <span style="color:#f3f4f6; font-size:0.95rem; line-height:1.4;">${msg.text}</span>
                            </div>
                        `;
                    }).join('');
                    feed.scrollTop = feed.scrollHeight;
                }
            } catch (e) {}
        }, 200);
    }
};
</script>
"""

def get_webrtc_html(config: AppConfig) -> str:
    key_warning = ""
    if not config.sarvam_api_key:
        key_warning = """
        <div style="background:#7f1d1d; border:1px solid #ef4444; border-radius:8px; padding:12px; margin-bottom:14px; color:#fee2e2;">
            <strong>⚠️ SARVAM_API_KEY is missing:</strong> Add your Sarvam API key in <code>backend/.env</code> and restart to enable real-time STT & TTS.
        </div>
        """

    return f"""
    <div id="voice-agent-app">
        {key_warning}
        <!-- Hidden Audio Element for Assistant Playback -->
        <audio id="remote-audio" autoplay playsinline></audio>

        <!-- Controls Header -->
        <div style="display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; margin-bottom:16px; background:#111827; padding:14px 18px; border-radius:12px; border:1px solid #1f2937;">
            <div style="display:flex; gap:10px; align-items:center;">
                <button id="btn-start" class="btn-action btn-start" onclick="window.voiceAgent.start()">
                    🎙️ Start Conversation
                </button>
                <button id="btn-stop" class="btn-action btn-stop" onclick="window.voiceAgent.stop()" disabled>
                    ⏹️ Stop
                </button>
            </div>
            <div style="display:flex; align-items:center; gap:12px;">
                <canvas id="mic-canvas" width="100" height="30" style="background:#030712; border-radius:6px;"></canvas>
                <span id="ui-status" class="status-pill" style="background:#475569;">⚪ Disconnected</span>
            </div>
        </div>

        <!-- Latency Metrics Breakdown -->
        <div class="metric-grid">
            <div class="metric-box">
                <div id="m-stt-partial" class="metric-val">-- ms</div>
                <div class="metric-lbl">STT First Partial</div>
            </div>
            <div class="metric-box">
                <div id="m-stt-final" class="metric-val">-- ms</div>
                <div class="metric-lbl">STT Final Transcript</div>
            </div>
            <div class="metric-box">
                <div id="m-llm-ttft" class="metric-val">-- ms</div>
                <div class="metric-lbl">LLM First Token (TTFT)</div>
            </div>
            <div class="metric-box">
                <div id="m-tts-ttfb" class="metric-val">-- ms</div>
                <div class="metric-lbl">TTS First Audio (TTFB)</div>
            </div>
            <div class="metric-box e2e-box">
                <div id="m-e2e" class="metric-val">-- ms</div>
                <div class="metric-lbl">⚡ E2E First Audio</div>
            </div>
        </div>

        <!-- Live Conversation Feed -->
        <div style="background:#0f172a; border:1px solid #1e293b; border-radius:12px; padding:16px; margin-bottom:14px; min-height:160px; max-height:260px; overflow-y:auto;">
            <div style="font-size:0.75rem; text-transform:uppercase; color:#94a3b8; font-weight:700; margin-bottom:8px; letter-spacing:0.05em;">
                💬 Live Conversation Transcript
            </div>
            <div id="transcript-feed" style="display:flex; flex-direction:column; gap:10px;">
                <div style="color:#64748b; font-style:italic;">Click "Start Conversation", grant microphone access, and start talking...</div>
            </div>
        </div>

        <!-- Real-time Diagnostic Console -->
        <div style="margin-top:10px;">
            <div style="font-size:0.75rem; text-transform:uppercase; color:#9ca3af; font-weight:700; margin-bottom:6px;">
                🔍 Client Activity Log
            </div>
            <div id="debug-log" class="console-box">
                <div>[Ready] Click 'Start Conversation' to initialize real-time WebRTC audio connection.</div>
            </div>
        </div>
    </div>
    """


def create_ui(config: AppConfig) -> gr.Blocks:
    """Build the single-page Gradio UI."""
    with gr.Blocks(title="Local LLM Voice Assistant") as demo:
        with gr.Column(elem_classes=["gradio-container"]):
            provider_label = "OpenRouter" if config.is_openrouter else "Local LLM"
            gr.Markdown(
                f"""
                # ⚡ Ultra-Low-Latency Voice Assistant (Maaki)
                **Streaming STT (`{config.sarvam_stt_model}`) + {provider_label} (`{config.active_llm_model}`) + Streaming TTS (`{config.sarvam_tts_model}`)**
                
                *Real-time peer-to-peer audio pipeline via Pipecat SmallWebRTC.*
                """
            )
            gr.HTML(get_webrtc_html(config))

            with gr.Accordion("⚙️ Pipeline Configuration & Endpoint Details", open=False):
                if config.is_openrouter:
                    gr.Markdown(
                        f"""
                        | Component | Setting |
                        | :--- | :--- |
                        | **LLM Provider** | `OpenRouter` |
                        | **OpenRouter Model** | `{config.openrouter_model}` |
                        | **OpenRouter Base URL** | `{config.openrouter_base_url}` |
                        | **OpenRouter API Key** | `{'✅ Configured' if config.openrouter_api_key else '❌ Missing – set OPENROUTER_API_KEY'}` |
                        | **Sarvam STT Model** | `{config.sarvam_stt_model}` |
                        | **Sarvam TTS Model** | `{config.sarvam_tts_model}` |
                        | **Language / Voice** | `{config.sarvam_language}` / `{config.sarvam_tts_voice}` |
                        | **System Prompt** | `{config.system_prompt}` |
                        """
                    )
                else:
                    gr.Markdown(
                        f"""
                        | Component | Setting |
                        | :--- | :--- |
                        | **LLM Provider** | `Local` |
                        | **Local LLM URL** | `{config.local_llm_base_url}` |
                        | **Local LLM Model** | `{config.local_llm_model}` |
                        | **Sarvam STT Model** | `{config.sarvam_stt_model}` |
                        | **Sarvam TTS Model** | `{config.sarvam_tts_model}` |
                        | **Language / Voice** | `{config.sarvam_language}` / `{config.sarvam_tts_voice}` |
                        | **System Prompt** | `{config.system_prompt}` |
                        """
                    )

    return demo
