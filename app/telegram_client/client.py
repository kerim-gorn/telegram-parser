from typing import Optional

from telethon import TelegramClient
from telethon.sessions import StringSession

from app.settings.config import settings


def build_client(session_string: Optional[str] = None) -> TelegramClient:
    session = StringSession(session_string) if session_string else StringSession()
    return TelegramClient(session, settings.telegram.api_id, settings.telegram.api_hash)
