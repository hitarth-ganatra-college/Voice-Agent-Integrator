"""stt.py – Speech-to-Text using the OpenAI Whisper API."""

import os
import tempfile

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
        MIME type used to choose the temp-file extension so Whisper can
        identify the codec.  Defaults to ``audio/webm``.
    """
    ext_map = {
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/mp4": ".mp4",
        "audio/mpeg": ".mp3",
    }
    suffix = ext_map.get(mime_hint, ".webm")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_data)
        tmp_path = tmp.name

    try:
        client = _get_client()
        with open(tmp_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
        return transcript.text.strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
