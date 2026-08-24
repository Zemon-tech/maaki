"""Consultation context engine and persistent medical memory manager for Dr. Maaki."""

from datetime import datetime
import json
from pathlib import Path
from typing import Any
import uuid
from loguru import logger
from pydantic import BaseModel, Field


DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONSULTATIONS_FILE = DATA_DIR / "consultations.json"


def _generate_session_id() -> str:
    """Unique meet ID: second-resolution timestamp collides when sessions start
    back-to-back, which would make finalize overwrite the earlier record."""
    return f"meet-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


class ClinicalState(BaseModel):
    """Structured clinical state built progressively throughout the consultation."""
    stage: str = Field(
        default="intake",
        description="Current clinical stage: 'intake' | 'exploration' | 'history' | 'assessment' | 'wrapup'"
    )
    chief_complaint: str = Field(default="", description="Primary symptom or reason for visit")
    symptoms: list[str] = Field(default_factory=list, description="Identified symptoms")
    duration: str = Field(default="", description="Duration of symptoms")
    severity: str = Field(default="", description="Severity / intensity (e.g., mild, moderate, severe, 8/10)")
    location: str = Field(default="", description="Anatomical location of symptom")
    associated_symptoms: list[str] = Field(default_factory=list, description="Associated symptoms")
    past_history: str = Field(default="", description="Relevant medical or surgical history")
    current_medications: list[str] = Field(default_factory=list, description="Current medications or treatments")
    allergies: list[str] = Field(default_factory=list, description="Known allergies")
    clinical_impressions: list[str] = Field(default_factory=list, description="Possible causes / differentials explored")
    recommendations: list[str] = Field(default_factory=list, description="Doctor's advice and red flags mentioned")


class ConsultationRecord(BaseModel):
    """A persistent record of a completed or active consultation meet."""
    id: str
    patient_name: str = "Patient"
    started_at: str
    ended_at: str | None = None
    clinical_state: ClinicalState = Field(default_factory=ClinicalState)
    messages: list[dict[str, str]] = Field(default_factory=list)
    soap_summary: dict[str, str] = Field(
        default_factory=lambda: {
            "subjective": "",
            "objective": "Tele-consultation via voice AI assessment.",
            "assessment": "",
            "plan": "",
        }
    )


class ConsultationManager:
    """Manages consultation state within a meet and persists history across meets."""

    def __init__(self):
        self.active_consultation: ConsultationRecord | None = None
        self._consultations: list[ConsultationRecord] = []
        self._load_history()
        self.ensure_active_consultation()

    def _load_history(self):
        """Load past consultation records from disk."""
        if CONSULTATIONS_FILE.exists():
            try:
                with open(CONSULTATIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._consultations = [ConsultationRecord(**item) for item in data]
                logger.info(f"Loaded {len(self._consultations)} past consultation records.")
            except Exception as e:
                logger.error(f"Error loading consultations history: {e}")
                self._consultations = []
        else:
            self._consultations = []

    def _save_history(self):
        """Save consultation records to disk."""
        try:
            with open(CONSULTATIONS_FILE, "w", encoding="utf-8") as f:
                json.dump([c.model_dump() for c in self._consultations], f, indent=2)
        except Exception as e:
            logger.error(f"Error saving consultations history: {e}")

    def ensure_active_consultation(self):
        """Start a new consultation record if none is active (e.g. on first connect)."""
        if not self.active_consultation:
            self.active_consultation = ConsultationRecord(
                id=_generate_session_id(),
                started_at=datetime.now().isoformat(),
            )

    def start_new_consultation(self, patient_name: str = "Patient") -> ConsultationRecord:
        """Start a brand new consultation session."""
        if self.active_consultation and self.active_consultation.messages:
            self.finalize_active_consultation()

        self.active_consultation = ConsultationRecord(
            id=_generate_session_id(),
            patient_name=patient_name,
            started_at=datetime.now().isoformat(),
        )
        return self.active_consultation

    def get_past_consultations(self) -> list[dict[str, Any]]:
        """Return list of past consultation summaries for UI display."""
        records = []
        for c in reversed(self._consultations):
            records.append({
                "id": c.id,
                "patient_name": c.patient_name,
                "started_at": c.started_at,
                "ended_at": c.ended_at,
                "chief_complaint": c.clinical_state.chief_complaint or "General Consultation",
                "stage": c.clinical_state.stage,
                "symptoms": c.clinical_state.symptoms,
                "soap_summary": c.soap_summary,
                "message_count": len(c.messages),
            })
        return records

    def get_historical_context_prompt(self) -> str:
        """Construct a concise clinical summary of prior consultations to inject into LLM system prompt."""
        if not self._consultations:
            return ""

        recent_meets = self._consultations[-3:]  # Last 3 meets
        history_lines = ["\n[PREVIOUS CONSULTATION HISTORY FOR THIS PATIENT]:"]
        for meet in recent_meets:
            dt = meet.started_at[:10] if meet.started_at else "Previous meet"
            cc = meet.clinical_state.chief_complaint or "Consultation"
            assessment = meet.soap_summary.get("assessment") or ", ".join(meet.clinical_state.clinical_impressions) or "Assessment completed"
            plan = meet.soap_summary.get("plan") or ", ".join(meet.clinical_state.recommendations) or "Advised follow-up"
            history_lines.append(f"- Meet ({dt}): Chief Complaint: {cc} | Assessment: {assessment} | Plan: {plan}")

        history_lines.append("Use this prior context seamlessly if the patient references past visits or recurring issues.\n")
        return "\n".join(history_lines)

    def record_turn(self, role: str, text: str):
        """Record a transcript message in active consultation and update clinical state."""
        if not self.active_consultation:
            self.ensure_active_consultation()

        assert self.active_consultation is not None
        self.active_consultation.messages.append({"role": role, "text": text})

        # Update clinical state heuristically / progressively
        self._update_clinical_state(role, text)

    def _update_clinical_state(self, role: str, text: str):
        """Progressively update consultation clinical state based on conversation cues."""
        if not self.active_consultation:
            return

        state = self.active_consultation.clinical_state
        msg_count = len(self.active_consultation.messages)
        t_lower = text.lower()

        # Update clinical stage progression
        if msg_count <= 2:
            state.stage = "intake"
        elif msg_count <= 6:
            state.stage = "exploration"
        elif msg_count <= 10:
            state.stage = "history"
        elif msg_count <= 16:
            state.stage = "assessment"
        else:
            state.stage = "wrapup"

        # Extract Chief Complaint / Symptoms if user turn
        if role == "user":
            # Check duration cues
            duration_cues = ["days", "day", "hours", "hour", "weeks", "week", "months", "month", "yesterday", "morning", "since"]
            for cue in duration_cues:
                if cue in t_lower and not state.duration:
                    state.duration = text.strip()
                    break

            # Check severity cues
            severity_cues = ["severe", "mild", "moderate", "terrible", "unbearable", "sharp", "dull", "throbbing", "burning"]
            for s in severity_cues:
                if s in t_lower and not state.severity:
                    state.severity = s.capitalize()
                    break

            # Check common symptoms
            symptom_keywords = [
                "headache", "fever", "cough", "cold", "throat pain", "sore throat", "chest pain",
                "back pain", "stomach ache", "nausea", "vomiting", "dizziness", "fatigue",
                "shortness of breath", "rash", "joint pain", "diarrhea", "migraine", "body ache"
            ]
            for sym in symptom_keywords:
                if sym in t_lower and sym not in [s.lower() for s in state.symptoms]:
                    state.symptoms.append(sym.title())
                    if not state.chief_complaint:
                        state.chief_complaint = sym.title()

        elif role == "assistant":
            # Extract doctor recommendations/advice
            if any(k in t_lower for k in ["recommend", "suggest", "take", "rest", "drink", "prescribe", "consult", "hospital", "urgent", "test", "visit"]):
                if text not in state.recommendations:
                    state.recommendations.append(text)

    def finalize_active_consultation(self) -> ConsultationRecord | None:
        """Finalize active consultation, generate SOAP note summary, save to disk,
        and clear the active record so the next session starts fresh."""
        if not self.active_consultation or not self.active_consultation.messages:
            self.active_consultation = None
            return None

        self.active_consultation.ended_at = datetime.now().isoformat()
        state = self.active_consultation.clinical_state

        # Build comprehensive SOAP Note
        user_msgs = [m["text"] for m in self.active_consultation.messages if m["role"] == "user"]
        assistant_msgs = [m["text"] for m in self.active_consultation.messages if m["role"] == "assistant"]

        symptoms_str = ", ".join(state.symptoms) if state.symptoms else (state.chief_complaint or "Symptoms reported during consultation")
        duration_str = f" Duration: {state.duration}." if state.duration else ""
        severity_str = f" Severity: {state.severity}." if state.severity else ""

        subjective = f"Patient presented with {symptoms_str}.{duration_str}{severity_str}"
        if user_msgs:
            subjective += f" Reported details: {' '.join(user_msgs[:3])}"

        assessment = "Clinical evaluation based on reported symptoms."
        if state.symptoms:
            assessment = f"Evaluation of {', '.join(state.symptoms)}. Possible viral or tension-related etiology, pending clinical exam."

        plan = " ".join(state.recommendations[-2:]) if state.recommendations else "Hydration, symptomatic rest, and in-person clinical follow-up if symptoms persist or red flags appear."

        self.active_consultation.soap_summary = {
            "subjective": subjective,
            "objective": "Tele-consultation conversational assessment via Dr. Maaki Voice AI.",
            "assessment": assessment,
            "plan": plan,
        }

        # Check if already in list
        existing_idx = next((i for i, c in enumerate(self._consultations) if c.id == self.active_consultation.id), None)
        if existing_idx is not None:
            self._consultations[existing_idx] = self.active_consultation
        else:
            self._consultations.append(self.active_consultation)

        self._save_history()
        logger.info(f"Finalized consultation {self.active_consultation.id} with SOAP note.")
        finalized = self.active_consultation
        self.active_consultation = None
        return finalized


consultation_manager = ConsultationManager()
