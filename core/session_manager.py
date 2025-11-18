from typing import Optional
import asyncio

from redis.asyncio import Redis
from cryptography.fernet import Fernet, InvalidToken


class SessionManager:
    """
    Stores Telethon StringSession in Redis.
    If an encryption key is provided, values are transparently encrypted/decrypted via Fernet.
    Workers remain stateless; no *.session files are ever written to disk.
    """

    def __init__(
        self,
        redis_url: str,
        key_prefix: str = "telegram:sessions:",
        encryption_key: Optional[str] = None,
    ) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._key_prefix = key_prefix
        self._fernet: Optional[Fernet] = Fernet(encryption_key) if encryption_key else None

    def _key(self, account_id: str) -> str:
        return f"{self._key_prefix}{account_id}"

    async def get_string_session(self, account_id: str) -> Optional[str]:
        raw: Optional[str] = await self._redis.get(self._key(account_id))
        if raw is None:
            return None
        if self._fernet is None:
            return raw
        # Attempt decryption; if not encrypted, fall back to raw
        try:
            decrypted_bytes = self._fernet.decrypt(raw.encode("utf-8"))
            return decrypted_bytes.decode("utf-8")
        except (InvalidToken, ValueError):
            return raw

    async def set_string_session(self, account_id: str, session: str) -> None:
        to_store = (
            self._fernet.encrypt(session.encode("utf-8")).decode("utf-8")
            if self._fernet
            else session
        )
        await self._redis.set(self._key(account_id), to_store)

    async def close(self) -> None:
        # Compatibility across redis-py versions (close may be sync/async; aclose may not exist)
        close = getattr(self._redis, "aclose", None) or getattr(self._redis, "close", None)
        if callable(close):
            result = close()
            if asyncio.iscoroutine(result):
                await result


