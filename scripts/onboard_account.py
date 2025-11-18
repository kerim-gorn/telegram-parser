import asyncio
import os
from getpass import getpass
from typing import Tuple, Optional

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from redis.asyncio import Redis
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession


def _read_api_credentials() -> Tuple[int, str]:
    """
    Load TELEGRAM_API_ID and TELEGRAM_API_HASH from environment or prompt the user.
    """
    load_dotenv()
    api_id_str = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")

    if not api_id_str:
        while True:
            api_id_str = input("Введите TELEGRAM_API_ID: ").strip()
            if api_id_str.isdigit():
                break
            print("Некорректный TELEGRAM_API_ID. Введите число.")
    if not api_hash:
        api_hash = input("Введите TELEGRAM_API_HASH: ").strip()

    return int(api_id_str), str(api_hash)


def _read_crypto_and_storage() -> tuple[Fernet, str, str, bool]:
    """
    Load Fernet key and Redis settings from environment.
    SESSION_CRYPTO_KEY must exist in .env; otherwise we abort.
    """
    load_dotenv()
    key = os.getenv("SESSION_CRYPTO_KEY")
    if not key:
        raise RuntimeError("SESSION_CRYPTO_KEY не найден в .env. Сгенерируйте ключ Fernet и добавьте его.")
    fernet = Fernet(key.encode("utf-8"))

    # Track whether REDIS_URL was explicitly set to avoid silent fallback confusion
    env_has_redis_url = "REDIS_URL" in os.environ and bool(os.environ.get("REDIS_URL"))
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    prefix = os.getenv("TELEGRAM_SESSION_PREFIX", "telegram:sessions:")
    return fernet, redis_url, prefix, env_has_redis_url


def _read_phone_and_2fa() -> tuple[str, Optional[str]]:
    """
    Read phone and optional 2FA password from env; prompt if missing.
    """
    load_dotenv()
    phone = os.getenv("TELEGRAM_PHONE")
    twofa = os.getenv("TELEGRAM_2FA_PASSWORD")
    if not phone:
        phone = input("Введите номер телефона (в международном формате): ").strip()
    return phone, twofa


async def _login_and_get_session(
    api_id: int, api_hash: str, phone: str, twofa_password: Optional[str]
) -> tuple[str, str]:
    """
    Interactive login flow using Telethon and StringSession.
    Returns (phone_number, session_string).
    """
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        await client.send_code_request(phone)
        code = input("Введите код подтверждения: ").strip()
        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            password = twofa_password or getpass("Введите 2FA-пароль: ")
            await client.sign_in(password=password)

        session_string: str = client.session.save()  # type: ignore[attr-defined]
        return phone, session_string
    finally:
        await client.disconnect()

async def _maybe_close_redis(redis: Redis) -> None:
    close = getattr(redis, "aclose", None) or getattr(redis, "close", None)
    if callable(close):
        result = close()
        if asyncio.iscoroutine(result):
            await result

async def _open_redis_with_fallback(
    url: str,
    allow_fallback: bool = True,
    fallback_url: str = "redis://localhost:6379/0",
) -> tuple[Redis, str]:
    """
    Try connecting to Redis at given URL; on failure fallback to localhost.
    """
    client = Redis.from_url(url, decode_responses=True)
    try:
        await client.ping()
        return client, url
    except Exception:
        if not allow_fallback:
            await _maybe_close_redis(client)
            raise RuntimeError(
                f"Не удалось подключиться к Redis по REDIS_URL={url}. "
                f"Запустите Redis или скорректируйте REDIS_URL."
            )
        await _maybe_close_redis(client)
        client2 = Redis.from_url(fallback_url, decode_responses=True)
        await client2.ping()
        return client2, fallback_url


async def main() -> None:
    """
    Онбординг аккаунта:
      1) Читает API_ID/API_HASH из .env или спрашивает у пользователя
      2) Интерактивный логин (номер телефона, код, 2FA)
      3) Получает session_string, шифрует с помощью Fernet
      4) Сохраняет в Redis по ключу {PREFIX}{phone}
    """
    api_id, api_hash = _read_api_credentials()
    fernet, redis_url, prefix, env_has_redis_url = _read_crypto_and_storage()

    phone_input, twofa_input = _read_phone_and_2fa()
    phone, session_string = await _login_and_get_session(api_id, api_hash, phone_input, twofa_input)
    encrypted_session = fernet.encrypt(session_string.encode("utf-8")).decode("utf-8")

    redis, used_url = await _open_redis_with_fallback(redis_url, allow_fallback=not env_has_redis_url)
    try:
        key = f"{prefix}{phone}"
        await redis.set(key, encrypted_session)
    finally:
        await _maybe_close_redis(redis)

    print(f"Успех! Сессия сохранена в Redis. URL={used_url}, KEY={key}")


if __name__ == "__main__":
    asyncio.run(main())


