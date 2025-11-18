from __future__ import annotations

import asyncio
import html
from typing import Optional, Union

from core.anti_ban import handle_flood_wait
from core.config import settings
from core.session_manager import SessionManager
from core.telethon_client import create_client_from_session


class SignalNotifier:
    """
    Minimal async notifier that posts detected signals to a configured Telegram channel.
    - Uses Redis-backed StringSession (no file sessions).
    - Lazily establishes one Telethon client per process and reuses it.
    - Wraps Telegram I/O with flood-wait handling.
    """

    def __init__(self) -> None:
        self._client = None  # type: ignore[assignment]
        self._lock = asyncio.Lock()
        self._session_manager = SessionManager(
            settings.redis_url,
            settings.telegram_session_prefix,
            settings.session_crypto_key,
        )
        self._account_id = (settings.signals_account_id or settings.telegram_account_id).strip()
        self._target = (settings.signals_channel or "").strip()

    async def _ensure_client(self):
        if self._client is not None and self._client.is_connected():
            return self._client
        async with self._lock:
            if self._client is not None and self._client.is_connected():
                return self._client
            session_string = await self._session_manager.get_string_session(self._account_id)
            if not session_string:
                raise RuntimeError(
                    f"No StringSession found for notifier account '{self._account_id}'. "
                    "Ensure onboarding for this account is completed."
                )
            client = create_client_from_session(session_string)
            await client.connect()
            self._client = client
            return client

    @handle_flood_wait(max_retries=5)
    async def _resolve_username(
        self, client, entity_id: Optional[int]
    ) -> Optional[str]:
        if entity_id is None:
            return None
        try:
            ent = await client.get_entity(entity_id)
            username = getattr(ent, "username", None)
            if isinstance(username, str) and username:
                return f"@{username}"
            # Fallback to human-readable name
            first = getattr(ent, "first_name", None)
            last = getattr(ent, "last_name", None)
            parts = [p for p in (first, last) if isinstance(p, str) and p]
            display = " ".join(parts)
            return display or None
        except Exception:
            return None

    @handle_flood_wait(max_retries=5)
    async def _resolve_chatname(
        self, client, chat: Union[int, str, None]
    ) -> Optional[str]:
        if chat is None:
            return None
        try:
            ent = await client.get_entity(chat)
            username = getattr(ent, "username", None)
            if isinstance(username, str) and username:
                return f"@{username}"
            title = getattr(ent, "title", None)
            if isinstance(title, str) and title:
                return title
        except Exception:
            return None
        return None

    @handle_flood_wait(max_retries=5)
    async def _send_html(self, client, target: Union[str, int], html_text: str) -> None:
        await client.send_message(target, html_text, parse_mode="html")

    async def send_signal(
        self,
        text: str,
        source_chat_id: Optional[int],
        sender_id: Optional[int],
        source_message_id: Optional[int] = None,
    ) -> None:
        """
        Send a formatted notification with the original text, author and source chat.
        """
        if not self._target:
            return
        safe_text = (text or "").strip()
        if not safe_text:
            return

        client = await self._ensure_client()
        author = await self._resolve_username(client, sender_id)
        chat_name = await self._resolve_chatname(client, source_chat_id)
        escaped = html.escape(safe_text)
        author_part = author or "неизвестно"
        chat_part = chat_name or "неизвестно"

        link_line = ""
        try:
            if chat_name and chat_name.startswith("@") and source_message_id:
                link = f"https://t.me/{chat_name[1:]}/{int(source_message_id)}"
                link_line = f'\n<a href="{link}">Открыть оригинал</a>'
        except Exception:
            link_line = ""

        body = (
            f"<b>📣 Сигнал обнаружен</b>\n"
            f"<b>Текст:</b>\n"
            f"<pre>{escaped}</pre>\n"
            f"<b>Автор:</b> {author_part}\n"
            f"<b>Источник:</b> {chat_part}"
            f"{link_line}"
        )
        await self._send_html(client, self._target, body)

    async def close(self) -> None:
        if self._client is not None and self._client.is_connected():
            await self._client.disconnect()
        await self._session_manager.close()


notifier = SignalNotifier()


