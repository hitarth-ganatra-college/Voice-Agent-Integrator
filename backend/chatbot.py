"""chatbot.py – Configurable chatbot integration.

Supported backends
------------------
* ``openai``  (default) – OpenAI chat-completions in JSON mode.
  The model is instructed to return  ``{"msg": "<reply>"}``
* ``custom``  – any HTTP endpoint that accepts
  ``POST {"text": "<utterance>"}``  and returns  ``{"msg": "<reply>"}``.
"""

import json
import os

import httpx
from openai import AsyncOpenAI

_chatbot_type: str = os.getenv("CHATBOT_TYPE", "openai").lower()
_chatbot_url: str = os.getenv("CHATBOT_URL", "")
_openai_model: str = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
_system_prompt: str = os.getenv(
    "SYSTEM_PROMPT",
    "You are a helpful, friendly voice assistant. Keep replies short and conversational.",
)
_openai_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. "
                "Copy backend/.env.example to backend/.env and fill in your key."
            )
        _openai_client = AsyncOpenAI(api_key=api_key)
    return _openai_client


async def get_response(user_text: str) -> str:
    """Return the agent's reply for the given user utterance."""
    if _chatbot_type == "custom" and _chatbot_url:
        return await _custom_backend(user_text)
    return await _openai_backend(user_text)


async def _openai_backend(user_text: str) -> str:
    client = _get_openai_client()
    full_system = (
        _system_prompt
        + "\n\nIMPORTANT: always respond with a JSON object in exactly this shape: "
        '{"msg": "<your reply here>"}'
    )
    completion = await client.chat.completions.create(
        model=_openai_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": full_system},
            {"role": "user", "content": user_text},
        ],
    )
    raw = completion.choices[0].message.content or "{}"
    data = json.loads(raw)
    return str(data.get("msg", "")).strip()


async def _custom_backend(user_text: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(_chatbot_url, json={"text": user_text})
        response.raise_for_status()
        data = response.json()
        return str(data.get("msg", "")).strip()
