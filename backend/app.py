"""Main application server integrating FastAPI, Pipecat SmallWebRTC, and Gradio UI."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import gradio as gr
from loguru import logger
import uvicorn

from pipecat.transports.smallwebrtc.connection import IceServer
from pipecat.transports.smallwebrtc.request_handler import (
    ConnectionMode,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

from agent import create_and_run_agent
from config import AppConfig, check_llm_reachability, check_local_llm_reachability, get_config, print_startup_banner
from latency import metrics_store
from ui import HEAD_CONTENT, create_ui

# Global config
config: AppConfig = get_config()

# WebRTC request handler with standard Google STUN server
ice_servers = [IceServer(urls="stun:stun.l.google.com:19302")]
webrtc_handler = SmallWebRTCRequestHandler(
    ice_servers=ice_servers,
    connection_mode=ConnectionMode.SINGLE,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup validation
    llm_reachable, llm_message = check_llm_reachability(config)
    print_startup_banner(config, llm_reachable, llm_message)

    if not config.sarvam_api_key:
        logger.warning("SARVAM_API_KEY is not set. Please update your .env file to enable STT & TTS.")

    yield

    # Shutdown cleanup
    logger.info("Shutting down WebRTC connections...")
    await webrtc_handler.close()


app = FastAPI(title="Ultra-Low-Latency Local LLM Voice Assistant", lifespan=lifespan)

# Allow CORS for local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/offer")
async def handle_webrtc_offer(request: Request):
    """Handle WebRTC SDP offer and launch Pipecat pipeline for the connection."""
    try:
        body = await request.json()
        selected_voice = body.get("voice") or config.sarvam_tts_voice
        webrtc_payload = {k: v for k, v in body.items() if k != "voice"}
        webrtc_req = SmallWebRTCRequest.from_dict(webrtc_payload)

        async def connection_callback(conn):
            # Launch agent in background task for this connection with custom voice
            asyncio.create_task(create_and_run_agent(conn, config, voice=selected_voice))

        answer = await webrtc_handler.handle_web_request(
            request=webrtc_req,
            webrtc_connection_callback=connection_callback,
        )
        return answer
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling WebRTC offer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/offer")
async def handle_webrtc_patch(request: Request):
    """Handle WebRTC ICE candidate patching."""
    try:
        body = await request.json()
        patch_req = SmallWebRTCPatchRequest(**body)
        await webrtc_handler.handle_patch_request(patch_req)
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling WebRTC patch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


from consultation import consultation_manager


@app.get("/api/status")
async def get_pipeline_status():
    """Retrieve real-time latency metrics, conversation feed, connection status, and clinical context."""
    return {
        "status": metrics_store.status,
        "state": metrics_store.state,
        "metrics": asdict(metrics_store.latest_metrics),
        "conversation": metrics_store.conversation,
        "clinical_state": metrics_store.get_clinical_state(),
        "active_consultation": metrics_store.get_active_consultation(),
    }


@app.get("/api/consultations")
async def list_past_consultations():
    """Retrieve past consultation meet records and SOAP notes for the patient."""
    return {
        "consultations": consultation_manager.get_past_consultations(),
        "current": metrics_store.get_active_consultation(),
    }


@app.get("/api/consultations/current")
async def get_current_consultation():
    """Retrieve active consultation clinical state and messages."""
    return {
        "consultation": metrics_store.get_active_consultation(),
        "clinical_state": metrics_store.get_clinical_state(),
    }


@app.post("/api/consultations/end")
async def end_current_consultation():
    """Finalize active consultation, generate SOAP note, and save record."""
    record = consultation_manager.finalize_active_consultation()
    return {
        "status": "finalized",
        "consultation": record.model_dump() if record else None,
    }


@app.post("/api/consultations/reset")
async def reset_consultation():
    """Reset metrics and start a fresh consultation meet session."""
    metrics_store.reset()
    record = consultation_manager.start_new_consultation()
    return {
        "status": "started",
        "consultation": record.model_dump(),
    }


@app.get("/api/health")
async def health_check():
    """Simple health check endpoint."""
    llm_reachable, llm_msg = check_llm_reachability(config)
    return {
        "status": "ok",
        "sarvam_configured": bool(config.sarvam_api_key),
        "llm_provider": config.llm_provider,
        "llm": {
            "provider": config.llm_provider,
            "endpoint": config.active_llm_base_url,
            "model": config.active_llm_model,
            "reachable": llm_reachable,
            "message": llm_msg,
        },
        # Legacy key kept for backwards-compatibility
        "local_llm": {
            "endpoint": config.local_llm_base_url,
            "model": config.local_llm_model,
            "reachable": llm_reachable if not config.is_openrouter else None,
            "message": llm_msg if not config.is_openrouter else "N/A (OpenRouter active)",
        },
    }


# Mount Gradio Blocks UI onto FastAPI root
gradio_ui = create_ui(config)
app = gr.mount_gradio_app(app, gradio_ui, path="/", head=HEAD_CONTENT)


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host=config.host,
        port=config.port,
        reload=False,
        log_level="info",
    )
