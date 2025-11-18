from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, Optional

import httpx


OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL_NAME = "qwen/qwen3-max"


def _build_system_prompt() -> str:
    """
    Build a strict system prompt instructing the LLM to return JSON only.
    """
    return (
        "Ты – ИИ-фильтр сообщений в чатах жильцов ЖК и коттеджных посёлков.\n\n"
        "Каждый раз ты получаешь ОДНО сообщение из чата.\n"
        "Твоя задача – определить, является ли это сообщение потенциальным ЛИДОМ на ремонт/строительство.\n\n"
        "ЛИД – это когда автор пишет, что:\n"
        "- ему НУЖЕН ремонт или строительные работы,\n"
        "- или он ИЩЕТ/ПРОСИТ ПОСОВЕТОВАТЬ мастера/бригады/компанию\n"
        "по ремонту квартир, коммерческих помещений или малоэтажному строительству\n"
        "(дом, коттедж, баня, гараж, пристройка и т.п., а также электрика, сантехника, отделка, кровля и т.д.).\n\n"
        "Если в сообщении нет запроса на ремонт/строительство или поиска мастеров – это не лид.\n\n"
        "Отвечай СТРОГО в формате JSON:\n\n"
        "{\"is_signal\": <boolean>, \"confidence\": <значение от 0.0 до 1.0>, \"summary\": \"<краткая суть запроса>\"}"
    )


def _extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """
    Best-effort extraction of the first top-level JSON object from a text blob.
    Useful if the model adds stray characters around the JSON despite instructions.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


async def analyze_message_for_signal(text: str) -> Dict[str, Any]:
    """
    Analyze Telegram message text for a renovation/contractor advice request using OpenRouter chat completions API.

    - Loads OPENROUTER_API_KEY and LLM_MODEL_NAME from environment.
    - Sends POST to OpenRouter with strict system prompt asking for JSON-only response.
    - Handles timeouts and HTTP/API errors gracefully.
    - Returns a dictionary with either {ok: True, data: <parsed_json>, raw: <api_response>} or
      {ok: False, error: <type>, message?: str, status_code?: int, body?: str}.
    """
    if not isinstance(text, str) or not text.strip():
        return {"ok": False, "error": "invalid_input", "message": "text must be a non-empty string"}

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model_name = os.getenv("LLM_MODEL_NAME", DEFAULT_MODEL_NAME).strip() or DEFAULT_MODEL_NAME
    if not api_key:
        return {"ok": False, "error": "missing_api_key", "message": "OPENROUTER_API_KEY is not set"}

    system_prompt = _build_system_prompt()

    headers = {
        "Authorization": f"Bearer {api_key}",
        # OpenRouter requires an HTTP Referer identifying your site or app
        "HTTP-Referer": "http://localhost",
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Проанализируй следующее сообщение и ответь строго одним JSON по указанной схеме:\n{text.strip()}",
            },
        ],
        # Encourage deterministic, schema-abiding outputs
        "temperature": 0.2,
        # Ask for JSON mode when supported; servers/models that don't support it will ignore
        "response_format": {"type": "json_object"},
        # Reasonable cap for concise classification
        "max_tokens": 400,
    }

    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = await client.post(OPENROUTER_API_URL, json=payload)
            # Raise for non-2xx so we can include status/body in the error path
            response.raise_for_status()

            api_json = response.json()
            # OpenRouter (OpenAI-compatible) response shape:
            # { choices: [ { message: { role: "assistant", content: "<JSON>" } } ] , ... }
            choices = api_json.get("choices") or []
            if not choices:
                return {"ok": False, "error": "empty_response", "raw": api_json}

            content = (choices[0].get("message") or {}).get("content") or ""
            if not isinstance(content, str) or not content.strip():
                return {"ok": False, "error": "no_content", "raw": api_json}

            # Primary parse attempt
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                # Fallback: attempt to extract the first JSON object from the content
                parsed = _extract_first_json_object(content)

            if not isinstance(parsed, dict):
                return {
                    "ok": False,
                    "error": "parse_error",
                    "message": "LLM did not return valid JSON",
                    "raw": api_json,
                    "text": content,
                }

            return {"ok": True, "data": parsed, "raw": api_json}

    except httpx.TimeoutException:
        return {"ok": False, "error": "timeout", "message": "OpenRouter request timed out"}
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else None
        body = None
        try:
            body = e.response.text if e.response is not None else None
        except Exception:
            body = None
        return {
            "ok": False,
            "error": "http_error",
            "status_code": status,
            "body": body,
        }
    except httpx.RequestError as e:
        return {"ok": False, "error": "request_error", "message": str(e)}
    except Exception as e:
        return {"ok": False, "error": "unexpected_error", "message": str(e)}


# Convenience for quick local manual testing:
#   import asyncio; asyncio.run(analyze_message_for_signal("Buy BTC at 40k, SL 38k, TP 45k"))
if __name__ == "__main__":
    async def _demo() -> None:
        sample = "Thinking to buy AAPL after earnings surprise; strong momentum."
        result = await analyze_message_for_signal(sample)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(_demo())


