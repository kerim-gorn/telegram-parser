from __future__ import annotations

import asyncio
import html
from datetime import datetime, timezone
from typing import Optional, Union

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from core.anti_ban import handle_flood_wait
from core.config import settings


def _bot_api_proxy_url() -> Optional[str]:
    """SOCKS/HTTP для aiogram → api.telegram.org. MTProto (TELEGRAM_MTPROXY_*) сюда не используется."""
    for raw in (settings.telegram_bot_proxy_url, settings.telegram_proxy_url):
        if raw is None:
            continue
        s = str(raw).strip()
        if s:
            return s
    return None


def _proxy_url_for_aiogram(proxy_url: str) -> str:
    """
    python_socks (aiohttp_socks) не знает схему socks5h — только socks5/socks4/http.
    В aiogram для SOCKS rdns в коннекторе уже true, socks5:// достаточно.
    """
    lower = proxy_url.lower()
    if lower.startswith("socks5h://"):
        return "socks5://" + proxy_url[10:]
    if lower.startswith("socks4a://"):
        return "socks4://" + proxy_url[10:]
    return proxy_url


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


def _build_link(
    chat_id: Optional[int],
    chat_username: Optional[str],
    message_id: Optional[int],
    message_thread_id: Optional[int] = None,
) -> str:
    """
    Build a deep link to the original Telegram message.
    - For public groups/channels with a username:
        - topic message: https://t.me/{username}/{thread_id}/{message_id}
        - regular message: https://t.me/{username}/{message_id}
    - For private groups/channels (no username but numeric chat_id):
        - topic message: https://t.me/c/{abs(chat_id)}/{thread_id}/{message_id}
        - regular message: https://t.me/c/{abs(chat_id)}/{message_id}
    """
    try:
        if not message_id:
            return ""

        # Prefer human-friendly links when username is available
        if isinstance(chat_username, str) and chat_username.startswith("@"):
            uname = chat_username[1:]
            if message_thread_id:
                return f'\n<a href="https://t.me/{uname}/{int(message_thread_id)}/{int(message_id)}">Открыть оригинал</a>'
            return f'\n<a href="https://t.me/{uname}/{int(message_id)}">Открыть оригинал</a>'

        # Fallback to /c/ links when only chat_id is known (e.g. private/special groups)
        if chat_id:
            internal_id = abs(int(chat_id))
            if message_thread_id:
                return f'\n<a href="https://t.me/c/{internal_id}/{int(message_thread_id)}/{int(message_id)}">Открыть оригинал</a>'
            return f'\n<a href="https://t.me/c/{internal_id}/{int(message_id)}">Открыть оригинал</a>'
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
            proxy_url = _bot_api_proxy_url()
            if proxy_url:
                session = AiohttpSession(proxy=_proxy_url_for_aiogram(proxy_url))
                self._bot = Bot(
                    token=self._token,
                    session=session,
                    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
                )
            else:
                self._bot = Bot(
                    token=self._token,
                    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
                )
            return self._bot

    @handle_flood_wait(max_retries=5)
    async def _send_html(
        self,
        chat_id: Union[int, str],
        html_text: str,
        message_thread_id: Optional[int] = None,
    ) -> None:
        bot = await self._ensure_bot()
        kwargs: dict[str, object] = {"disable_web_page_preview": True}
        if isinstance(message_thread_id, int):
            kwargs["message_thread_id"] = message_thread_id
        await bot.send_message(chat_id, html_text, **kwargs)

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
        target_chat_id: Optional[int] = None,
        source_message_thread_id: Optional[int] = None,
        target_message_thread_id: Optional[int] = None,
    ) -> None:
        """
        Send a formatted notification with original text, author, source chat and timestamp.
        All username/time fields are optional; when absent, placeholders are used.
        
        Args:
            text: Message text content.
            source_chat_id: Source Telegram chat ID.
            sender_id: Sender user ID.
            source_message_id: Original message ID for deep linking.
            source_message_thread_id: Optional topic/thread identifier for messages in topics.
            target_message_thread_id: Optional topic/thread identifier for the notification destination.
            sender_username: Sender username (optional).
            chat_username: Source chat username (optional).
            message_date: Message timestamp (optional).
            target_chat_id: Target chat ID for notification. If None, uses default from settings.
        """
        safe_text = (text or "").strip()
        if not safe_text:
            return

        author = _normalize_username(sender_username) or "неизвестно"
        channel = _normalize_username(chat_username) or "неизвестно"
        when = _format_dt_utc(message_date) or "неизвестно"
        escaped = html.escape(safe_text)
        normalized_chat_username = _normalize_username(chat_username)
        link_line = _build_link(source_chat_id, normalized_chat_username, source_message_id, source_message_thread_id)

        body = (
            f"<b>📣 Сигнал обнаружен</b>\n"
            f"<b>Канал:</b> {channel}\n"
            f"<b>Автор:</b> {author}\n"
            f"<b>Время:</b> {when}\n"
            f"<b>Текст:</b>\n"
            f"<pre>{escaped}</pre>"
            f"{link_line}"
        )
        
        # Use provided target_chat_id or fallback to default
        chat_id = target_chat_id if target_chat_id is not None else self._target_chat_id
        await self._send_html(chat_id, body, message_thread_id=target_message_thread_id)

    async def close(self) -> None:
        if self._bot is not None:
            try:
                await self._bot.session.close()
            finally:
                self._bot = None


notifier = SignalNotifier()


