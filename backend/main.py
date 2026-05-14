"""main.py – Voice Agent Integrator backend.

WebSocket flow
--------------
1. Browser connects via  ws://<host>/ws
2. Browser sends binary frames (WebM/Opus audio chunks) while the user speaks.
3. Browser sends  {"type": "end_of_speech"}  when the user stops speaking.
4. Server transcribes the audio with OpenAI Whisper.
5. Server queries the configured chatbot and receives {"msg": "…"}.
6. Server sends  {"type": "speak", "text": "…"}  back to the browser.
7. Browser's Web Speech API speaks the text aloud.
8. Loop back to step 2 for the next turn.

Status messages of shape  {"type": "status", "text": "…"}  are sent during
processing so the UI can show a progress indicator.

Error messages of shape  {"type": "error", "text": "…"}  are sent on failure.
"""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# Load .env from the same directory as this file
load_dotenv(Path(__file__).parent / ".env")

from chatbot import get_response  # noqa: E402 – import after dotenv
from stt import transcribe_audio  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Voice Agent Integrator")

# Serve the frontend from ../frontend
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    log.info("Client connected: %s", websocket.client)

    audio_chunks: list[bytes] = []

    try:
        while True:
            message = await websocket.receive()

            # ── Binary frame: audio chunk ──────────────────────────────────
            if "bytes" in message and message["bytes"] is not None:
                audio_chunks.append(message["bytes"])
                continue

            # ── Text frame: control message ────────────────────────────────
            if "text" not in message or message["text"] is None:
                continue

            try:
                payload = json.loads(message["text"])
            except json.JSONDecodeError:
                await websocket.send_json(
                    {"type": "error", "text": "Invalid JSON control message."}
                )
                continue

            msg_type = payload.get("type", "")

            if msg_type == "end_of_speech":
                if not audio_chunks:
                    await websocket.send_json(
                        {"type": "error", "text": "No audio received."}
                    )
                    continue

                audio_data = b"".join(audio_chunks)
                audio_chunks = []
                log.info("Received %d bytes of audio.", len(audio_data))

                # ── Step 1: Transcribe ─────────────────────────────────────
                await websocket.send_json(
                    {"type": "status", "text": "Transcribing…"}
                )
                try:
                    transcript = await transcribe_audio(audio_data)
                except Exception as exc:
                    log.exception("STT error: %s", exc)
                    await websocket.send_json(
                        {"type": "error", "text": f"Transcription failed: {exc}"}
                    )
                    continue

                if not transcript:
                    await websocket.send_json(
                        {"type": "error", "text": "Could not detect speech. Please try again."}
                    )
                    continue

                log.info("Transcript: %s", transcript)
                await websocket.send_json(
                    {"type": "transcript", "text": transcript}
                )

                # ── Step 2: Chatbot ────────────────────────────────────────
                await websocket.send_json(
                    {"type": "status", "text": "Thinking…"}
                )
                try:
                    reply = await get_response(transcript)
                except Exception as exc:
                    log.exception("Chatbot error: %s", exc)
                    await websocket.send_json(
                        {"type": "error", "text": f"Chatbot error: {exc}"}
                    )
                    continue

                if not reply:
                    await websocket.send_json(
                        {"type": "error", "text": "Chatbot returned an empty response."}
                    )
                    continue

                log.info("Agent reply: %s", reply)

                # ── Step 3: Send text for TTS ──────────────────────────────
                await websocket.send_json({"type": "speak", "text": reply})

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                log.warning("Unknown message type: %s", msg_type)

    except WebSocketDisconnect:
        log.info("Client disconnected: %s", websocket.client)
    except Exception as exc:
        log.exception("Unexpected WebSocket error: %s", exc)
        try:
            await websocket.send_json(
                {"type": "error", "text": f"Server error: {exc}"}
            )
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
