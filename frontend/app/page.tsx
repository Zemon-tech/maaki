"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { Persona, PersonaState } from "@/components/ai-elements/persona";
import {
  VoiceSelector,
  VoiceSelectorTrigger,
  VoiceSelectorContent,
  VoiceSelectorInput,
  VoiceSelectorList,
  VoiceSelectorEmpty,
  VoiceSelectorGroup,
  VoiceSelectorItem,
  VoiceSelectorName,
  VoiceSelectorAttributes,
  VoiceSelectorGender,
  VoiceSelectorAccent,
  VoiceSelectorDescription,
  VoiceSelectorBullet,
} from "@/components/ai-elements/voice-selector";
import {
  MicSelector,
  MicSelectorTrigger,
  MicSelectorValue,
  MicSelectorContent,
  MicSelectorInput,
  MicSelectorList,
  MicSelectorEmpty,
  MicSelectorItem,
  MicSelectorLabel,
} from "@/components/ai-elements/mic-selector";
import {
  Transcription,
} from "@/components/ai-elements/transcription";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Mic,
  MicOff,
  PhoneCall,
  PhoneOff,
  Radio,
  Zap,
  Volume2,
  HeartPulse,
  Stethoscope,
  CheckCircle2,
  FileText,
  History,
  Activity,
  PlusCircle,
  Clock,
  Sparkles,
  ClipboardList,
  Check,
} from "lucide-react";

interface TurnTelemetry {
  turn_id?: number;
  stt_first_partial_ms?: number | null;
  stt_final_ms?: number | null;
  llm_first_token_ms?: number | null;
  tts_first_audio_ms?: number | null;
  e2e_first_audio_ms?: number | null;
}

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  timestamp?: string;
}

interface ClinicalState {
  stage?: string;
  chief_complaint?: string;
  symptoms?: string[];
  duration?: string;
  severity?: string;
  location?: string;
  associated_symptoms?: string[];
  past_history?: string;
  current_medications?: string[];
  allergies?: string[];
  clinical_impressions?: string[];
  recommendations?: string[];
}

interface PastConsultation {
  id: string;
  patient_name: string;
  started_at: string;
  ended_at?: string;
  chief_complaint: string;
  stage: string;
  symptoms: string[];
  soap_summary: {
    subjective?: string;
    objective?: string;
    assessment?: string;
    plan?: string;
  };
  message_count: number;
}

const SARVAM_VOICES = [
  {
    id: "ratan",
    name: "Ratan",
    gender: "male" as const,
    accent: "india" as const,
    language: "en-IN / hi-IN",
    description: "Recommended male English (India) doctor voice. Calm, confident & clear.",
  },
  {
    id: "ishita",
    name: "Ishita",
    gender: "female" as const,
    accent: "india" as const,
    language: "en-IN / hi-IN",
    description: "Top-tier female voice for English & Hindi. Warm, empathetic & articulate.",
  },
  {
    id: "shubh",
    name: "Shubh",
    gender: "male" as const,
    accent: "india" as const,
    language: "hi-IN",
    description: "Natural conversational Hindi & multilingual voice.",
  },
  {
    id: "priya",
    name: "Priya",
    gender: "female" as const,
    accent: "india" as const,
    language: "hi-IN / te-IN",
    description: "Expressive female voice, excellent for medical wellness consultations.",
  },
  {
    id: "aditya",
    name: "Aditya",
    gender: "male" as const,
    accent: "india" as const,
    language: "hi-IN",
    description: "Deep, reassuring voice with clear diction.",
  },
  {
    id: "ritu",
    name: "Ritu",
    gender: "female" as const,
    accent: "india" as const,
    language: "ta-IN / hi-IN",
    description: "Friendly and attentive voice for southern Indic languages and Hindi.",
  },
];

const CLINICAL_STAGES = [
  { id: "intake", label: "1. Intake", desc: "Chief Complaint" },
  { id: "exploration", label: "2. Deep-Dive", desc: "Duration & Severity" },
  { id: "history", label: "3. History", desc: "Meds & Prior Care" },
  { id: "assessment", label: "4. Assessment", desc: "Clinical Impression" },
  { id: "wrapup", label: "5. Plan", desc: "Advice & Next Steps" },
];

export default function Home() {
  // WebRTC & Session State
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [sessionStatus, setSessionStatus] = useState("Disconnected");
  
  // Visual Persona State: "idle" | "listening" | "thinking" | "speaking" | "asleep"
  const [personaState, setPersonaState] = useState<PersonaState>("idle");
  const [personaVariant, setPersonaVariant] = useState<
    "obsidian" | "mana" | "opal" | "halo" | "glint" | "command"
  >("opal");

  // Active view tab: "transcript" | "clinical_context" | "past_meets"
  const [activeTab, setActiveTab] = useState<"transcript" | "clinical_context" | "past_meets">("transcript");

  // Device & Voice Config
  const [selectedVoice, setSelectedVoice] = useState("ratan");
  const [selectedMic, setSelectedMic] = useState<string | undefined>(undefined);

  // Telemetry & Conversation Feed
  const [telemetry, setTelemetry] = useState<TurnTelemetry>({});
  const [conversation, setConversation] = useState<ChatMessage[]>([]);
  const [clinicalState, setClinicalState] = useState<ClinicalState>({});
  const [activeConsultation, setActiveConsultation] = useState<{ id?: string; started_at?: string; soap_summary?: Record<string, string> }>({});
  const [pastConsultations, setPastConsultations] = useState<PastConsultation[]>([]);
  const [audioCurrentTime, setAudioCurrentTime] = useState(0);

  // Audio level visualizer
  const [audioLevel, setAudioLevel] = useState(0);

  // WebRTC references
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversation]);

  // Fetch past consultations
  const fetchPastConsultations = async () => {
    try {
      const res = await fetch("/api/consultations");
      if (res.ok) {
        const data = await res.json();
        if (data.consultations) {
          setPastConsultations(data.consultations);
        }
      }
    } catch (e) {
      console.debug("Error fetching past consultations:", e);
    }
  };

  useEffect(() => {
    fetchPastConsultations();
  }, []);

  // Convert conversation to AI SDK Transcription format for transcription component (memoized)
  const transcriptionSegments = useMemo(
    () =>
      conversation.map((msg, idx) => ({
        text: `${msg.role === "user" ? "Patient" : "Dr. Maaki"}: ${msg.text}`,
        startSecond: idx * 4,
        endSecond: (idx + 1) * 4,
      })),
    [conversation]
  );

  // Update visualizer based on microphone stream
  const setupAudioVisualizer = (stream: MediaStream) => {
    try {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new AudioCtx();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 64;
      const source = ctx.createMediaStreamSource(stream);
      source.connect(analyser);

      audioContextRef.current = ctx;
      analyserRef.current = analyser;

      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      const checkVolume = () => {
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
        const avg = sum / dataArray.length;
        setAudioLevel(Math.min(100, Math.round((avg / 128) * 100)));
        animFrameRef.current = requestAnimationFrame(checkVolume);
      };
      checkVolume();
    } catch (e) {
      console.warn("Visualizer initialization:", e);
    }
  };

  // Start WebRTC Call to Pipecat Backend
  const startCall = async () => {
    if (isConnecting || isConnected) return;
    setIsConnecting(true);
    setSessionStatus("Requesting microphone...");

    try {
      // 1. Get user media (selected mic or default)
      const audioConstraints: MediaTrackConstraints = {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        sampleRate: 16000,
      };
      if (selectedMic) {
        audioConstraints.deviceId = { exact: selectedMic };
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: audioConstraints,
        video: false,
      });
      localStreamRef.current = stream;
      setupAudioVisualizer(stream);

      // Pre-unlock remote audio element for autoplay compatibility
      if (remoteAudioRef.current) {
        remoteAudioRef.current.muted = false;
        remoteAudioRef.current.volume = 1.0;
        remoteAudioRef.current.play().catch(() => {});
      }

      setSessionStatus("Establishing WebRTC connection...");

      // 2. Setup RTCPeerConnection with STUN server
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
      });
      pcRef.current = pc;

      // Add local audio tracks
      stream.getTracks().forEach((track) => {
        pc.addTrack(track, stream);
      });

      // Ensure transceiver is configured as sendrecv to guarantee bidirectional audio
      const transceivers = pc.getTransceivers();
      const audioTransceiver = transceivers.find(
        (t) => t.receiver.track.kind === "audio" || t.sender.track?.kind === "audio"
      );
      if (audioTransceiver) {
        audioTransceiver.direction = "sendrecv";
      } else {
        pc.addTransceiver("audio", { direction: "sendrecv" });
      }

      // Setup Web Audio API context on user gesture to guarantee audio output
      // Handle remote incoming audio track from assistant
      pc.ontrack = (event) => {
        console.log("WebRTC ontrack received:", event.track.kind);
        if (event.track.kind === "audio") {
          const remoteStream =
            event.streams && event.streams[0]
              ? event.streams[0]
              : new MediaStream([event.track]);

          if (remoteAudioRef.current) {
            remoteAudioRef.current.srcObject = remoteStream;
            remoteAudioRef.current.muted = false;
            remoteAudioRef.current.volume = 1.0;
            const playPromise = remoteAudioRef.current.play();
            if (playPromise !== undefined) {
              playPromise.catch((e) => console.log("Audio playback notice:", e));
            }
          }

          event.track.onunmute = () => {
            remoteAudioRef.current?.play().catch(() => {});
          };
        }
      };

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === "connected") {
          setIsConnected(true);
          setIsConnecting(false);
          setSessionStatus("Listening (Ready)");
          setPersonaState("listening");
        } else if (["disconnected", "failed", "closed"].includes(pc.connectionState)) {
          stopCall();
        }
      };

      // Create DataChannel for Pipecat control messages
      pc.createDataChannel("pipecat");

      // 3. Create Offer
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // 4. Wait for ICE gathering
      await new Promise<void>((resolve) => {
        if (pc.iceGatheringState === "complete") resolve();
        else {
          const check = () => {
            if (pc.iceGatheringState === "complete") {
              pc.removeEventListener("icegatheringstatechange", check);
              resolve();
            }
          };
          pc.addEventListener("icegatheringstatechange", check);
          setTimeout(resolve, 800);
        }
      });

      // 5. Send SDP and selected voice to FastAPI backend
      const res = await fetch("/api/offer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sdp: pc.localDescription?.sdp,
          type: pc.localDescription?.type,
          voice: selectedVoice,
        }),
      });

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}: ${await res.text()}`);
      }

      const answer = await res.json();
      await pc.setRemoteDescription(new RTCSessionDescription(answer));

      // 6. Poll status immediately
      pollStatus();

    } catch (err: unknown) {
      console.error("WebRTC Error:", err);
      const errorMsg = err instanceof Error ? err.message : "Connection failed";
      setSessionStatus(`Error: ${errorMsg}`);
      stopCall();
    } finally {
      setIsConnecting(false);
    }
  };

  // Stop WebRTC Call
  const stopCall = useCallback(async () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach((t) => t.stop());
      localStreamRef.current = null;
    }

    setIsConnected(false);
    setIsConnecting(false);
    setPersonaState("idle");
    setSessionStatus("Disconnected");
    setAudioLevel(0);

    // Finalize consultation & refresh history
    try {
      await fetch("/api/consultations/end", { method: "POST" });
      await fetchPastConsultations();
    } catch (e) {
      console.debug("Consultation finalization notice:", e);
    }
  }, []);

  // Start fresh consultation meet
  const handleResetConsultation = async () => {
    try {
      await fetch("/api/consultations/reset", { method: "POST" });
      setConversation([]);
      setClinicalState({});
      setTelemetry({});
      await fetchPastConsultations();
      if (isConnected) {
        stopCall();
      }
    } catch (e) {
      console.error("Reset error:", e);
    }
  };

  // Toggle Microphone Mute
  const toggleMute = () => {
    if (localStreamRef.current) {
      const audioTracks = localStreamRef.current.getAudioTracks();
      if (audioTracks.length > 0) {
        const nextState = !audioTracks[0].enabled;
        audioTracks[0].enabled = nextState;
        setIsMuted(!nextState);
      }
    }
  };

  // Poll status, telemetry, clinical state, and conversation with change detection
  const pollStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/status");
      if (!res.ok) return;
      const data = await res.json();

      if (data.status) {
        setSessionStatus((prev) => (prev !== data.status ? data.status : prev));
      }

      if (data.state && ["idle", "listening", "thinking", "speaking", "asleep"].includes(data.state)) {
        setPersonaState((prev) => (prev !== data.state ? (data.state as PersonaState) : prev));
      } else if (data.status) {
        let derivedState: PersonaState = "idle";
        if (data.status.includes("Listening")) {
          derivedState = "listening";
        } else if (
          data.status.includes("Thinking") ||
          data.status.includes("Generating") ||
          data.status.includes("Processing")
        ) {
          derivedState = "thinking";
        } else if (data.status.includes("Speaking")) {
          derivedState = "speaking";
        }
        setPersonaState((prev) => (prev !== derivedState ? derivedState : prev));
      }

      if (data.metrics) {
        setTelemetry((prev) =>
          prev?.turn_id !== data.metrics?.turn_id ||
          prev?.e2e_first_audio_ms !== data.metrics?.e2e_first_audio_ms
            ? data.metrics
            : prev
        );
      }

      if (data.conversation && Array.isArray(data.conversation)) {
        setConversation((prev) => {
          if (prev.length !== data.conversation.length) return data.conversation;
          if (prev.length > 0 && data.conversation.length > 0) {
            const lastPrev = prev[prev.length - 1];
            const lastData = data.conversation[data.conversation.length - 1];
            if (lastPrev.text !== lastData.text || lastPrev.role !== lastData.role) {
              return data.conversation;
            }
          }
          return prev;
        });
      }

      if (data.clinical_state) {
        setClinicalState((prev) =>
          prev?.stage !== data.clinical_state?.stage ||
          prev?.chief_complaint !== data.clinical_state?.chief_complaint ||
          (prev?.symptoms?.length ?? 0) !== (data.clinical_state?.symptoms?.length ?? 0)
            ? data.clinical_state
            : prev
        );
      }

      if (data.active_consultation) {
        setActiveConsultation((prev) =>
          prev?.id !== data.active_consultation?.id ||
          JSON.stringify(prev?.soap_summary) !== JSON.stringify(data.active_consultation?.soap_summary)
            ? data.active_consultation
            : prev
        );
      }
    } catch (e) {
      console.debug("Status poll:", e);
    }
  }, []);

  // Continuous polling on mount (fast when connected, relaxed when idle)
  useEffect(() => {
    pollStatus();
    fetchPastConsultations();

    const intervalTime = isConnected ? 200 : 800;
    const timer = setInterval(() => {
      pollStatus();
    }, intervalTime);

    return () => clearInterval(timer);
  }, [isConnected, pollStatus]);

  const selectedVoiceObj = SARVAM_VOICES.find((v) => v.id === selectedVoice) || SARVAM_VOICES[0];
  const activeStageId = clinicalState.stage || "intake";
  const activeStageIdx = CLINICAL_STAGES.findIndex((s) => s.id === activeStageId);

  return (
    <div className="flex min-h-screen flex-col bg-zinc-950 text-zinc-100 selection:bg-cyan-500 selection:text-black">
      {/* Hidden Audio Element for WebRTC Audio */}
      <audio ref={remoteAudioRef} autoPlay playsInline />

      {/* Navigation Header */}
      <header className="sticky top-0 z-50 flex h-16 items-center justify-between border-b border-zinc-800/80 bg-zinc-950/80 px-6 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 shadow-md shadow-cyan-500/20">
            <Stethoscope className="size-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold tracking-tight text-white">Dr. Maaki</span>
              <span className="rounded-full bg-cyan-950/80 px-2 py-0.5 text-[10px] font-semibold text-cyan-400 border border-cyan-800/50">
                AI Voice Doctor
              </span>
              <span className="rounded-full bg-purple-950/80 px-2 py-0.5 text-[10px] font-semibold text-purple-300 border border-purple-800/50">
                Multi-Meet Context Active
              </span>
            </div>
            <p className="text-xs text-zinc-400">Sarvam Bulbul v3 + Persistent Clinical Memory</p>
          </div>
        </div>

        {/* Global Controls & Selectors */}
        <div className="flex items-center gap-3">
          {/* New Meet Button */}
          <Button
            variant="outline"
            size="sm"
            onClick={handleResetConsultation}
            className="h-9 gap-1.5 border-zinc-800 bg-zinc-900 text-xs text-zinc-300 hover:bg-zinc-800 hover:text-white"
          >
            <PlusCircle className="size-3.5 text-cyan-400" />
            <span>New Meet</span>
          </Button>

          {/* Mic Selector */}
          <MicSelector value={selectedMic} onValueChange={setSelectedMic}>
            <MicSelectorTrigger className="h-9 gap-2 border-zinc-800 bg-zinc-900 text-xs text-zinc-300 hover:bg-zinc-800 hover:text-white">
              <Mic className="size-3.5 text-cyan-400" />
              <MicSelectorValue />
            </MicSelectorTrigger>
            <MicSelectorContent>
              <MicSelectorInput placeholder="Search microphones..." />
              <MicSelectorEmpty>No microphones found.</MicSelectorEmpty>
              <MicSelectorList>
                {(devices) =>
                  devices.map((device) => (
                    <MicSelectorItem key={device.deviceId} value={device.deviceId}>
                      <MicSelectorLabel device={device} />
                    </MicSelectorItem>
                  ))
                }
              </MicSelectorList>
            </MicSelectorContent>
          </MicSelector>

          {/* Voice Selector */}
          <VoiceSelector value={selectedVoice} onValueChange={(val) => val && setSelectedVoice(val)}>
            <VoiceSelectorTrigger render={<Button variant="outline" className="h-9 gap-2 border-zinc-800 bg-zinc-900 text-xs text-zinc-300 hover:bg-zinc-800 hover:text-white" />}>
              <Volume2 className="size-3.5 text-cyan-400" />
              <span>Voice: {selectedVoiceObj.name}</span>
            </VoiceSelectorTrigger>
            <VoiceSelectorContent title="Select Sarvam AI Bulbul Voice">
              <VoiceSelectorInput placeholder="Search voices..." />
              <VoiceSelectorEmpty>No voice found.</VoiceSelectorEmpty>
              <VoiceSelectorList>
                <VoiceSelectorGroup heading="Sarvam Bulbul v3 Indian Voices">
                  {SARVAM_VOICES.map((v) => (
                    <VoiceSelectorItem key={v.id} value={v.id}>
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center gap-2">
                          <VoiceSelectorName>{v.name}</VoiceSelectorName>
                          <VoiceSelectorAttributes>
                            <VoiceSelectorGender value={v.gender} />
                            <VoiceSelectorBullet />
                            <VoiceSelectorAccent value={v.accent} />
                            <VoiceSelectorBullet />
                            <span className="text-xs text-zinc-400">{v.language}</span>
                          </VoiceSelectorAttributes>
                        </div>
                        <VoiceSelectorDescription>{v.description}</VoiceSelectorDescription>
                      </div>
                    </VoiceSelectorItem>
                  ))}
                </VoiceSelectorGroup>
              </VoiceSelectorList>
            </VoiceSelectorContent>
          </VoiceSelector>

          {/* Persona Variant Switcher */}
          <div className="flex items-center rounded-lg border border-zinc-800 bg-zinc-900/90 p-0.5 text-xs text-zinc-400">
            {(["opal", "mana", "obsidian", "halo", "glint", "command"] as const).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setPersonaVariant(v)}
                className={`rounded-md px-2.5 py-1 capitalize transition-all cursor-pointer ${
                  personaVariant === v
                    ? "bg-zinc-800 font-medium text-white shadow-sm"
                    : "hover:text-zinc-200"
                }`}
              >
                {v}
              </button>
            ))}
          </div>
        </div>
      </header>

      {/* Progressive Clinical Stage Stepper Banner */}
      <div className="border-b border-zinc-800/80 bg-zinc-900/40 px-6 py-2.5 backdrop-blur-sm">
        <div className="flex items-center justify-between max-w-5xl mx-auto gap-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-400">
            <Activity className="size-3.5 text-cyan-400" />
            <span>Consultation Stage:</span>
          </div>
          <div className="flex items-center gap-1 sm:gap-2 flex-1 max-w-2xl">
            {CLINICAL_STAGES.map((stg, i) => {
              const isCurrent = stg.id === activeStageId;
              const isPast = i < activeStageIdx;
              return (
                <div
                  key={stg.id}
                  className={`flex-1 flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[11px] font-medium transition-all ${
                    isCurrent
                      ? "bg-cyan-950/70 border-cyan-500/50 text-cyan-300 shadow-sm shadow-cyan-500/10 animate-pulse"
                      : isPast
                      ? "bg-emerald-950/30 border-emerald-800/40 text-emerald-300"
                      : "bg-zinc-900/50 border-zinc-800/60 text-zinc-500"
                  }`}
                >
                  {isPast ? (
                    <Check className="size-3 text-emerald-400 shrink-0" />
                  ) : (
                    <span className="size-1.5 rounded-full bg-current shrink-0" />
                  )}
                  <span className="truncate">{stg.label}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Main Experience Layout */}
      <main className="flex flex-1 flex-col lg:flex-row overflow-hidden">
        {/* Left / Center: Interactive Voice Persona Stage */}
        <section className="flex flex-1 flex-col items-center justify-between p-6 sm:p-8 border-b lg:border-b-0 lg:border-r border-zinc-800/80 bg-radial from-zinc-900/50 via-zinc-950 to-zinc-950">
          {/* Status Badge & Clinical Live Pill */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 rounded-full border border-zinc-800/80 bg-zinc-900/70 px-4 py-1.5 backdrop-blur-md">
              <span
                className={`size-2.5 rounded-full transition-all ${
                  isConnected
                    ? personaState === "speaking"
                      ? "bg-purple-400 animate-ping"
                      : personaState === "thinking"
                      ? "bg-amber-400 animate-pulse"
                      : "bg-emerald-400"
                    : isConnecting
                    ? "bg-amber-400 animate-pulse"
                    : "bg-zinc-500"
                }`}
              />
              <span className="text-xs font-medium text-zinc-300 capitalize">{sessionStatus}</span>
            </div>

            {clinicalState.chief_complaint && (
              <div className="flex items-center gap-1.5 rounded-full border border-cyan-800/40 bg-cyan-950/40 px-3 py-1 text-[11px] text-cyan-300">
                <HeartPulse className="size-3 text-cyan-400" />
                <span>Issue: {clinicalState.chief_complaint}</span>
              </div>
            )}
          </div>

          {/* Animated AI Persona Visual (Rive WebGL2) */}
          <div className="relative flex size-64 sm:size-80 items-center justify-center my-4">
            <div
              className={`absolute inset-0 rounded-full blur-3xl transition-opacity duration-700 pointer-events-none ${
                personaState === "speaking"
                  ? "bg-purple-600/30 opacity-100"
                  : personaState === "thinking"
                  ? "bg-blue-600/25 opacity-100"
                  : personaState === "listening"
                  ? "bg-cyan-500/20 opacity-100"
                  : "bg-zinc-700/10 opacity-40"
              }`}
            />
            <Persona
              state={personaState}
              variant={personaVariant}
              className="size-full z-10"
            />
          </div>

          {/* Live Context Quick Bar */}
          {clinicalState.symptoms && clinicalState.symptoms.length > 0 && (
            <div className="flex flex-wrap items-center justify-center gap-1.5 max-w-md my-1">
              <span className="text-[10px] uppercase tracking-wider text-zinc-500 mr-1">Identified:</span>
              {clinicalState.symptoms.map((sym, idx) => (
                <span
                  key={idx}
                  className="rounded-md bg-zinc-800/70 px-2 py-0.5 text-[11px] font-medium text-zinc-300 border border-zinc-700/50"
                >
                  {sym}
                </span>
              ))}
              {clinicalState.duration && (
                <span className="rounded-md bg-amber-950/40 px-2 py-0.5 text-[11px] font-medium text-amber-300 border border-amber-800/40">
                  ⏱ {clinicalState.duration}
                </span>
              )}
              {clinicalState.severity && (
                <span className="rounded-md bg-red-950/40 px-2 py-0.5 text-[11px] font-medium text-red-300 border border-red-800/40">
                  ⚡ {clinicalState.severity}
                </span>
              )}
            </div>
          )}

          {/* Real-time Interaction Bar */}
          <div className="flex flex-col items-center gap-4 w-full max-w-md">
            {/* Live Mic Activity Visualizer */}
            {isConnected && (
              <div className="flex items-center gap-2 w-full max-w-xs">
                <Mic className="size-3.5 text-zinc-400" />
                <div className="h-1.5 flex-1 rounded-full bg-zinc-800 overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-cyan-500 to-emerald-400 transition-all duration-75"
                    style={{ width: `${isMuted ? 0 : audioLevel}%` }}
                  />
                </div>
                <span className="text-[10px] font-medium text-zinc-400 w-8 text-right">
                  {isMuted ? "Muted" : `${audioLevel}%`}
                </span>
              </div>
            )}

            {/* Action Buttons */}
            <div className="flex items-center gap-4">
              {!isConnected ? (
                <Button
                  size="lg"
                  onClick={startCall}
                  disabled={isConnecting}
                  className="h-13 px-8 rounded-full bg-gradient-to-r from-cyan-500 via-blue-500 to-indigo-600 text-white font-semibold shadow-lg shadow-cyan-500/25 hover:opacity-95 transition-all hover:scale-[1.02] active:scale-[0.98] cursor-pointer"
                >
                  <PhoneCall className="mr-2 size-5" />
                  {isConnecting ? "Connecting..." : "Start Consultation"}
                </Button>
              ) : (
                <>
                  <Button
                    size="lg"
                    variant={isMuted ? "destructive" : "secondary"}
                    onClick={toggleMute}
                    className="size-13 rounded-full p-0 shadow-md transition-all cursor-pointer"
                  >
                    {isMuted ? <MicOff className="size-5" /> : <Mic className="size-5" />}
                  </Button>
                  <Button
                    size="lg"
                    variant="destructive"
                    onClick={stopCall}
                    className="h-13 px-8 rounded-full font-semibold shadow-lg shadow-red-500/20 hover:opacity-90 transition-all active:scale-[0.98] cursor-pointer"
                  >
                    <PhoneOff className="mr-2 size-5" />
                    End Call
                  </Button>
                </>
              )}
            </div>

            <p className="text-xs text-zinc-500 text-center">
              Speak naturally. Dr. Maaki remembers your symptoms and builds context progressively.
            </p>
          </div>
        </section>

        {/* Right: Telemetry, Clinical Context, Transcript & Past Meets Panel */}
        <aside className="w-full lg:w-[500px] flex flex-col justify-between p-6 bg-zinc-950 border-t lg:border-t-0 overflow-y-auto">
          <div className="flex flex-col gap-5">
            {/* View Mode Navigation Tabs */}
            <div className="flex items-center rounded-xl border border-zinc-800 bg-zinc-900/80 p-1 text-xs">
              <button
                type="button"
                onClick={() => setActiveTab("transcript")}
                className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg font-medium transition-all cursor-pointer ${
                  activeTab === "transcript"
                    ? "bg-zinc-800 text-cyan-300 shadow-sm"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                <Radio className="size-3.5" />
                <span>Live Transcript</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("clinical_context")}
                className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg font-medium transition-all cursor-pointer ${
                  activeTab === "clinical_context"
                    ? "bg-zinc-800 text-purple-300 shadow-sm"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                <FileText className="size-3.5" />
                <span>SOAP & Context</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  fetchPastConsultations();
                  setActiveTab("past_meets");
                }}
                className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg font-medium transition-all cursor-pointer ${
                  activeTab === "past_meets"
                    ? "bg-zinc-800 text-emerald-300 shadow-sm"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                <History className="size-3.5" />
                <span>Past Meets ({pastConsultations.length})</span>
              </button>
            </div>

            {/* Telemetry Metrics Card */}
            <div>
              <div className="flex items-center justify-between mb-2.5">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">
                  <Zap className="size-3.5 text-cyan-400" />
                  <span>Pipeline Latency Breakdown</span>
                </div>
                <span className="text-[11px] font-medium text-zinc-400">
                  Turn #{telemetry.turn_id ?? 0}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-2.5">
                  <div className="text-base font-bold font-sans text-cyan-400">
                    {telemetry.stt_first_partial_ms != null ? `${telemetry.stt_first_partial_ms} ms` : "-- ms"}
                  </div>
                  <div className="text-[9px] text-zinc-400 uppercase tracking-wider mt-0.5">
                    STT Partial
                  </div>
                </div>

                <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-2.5">
                  <div className="text-base font-bold font-sans text-blue-400">
                    {telemetry.stt_final_ms != null ? `${telemetry.stt_final_ms} ms` : "-- ms"}
                  </div>
                  <div className="text-[9px] text-zinc-400 uppercase tracking-wider mt-0.5">
                    STT Final
                  </div>
                </div>

                <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-2.5">
                  <div className="text-base font-bold font-sans text-amber-400">
                    {telemetry.llm_first_token_ms != null ? `${telemetry.llm_first_token_ms} ms` : "-- ms"}
                  </div>
                  <div className="text-[9px] text-zinc-400 uppercase tracking-wider mt-0.5">
                    LLM TTFT
                  </div>
                </div>

                <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-2.5">
                  <div className="text-base font-bold font-sans text-purple-400">
                    {telemetry.tts_first_audio_ms != null ? `${telemetry.tts_first_audio_ms} ms` : "-- ms"}
                  </div>
                  <div className="text-[9px] text-zinc-400 uppercase tracking-wider mt-0.5">
                    TTS TTFB
                  </div>
                </div>

                <div className="col-span-2 sm:col-span-2 rounded-xl border border-emerald-500/30 bg-emerald-950/20 p-2.5">
                  <div className="text-base font-bold font-sans text-emerald-400">
                    {telemetry.e2e_first_audio_ms != null ? `${telemetry.e2e_first_audio_ms} ms` : "-- ms"}
                  </div>
                  <div className="text-[9px] text-emerald-300 uppercase tracking-wider mt-0.5 font-semibold flex items-center gap-1">
                    <Zap className="size-3 text-emerald-400" />
                    ⚡ E2E First Audio (User Speech → Voice)
                  </div>
                </div>
              </div>
            </div>

            <Separator className="bg-zinc-800/80" />

            {/* TAB CONTENT 1: Live Consultation Transcript */}
            {activeTab === "transcript" && (
              <div className="flex flex-col flex-1">
                <div className="flex items-center justify-between mb-2.5">
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">
                    <Radio className="size-3.5 text-cyan-400 animate-pulse" />
                    <span>Live Consultation Transcript</span>
                  </div>
                  <span className="text-[11px] text-zinc-400 font-mono">
                    {conversation.length} message{conversation.length !== 1 ? "s" : ""}
                  </span>
                </div>

                <div className="flex-1 rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-3.5 min-h-[240px] max-h-[380px] overflow-y-auto space-y-2.5">
                  {conversation.length === 0 ? (
                    <div className="flex h-full min-h-[180px] flex-col items-center justify-center text-center p-6 text-zinc-500">
                      <HeartPulse className="size-8 mb-2 opacity-50 text-cyan-400" />
                      <p className="text-xs font-medium text-zinc-300">Ready for Consultation</p>
                      <p className="text-[11px] text-zinc-500 mt-1 max-w-xs">
                        Click &quot;Start Consultation&quot; and describe your symptoms to Dr. Maaki.
                      </p>
                    </div>
                  ) : (
                    <>
                      {conversation.map((msg, index) => {
                        const isUser = msg.role === "user";
                        return (
                          <div
                            key={index}
                            className={`flex flex-col gap-1 text-xs leading-relaxed p-3 rounded-xl transition-all shadow-sm ${
                              isUser
                                ? "bg-zinc-800/90 text-zinc-100 border border-zinc-700/60 ml-3"
                                : "bg-cyan-950/70 text-cyan-50 border border-cyan-800/60 mr-3"
                            }`}
                          >
                            <div className="flex items-center justify-between">
                              <span
                                className={`font-bold text-[11px] flex items-center gap-1.5 ${
                                  isUser ? "text-cyan-400" : "text-emerald-400"
                                }`}
                              >
                                {isUser ? "👤 You (Patient)" : "🩺 Dr. Maaki"}
                              </span>
                            </div>
                            <p className="text-xs text-zinc-200 mt-0.5 whitespace-pre-wrap">{msg.text}</p>
                          </div>
                        );
                      })}
                      <div ref={chatEndRef} />
                    </>
                  )}
                </div>
              </div>
            )}

            {/* TAB CONTENT 2: Clinical Context & Live SOAP Note */}
            {activeTab === "clinical_context" && (
              <div className="flex flex-col flex-1 gap-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-purple-300">
                    <ClipboardList className="size-3.5 text-purple-400" />
                    <span>Clinical Context & SOAP Note</span>
                  </div>
                  <span className="text-[10px] rounded-full bg-purple-950/60 border border-purple-800/50 px-2.5 py-0.5 text-purple-300 font-medium">
                    Live Telemetry
                  </span>
                </div>

                <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-4 space-y-3.5 text-xs max-h-[380px] overflow-y-auto">
                  {/* Chief Complaint & Duration / Severity */}
                  <div className="grid grid-cols-2 gap-2">
                    <div className="p-3 rounded-xl bg-zinc-900/90 border border-zinc-800">
                      <div className="text-[10px] text-zinc-400 uppercase font-semibold">Chief Complaint</div>
                      <div className="font-semibold text-cyan-300 mt-1">
                        {clinicalState.chief_complaint || "Awaiting patient intake"}
                      </div>
                    </div>
                    <div className="p-3 rounded-xl bg-zinc-900/90 border border-zinc-800">
                      <div className="text-[10px] text-zinc-400 uppercase font-semibold">Duration / Severity</div>
                      <div className="font-medium text-amber-300 mt-1">
                        {[clinicalState.duration, clinicalState.severity].filter(Boolean).join(" • ") || "Assessing..."}
                      </div>
                    </div>
                  </div>

                  {/* Symptoms List */}
                  <div className="p-3 rounded-xl bg-zinc-900/90 border border-zinc-800">
                    <div className="text-[10px] text-zinc-400 uppercase font-semibold mb-1.5">Identified Symptoms</div>
                    {clinicalState.symptoms && clinicalState.symptoms.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {clinicalState.symptoms.map((s, i) => (
                          <span key={i} className="px-2.5 py-1 rounded-lg bg-cyan-950/70 border border-cyan-700/50 text-cyan-200 text-[11px] font-medium">
                            {s}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <p className="text-zinc-500 italic text-[11px]">No specific symptoms extracted yet.</p>
                    )}
                  </div>

                  {/* Doctor's Advice & Recommendations */}
                  <div className="p-3 rounded-xl bg-zinc-900/90 border border-zinc-800">
                    <div className="text-[10px] text-zinc-400 uppercase font-semibold mb-1.5">Clinical Recommendations</div>
                    {clinicalState.recommendations && clinicalState.recommendations.length > 0 ? (
                      <ul className="space-y-1.5 text-emerald-200 text-[11px]">
                        {clinicalState.recommendations.map((rec, i) => (
                          <li key={i} className="flex items-start gap-1.5 leading-snug">
                            <span className="text-emerald-400 font-bold shrink-0">•</span>
                            <span>{rec}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-zinc-500 italic text-[11px]">Doctor will provide tailored advice during consultation.</p>
                    )}
                  </div>

                  {/* Generated SOAP Summary if available */}
                  {activeConsultation?.soap_summary && Object.keys(activeConsultation.soap_summary).length > 0 && (
                    <div className="p-3 rounded-xl bg-purple-950/30 border border-purple-800/40 space-y-2">
                      <div className="text-[10px] text-purple-300 uppercase font-bold tracking-wider">SOAP Note Summary</div>
                      {activeConsultation.soap_summary.subjective && (
                        <p className="text-[11px] text-zinc-300">
                          <strong className="text-purple-300">S (Subjective):</strong> {activeConsultation.soap_summary.subjective}
                        </p>
                      )}
                      {activeConsultation.soap_summary.assessment && (
                        <p className="text-[11px] text-zinc-300">
                          <strong className="text-purple-300">A (Assessment):</strong> {activeConsultation.soap_summary.assessment}
                        </p>
                      )}
                      {activeConsultation.soap_summary.plan && (
                        <p className="text-[11px] text-emerald-300">
                          <strong className="text-emerald-400">P (Plan):</strong> {activeConsultation.soap_summary.plan}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB CONTENT 3: Past Consultation Meets History */}
            {activeTab === "past_meets" && (
              <div className="flex flex-col flex-1 gap-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-emerald-300">
                    <History className="size-3.5 text-emerald-400" />
                    <span>Patient Consultation Records</span>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={fetchPastConsultations}
                    className="h-6 text-[11px] text-zinc-400 hover:text-white"
                  >
                    Refresh
                  </Button>
                </div>

                <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-3 space-y-2.5 text-xs max-h-[380px] overflow-y-auto">
                  {pastConsultations.length === 0 ? (
                    <div className="p-8 text-center text-zinc-500">
                      <Clock className="size-8 mx-auto mb-2 opacity-40 text-emerald-400" />
                      <p className="font-semibold text-xs text-zinc-300">No previous consultation meets</p>
                      <p className="text-[11px] text-zinc-500 mt-1">Concluded consultations are automatically saved here with full SOAP notes.</p>
                    </div>
                  ) : (
                    pastConsultations.map((meet) => (
                      <div
                        key={meet.id}
                        className="p-3.5 rounded-xl border border-zinc-800 bg-zinc-900/90 hover:border-zinc-700 transition-all space-y-2"
                      >
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="font-bold text-cyan-300 text-xs">{meet.chief_complaint}</span>
                          <span className="text-zinc-500 font-mono">{meet.started_at.slice(0, 10)}</span>
                        </div>
                        {meet.symptoms && meet.symptoms.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {meet.symptoms.map((s, idx) => (
                              <span key={idx} className="px-2 py-0.5 rounded-md text-[10px] font-medium bg-zinc-800 text-zinc-300 border border-zinc-700/50">
                                {s}
                              </span>
                            ))}
                          </div>
                        )}
                        {meet.soap_summary?.assessment && (
                          <p className="text-[11px] text-zinc-300 leading-snug">
                            <span className="text-purple-400 font-semibold">Assessment: </span>
                            {meet.soap_summary.assessment}
                          </p>
                        )}
                        {meet.soap_summary?.plan && (
                          <p className="text-[11px] text-emerald-300 leading-snug">
                            <span className="text-emerald-400 font-semibold">Plan: </span>
                            {meet.soap_summary.plan}
                          </p>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Footer Info */}
          <div className="mt-5 flex items-center justify-between text-[11px] text-zinc-400 border-t border-zinc-800/60 pt-3.5">
            <span className="flex items-center gap-1.5">
              <CheckCircle2 className="size-3 text-emerald-400" /> WebRTC P2P + Context Bridge
            </span>
            <span>Sarvam Saaras v3 + Bulbul v3</span>
          </div>
        </aside>
      </main>
    </div>
  );
}
