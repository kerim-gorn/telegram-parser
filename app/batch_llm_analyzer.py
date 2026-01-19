"""
Batch LLM analyzer for processing multiple messages at once using the new classification schema.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import httpx

from app.openrouter_client import DEFAULT_MODEL_NAME, OPENROUTER_API_URL, get_openrouter_client
from app.classification import (
    CompactClassificationBatchResult,
    SYSTEM_PROMPT_TEXT,
    decode_compact_batch,
    get_json_schema,
)


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
    
    if len(messages) > 50:
        return {
            "ok": False,
            "error": "batch_too_large",
            "message": f"Batch size {len(messages)} exceeds maximum of 50",
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
    
    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_TEXT},
            {"role": "user", "content": json.dumps(messages, ensure_ascii=False)},
        ],
        "response_format": get_json_schema(),
        "temperature": 0.1,
        "max_tokens": 64000,
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
        
        # Parse JSON response
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            return {
                "ok": False,
                "error": "parse_error",
                "message": f"Failed to parse JSON response: {e}",
                "raw": api_json,
                "text": content,
            }
        
        # Validate against compact Pydantic schema
        try:
            compact = CompactClassificationBatchResult.model_validate(parsed)
        except Exception as e:
            return {
                "ok": False,
                "error": "validation_error",
                "message": f"Response does not match schema: {e}",
                "raw": api_json,
                "parsed": parsed,
            }
        
        # Decode compact result into full schema
        try:
            result = decode_compact_batch(compact)
        except Exception as e:
            return {
                "ok": False,
                "error": "decode_error",
                "message": f"Failed to decode compact response: {e}",
                "raw": api_json,
                "parsed": parsed,
            }
        
        usage = api_json.get("usage", {})
        return {
            "ok": True,
            "data": result.model_dump(),
            "raw": api_json,
            "usage": usage,
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

