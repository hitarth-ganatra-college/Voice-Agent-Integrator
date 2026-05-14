"""stt.py – Speech-to-Text using the OpenAI Whisper API."""

import io
import os

from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. "
                "Copy backend/.env.example to backend/.env and fill in your key."
            )
        _client = AsyncOpenAI(api_key=api_key)
    return _client


async def transcribe_audio(audio_data: bytes, mime_hint: str = "audio/webm") -> str:
    """Transcribe raw audio bytes and return the recognised text.

    Parameters
    ----------
    audio_data:
        Raw audio bytes received from the browser (WebM/Opus by default).
    mime_hint:
        MIME type used as a format hint for the OpenAI SDK (sets the
        ``name`` attribute on the in-memory file so Whisper can identify
        the codec).  No temporary files are created.  Defaults to
        ``audio/webm``.
    """
    ext_map = {
        "audio/webm": "audio.webm",
        "audio/ogg":  "audio.ogg",
        "audio/wav":  "audio.wav",
        "audio/mp4":  "audio.mp4",
        "audio/mpeg": "audio.mp3",
    }
    filename = ext_map.get(mime_hint, "audio.webm")

    # Wrap the raw bytes in an in-memory file-like object so no data ever
    # touches disk, eliminating temporary-file accumulation and privacy risks.
    audio_file = io.BytesIO(audio_data)
    audio_file.name = filename  # OpenAI SDK uses .name to detect the format

    client = _get_client()
    transcript = await client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
    )
    return transcript.text.strip()
