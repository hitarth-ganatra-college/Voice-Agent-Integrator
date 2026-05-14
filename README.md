# Voice-Agent-Integrator

A real-time voice-call interface that connects a browser user to an AI agent.

```
Browser mic  →  WebSocket  →  Whisper STT  →  Chatbot (JSON {"msg":"…"})
                                                        ↓
Browser Web Speech API  ←  WebSocket  ←  reply text
```

---

## Architecture

| Layer | Technology |
|---|---|
| Frontend | Plain HTML + JavaScript (MediaRecorder API, Web Audio API, Web Speech API) |
| Transport | WebSocket (`/ws`) |
| STT | OpenAI Whisper API (`whisper-1`) |
| Chatbot | OpenAI GPT (JSON mode) **or** any custom HTTP endpoint |
| Backend | Python · FastAPI · Uvicorn |

### Conversation flow
1. User clicks the green phone button — microphone opens and a WebSocket connects.
2. Browser streams audio chunks (WebM/Opus) to the server as binary frames.
3. Silence detector (Web Audio API RMS) fires `{"type":"end_of_speech"}` after ~1.5 s of quiet.
4. Server transcribes the audio with Whisper, sends result to the chatbot.
5. Chatbot returns `{"msg": "…"}` — the server forwards the text to the browser.
6. Browser's SpeechSynthesis API reads the reply aloud.
7. Mic reopens automatically for the next turn.

---

## Quick start

### 1. Clone & set up the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### 2. Run the server

```bash
# still inside backend/
python main.py
```

The server starts at **http://localhost:8000**.

### 3. Open the app

Navigate to **http://localhost:8000** in any modern browser (Chrome / Edge recommended for best Web Speech API support).

Click the green 📞 button, allow microphone access, and start talking.

---

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | OpenAI API key used for Whisper and GPT |
| `CHATBOT_TYPE` | `openai` | `openai` or `custom` |
| `OPENAI_MODEL` | `gpt-3.5-turbo` | GPT model used for chat |
| `SYSTEM_PROMPT` | *(friendly assistant)* | System prompt injected into GPT |
| `CHATBOT_URL` | *(empty)* | HTTP endpoint when `CHATBOT_TYPE=custom` |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Bind port |

### Custom chatbot endpoint

Set `CHATBOT_TYPE=custom` and `CHATBOT_URL=https://your-bot/api/chat`.

The server will `POST`:
```json
{ "text": "<user utterance>" }
```
and expects:
```json
{ "msg": "<agent reply>" }
```

---

## Project structure

```
Voice-Agent-Integrator/
├── backend/
│   ├── main.py          # FastAPI app + WebSocket endpoint
│   ├── stt.py           # Whisper STT wrapper
│   ├── chatbot.py       # Chatbot integration (OpenAI / custom)
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── index.html       # Phone-call UI
    └── app.js           # MediaRecorder · silence detection · WebSocket · TTS
```

---

## Browser compatibility

| Feature | Chrome | Edge | Firefox | Safari |
|---|---|---|---|---|
| MediaRecorder (WebM/Opus) | ✅ | ✅ | ✅ | ⚠ partial |
| Web Speech API (synthesis) | ✅ | ✅ | ✅ | ✅ |
| WebSocket | ✅ | ✅ | ✅ | ✅ |

Chrome or Edge are recommended for the most reliable experience.
