from telethon import TelegramClient
from telethon.sessions import StringSession

from core.config import settings


def create_client_from_session(session_string: str | None) -> TelegramClient:
    """
    Create a Telethon client using StringSession only (no file sessions).
    The caller is responsible for connecting/starting the client.
    """
    session = StringSession(session_string) if session_string else StringSession()
    client = TelegramClient(session, settings.telegram_api_id, settings.telegram_api_hash)
    return client


