from __future__ import annotations

from typing import Any, Dict, Optional
import os

import httpx

from app.openrouter_client import (
    DEFAULT_MODEL_NAME,
    OPENROUTER_API_URL,
    get_openrouter_client,
)


async def generate_reply(prompt: str, model: Optional[str] = None) -> str:
    """
    Generate a single reply text for auto-reply DM using OpenRouter.

    Args:
        prompt: Fully assembled prompt text (includes user message and any context).
        model: Optional override of model name; falls back to LLM_MODEL_NAME or DEFAULT_MODEL_NAME.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set for auto-reply LLM generation")

    model_name = (model or os.getenv("LLM_MODEL_NAME", "") or DEFAULT_MODEL_NAME).strip() or DEFAULT_MODEL_NAME

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "http://localhost",
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты помогаешь формировать короткие, вежливые ответы в личные сообщения в Telegram. "
                    "Отвечай естественно, как живой человек, без упоминаний о том, что ты ИИ."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.5,
        "max_tokens": 256,
    }

    try:
        client = await get_openrouter_client()
        response: httpx.Response = await client.post(OPENROUTER_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter returned no choices for auto-reply")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenRouter returned empty content for auto-reply")
        return content.strip()
    except httpx.TimeoutException as e:
        raise RuntimeError(f"OpenRouter timeout during auto-reply generation: {e}") from e
    except httpx.HTTPError as e:
        raise RuntimeError(f"OpenRouter HTTP error during auto-reply generation: {e}") from e
    except Exception:
        raise

