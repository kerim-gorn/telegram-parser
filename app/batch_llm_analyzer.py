"""
Batch LLM analyzer for processing multiple messages at once using the new classification schema.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import httpx

from app.openrouter_client import DEFAULT_MODEL_NAME, OPENROUTER_API_URL, get_openrouter_client
from core.config import settings
from app.classification import SYSTEM_PROMPT_TEXT, parse_compact_batch_partial


async def analyze_messages_batch(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Analyze a batch of Telegram messages using OpenRouter API with the new classification schema.
    
    Args:
        messages: List of messages in format [{"id": str, "text": str}, ...]
                 Each message must have "id" and "text" fields.
    
    Returns:
        Dictionary with either:
        - {ok: True, data: ClassificationBatchResult, raw: api_response, usage?: token_usage}
        - {ok: False, error: error_type, message?: str, status_code?: int, body?: str}
    
    Raises:
        ValueError: If messages list is empty or exceeds maximum batch size.
    """
    if not messages:
        return {"ok": False, "error": "empty_batch", "message": "Messages list cannot be empty"}
    
    if len(messages) > settings.llm_batch_size:
        return {
            "ok": False,
            "error": "batch_too_large",
            "message": f"Batch size {len(messages)} exceeds maximum of {settings.llm_batch_size}",
        }
    
    # Validate message format
    for msg in messages:
        if not isinstance(msg, dict):
            return {"ok": False, "error": "invalid_format", "message": "Each message must be a dictionary"}
        if "id" not in msg or "text" not in msg:
            return {
                "ok": False,
                "error": "invalid_format",
                "message": "Each message must have 'id' and 'text' fields",
            }
    
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model_name = os.getenv("LLM_MODEL_NAME", DEFAULT_MODEL_NAME).strip() or DEFAULT_MODEL_NAME
    if not api_key:
        return {"ok": False, "error": "missing_api_key", "message": "OPENROUTER_API_KEY is not set"}
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "http://localhost",
        "Content-Type": "application/json",
    }
    
    max_tokens = len(messages) * 50
    order_messages: list[dict[str, str]] = []
    order_id_map: dict[str, str] = {}
    for idx, msg in enumerate(messages, start=1):
        order_id = str(idx)
        order_messages.append({"id": order_id, "text": msg.get("text", "")})
        order_id_map[order_id] = str(msg.get("id", order_id))
    user_prelude = (
        "Ответ только в формате битовых строк. "
        "Никаких пояснений. Reasoning 3-5 слов.\n"
    )
    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_TEXT},
            {"role": "user", "content": user_prelude + json.dumps(order_messages, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    
    try:
        client = await get_openrouter_client()
        response = await client.post(OPENROUTER_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        
        api_json = response.json()
        choices = api_json.get("choices") or []
        if not choices:
            return {"ok": False, "error": "empty_response", "raw": api_json}
        
        content = (choices[0].get("message") or {}).get("content") or ""
        if not isinstance(content, str) or not content.strip():
            return {"ok": False, "error": "no_content", "raw": api_json}
        
        # Parse compact response (best-effort per line)
        try:
            parsed_messages, parse_errors = parse_compact_batch_partial(content)
            data = {"classified_messages": parsed_messages}
            classified = data.get("classified_messages") or []
            unknown_ids: list[str] = []
            for item in classified:
                order_id = str(item.get("id", "")).strip()
                if order_id not in order_id_map:
                    unknown_ids.append(order_id)
                    continue
                item["id"] = order_id_map[order_id]
            if unknown_ids:
                return {
                    "ok": False,
                    "error": "parse_error",
                    "message": f"Unknown LLM ids in response: {sorted(set(unknown_ids))}",
                    "raw": api_json,
                    "text": content,
                }
            # Remap parse errors to original ids when possible
            for err in parse_errors:
                order_id = str(err.get("id", "")).strip()
                if order_id and order_id in order_id_map:
                    err["id"] = order_id_map[order_id]
        except Exception as e:
            return {
                "ok": False,
                "error": "parse_error",
                "message": f"Failed to parse compact response: {e}",
                "raw": api_json,
                "text": content,
            }
        
        usage = api_json.get("usage", {})
        return {
            "ok": True,
            "data": data,
            "raw": api_json,
            "usage": usage,
            "parse_errors": parse_errors,
        }
    
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

