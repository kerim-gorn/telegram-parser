"""
Прокси для Telethon: TELEGRAM_PROXY (SOCKS/HTTP) или TELEGRAM_MTPROXY_* (MTProto).
Секрет tg:// с префиксом ee… (Fake TLS) в Telethon как MTProto не использовать — только classic
32 hex на стороне прокси или SOCKS. См. https://core.telegram.org/proxy
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from telethon import TelegramClient, connection
from telethon.sessions import StringSession

_BOTH_PROXY_MSG = "Задайте только одно: TELEGRAM_PROXY или TELEGRAM_MTPROXY_*, не оба сразу"

_MTPROXY_EMPTY_SECRET = "00000000000000000000000000000000"

_MTPROXY_CONNECTIONS: dict[str, type] = {
    "randomized": connection.ConnectionTcpMTProxyRandomizedIntermediate,
    "intermediate": connection.ConnectionTcpMTProxyIntermediate,
    "abridged": connection.ConnectionTcpMTProxyAbridged,
}


def proxy_dict_from_url(url: str | None) -> dict | None:
    """SOCKS5/HTTP для Telethon (как «SOCKS5» в настройках приложения)."""
    if url is None:
        return None
    raw = str(url).strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme == "socks5h":
        proxy_type = "socks5"
        default_port = 1080
        rdns = True
    elif scheme == "socks5":
        proxy_type = "socks5"
        default_port = 1080
        rdns = False
    elif scheme == "socks4":
        proxy_type = "socks4"
        default_port = 1080
        rdns = True
    elif scheme in ("http", "https"):
        proxy_type = "http"
        default_port = 8080
        rdns = True
    else:
        raise ValueError(
            "TELEGRAM_PROXY: ожидается socks5://, socks5h:// или http:// "
            f"(схема {scheme!r})"
        )
    host = parsed.hostname
    if not host:
        raise ValueError("TELEGRAM_PROXY: нужен host")
    port = parsed.port if parsed.port is not None else default_port
    cfg: dict = {
        "proxy_type": proxy_type,
        "addr": host,
        "port": port,
        "rdns": rdns,
    }
    if parsed.username:
        cfg["username"] = unquote(parsed.username)
    if parsed.password:
        cfg["password"] = unquote(parsed.password)
    return cfg


def _mtproxy_connection_class(mode: str | None) -> type:
    key = (mode or "randomized").strip().lower()
    cls = _MTPROXY_CONNECTIONS.get(key)
    if cls is None:
        allowed = ", ".join(sorted(_MTPROXY_CONNECTIONS))
        raise ValueError(
            f"TELEGRAM_MTPROXY_MODE: одно из {allowed} (получено {key!r})"
        )
    return cls


def resolve_mtproxy(
    host: str | None,
    port: int | None,
    secret: str | None,
    mode: str | None = None,
) -> tuple[tuple[str, int, str], type] | None:
    """MTProto-прокси Telethon; host задан, port обязателен."""
    h = (host or "").strip()
    if not h:
        return None
    if port is None:
        raise ValueError(
            "Задан TELEGRAM_MTPROXY_HOST, но не задан TELEGRAM_MTPROXY_PORT"
        )
    cleaned = (secret or "").strip() or None
    sec = cleaned if cleaned else _MTPROXY_EMPTY_SECRET
    conn_cls = _mtproxy_connection_class(mode)
    return ((h, int(port), sec), conn_cls)


def _telegram_connect_kwargs(
    proxy_url: str | None,
    mt_host: str | None,
    mt_port: int | None,
    mt_secret: str | None,
    mt_mode: str | None,
) -> dict:
    proxy_d = proxy_dict_from_url(proxy_url)
    mt = resolve_mtproxy(mt_host, mt_port, mt_secret, mt_mode)
    if proxy_d and mt:
        raise ValueError(_BOTH_PROXY_MSG)
    if proxy_d:
        return {"proxy": proxy_d}
    if mt:
        t, cls = mt
        return {"connection": cls, "proxy": t}
    return {}


def create_client_from_session(session_string: str | None) -> TelegramClient:
    """StringSession + TELEGRAM_PROXY или TELEGRAM_MTPROXY_* (взаимоисключение)."""
    from core.config import settings

    session = StringSession(session_string) if session_string else StringSession()
    kw = _telegram_connect_kwargs(
        settings.telegram_proxy_url,
        settings.telegram_mtproxy_host,
        settings.telegram_mtproxy_port,
        settings.telegram_mtproxy_secret,
        settings.telegram_mtproxy_mode,
    )
    return TelegramClient(
        session,
        settings.telegram_api_id,
        settings.telegram_api_hash,
        **kw,
    )


def telegram_client_kwargs_from_env() -> dict:
    """kwargs для TelegramClient из os.environ (onboard и др. скрипты без полного Settings)."""
    import os

    from dotenv import load_dotenv

    load_dotenv()
    port_raw = (os.getenv("TELEGRAM_MTPROXY_PORT") or "").strip()
    port = int(port_raw) if port_raw else None
    return _telegram_connect_kwargs(
        os.getenv("TELEGRAM_PROXY"),
        os.getenv("TELEGRAM_MTPROXY_HOST"),
        port,
        os.getenv("TELEGRAM_MTPROXY_SECRET"),
        os.getenv("TELEGRAM_MTPROXY_MODE"),
    )
