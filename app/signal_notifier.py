from __future__ import annotations

import asyncio
import html
from datetime import datetime, timezone
from typing import Optional, Union

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from core.anti_ban import handle_flood_wait
from core.config import settings


def _normalize_username(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    return s if s.startswith("@") else f"@{s}"


def _format_dt_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return None


def _build_link(chat_username: Optional[str], message_id: Optional[int]) -> str:
    try:
        if isinstance(chat_username, str) and chat_username.startswith("@") and message_id:
            return f'\n<a href="https://t.me/{chat_username[1:]}/{int(message_id)}">Открыть оригинал</a>'
    except Exception:
        return ""
    return ""


class SignalNotifier:
    """
    Async notifier that posts detected signals via Telegram Bot (aiogram).
    - Lazily creates one Bot instance per process and reuses it.
    - Wraps Bot API calls with anti-ban flood wait handling.
    """

    def __init__(self) -> None:
        self._bot: Optional[Bot] = None
        self._lock = asyncio.Lock()
        # Fail fast if misconfigured
        self._token: str = settings.telegram_bot_token
        self._target_chat_id: int = settings.signals_bot_chat_id

    async def _ensure_bot(self) -> Bot:
        if self._bot is not None:
            return self._bot
        async with self._lock:
            if self._bot is not None:
                return self._bot
            self._bot = Bot(token=self._token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            return self._bot

    @handle_flood_wait(max_retries=5)
    async def _send_html(self, chat_id: Union[int, str], html_text: str) -> None:
        bot = await self._ensure_bot()
        await bot.send_message(chat_id, html_text, disable_web_page_preview=True)

    async def send_signal(
        self,
        text: str,
        source_chat_id: Optional[int],
        sender_id: Optional[int],
        source_message_id: Optional[int] = None,
        *,
        sender_username: Optional[str] = None,
        chat_username: Optional[str] = None,
        message_date: Optional[datetime] = None,
    ) -> None:
        """
        Send a formatted notification with original text, author, source chat and timestamp.
        All username/time fields are optional; when absent, placeholders are used.
        """
        safe_text = (text or "").strip()
        if not safe_text:
            return

        author = _normalize_username(sender_username) or "неизвестно"
        channel = _normalize_username(chat_username) or "неизвестно"
        when = _format_dt_utc(message_date) or "неизвестно"
        escaped = html.escape(safe_text)
        link_line = _build_link(_normalize_username(chat_username), source_message_id)

        body = (
            f"<b>📣 Сигнал обнаружен</b>\n"
            f"<b>Канал:</b> {channel}\n"
            f"<b>Автор:</b> {author}\n"
            f"<b>Время:</b> {when}\n"
            f"<b>Текст:</b>\n"
            f"<pre>{escaped}</pre>"
            f"{link_line}"
        )
        await self._send_html(self._target_chat_id, body)

    async def close(self) -> None:
        if self._bot is not None:
            try:
                await self._bot.session.close()
            finally:
                self._bot = None


notifier = SignalNotifier()


