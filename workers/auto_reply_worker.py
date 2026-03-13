from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional, Union

from telethon import TelegramClient

from core.anti_ban import handle_flood_wait
from core.config import settings
from core.session_manager import SessionManager
from core.telethon_client import create_client_from_session
from workers.celery_app import celery_app
from app.auto_reply_llm import generate_reply


@handle_flood_wait(max_retries=5)
async def _safe_send_message(
    client: TelegramClient,
    user_id: Union[int, str],
    text: str,
) -> None:
    await client.send_message(entity=user_id, message=text)


async def _async_send_auto_reply(payload: Dict[str, Any]) -> str:
    """
    Core async implementation for auto-reply job.

    Expected payload keys:
      - scenario_id: str
      - telegram_account_id: str
      - llm_model: Optional[str]
      - prompt_template: str
      - prompt_key: str
      - sender_id: int
      - sender_username: Optional[str]
      - chat_id: int
      - chat_username: Optional[str]
      - message_id: int
      - message_thread_id: Optional[int]
      - text: str
      - message_date: Optional[isoformat str]
    """
    scenario_id = str(payload.get("scenario_id") or "")
    account_id = str(payload.get("telegram_account_id") or "")
    prompt_template = str(payload.get("prompt_template") or "")
    llm_model = payload.get("llm_model")
    sender_id = payload.get("sender_id")
    text = payload.get("text") or ""

    if not scenario_id or not account_id or not prompt_template or sender_id is None or not text.strip():
        return "skipped_invalid_payload"

    # Build user-level prompt
    user_message = str(text)
    chat_username = payload.get("chat_username")
    domain = payload.get("domain")
    subcategory = payload.get("subcategory")

    chat_context_parts: list[str] = []
    if isinstance(chat_username, str) and chat_username.strip():
        chat_context_parts.append(f"чат {chat_username}")
    if domain:
        chat_context_parts.append(f"домен {domain}")
    if subcategory:
        chat_context_parts.append(f"подкатегория {subcategory}")
    chat_context = ", ".join(chat_context_parts) if chat_context_parts else ""

    # message_date can be ISO string or None
    message_date_raw = payload.get("message_date")
    message_date_str: Optional[str] = None
    if isinstance(message_date_raw, str):
        message_date_str = message_date_raw
    elif isinstance(message_date_raw, datetime):
        message_date_str = message_date_raw.isoformat()

    formatted_prompt = prompt_template.format(
        user_message=user_message,
        chat_context=chat_context,
        domain=domain or "",
        subcategory=subcategory or "",
        sender_username=str(payload.get("sender_username") or ""),
        message_date=message_date_str or "",
    )

    generated = await generate_reply(formatted_prompt, model=llm_model)
    if not generated.strip():
        return "skipped_empty_generated"

    session_manager = SessionManager(
        redis_url=settings.redis_url,
        key_prefix=settings.telegram_session_prefix,
        encryption_key=settings.session_crypto_key,
    )
    try:
        session_string = await session_manager.get_string_session(account_id)
        if not session_string:
            raise RuntimeError(f"No StringSession found in Redis for auto-reply account '{account_id}'")

        client = create_client_from_session(session_string)
        async with client:
            await _safe_send_message(client, user_id=sender_id, text=generated)
        return "ok"
    finally:
        await session_manager.close()


@celery_app.task(name="workers.auto_reply_worker.send_auto_reply", bind=True)
def send_auto_reply(self, payload: Dict[str, Any]) -> str:  # type: ignore[override]
    """
    Celery entrypoint for auto-reply DM.
    """
    return asyncio.run(_async_send_auto_reply(payload))


