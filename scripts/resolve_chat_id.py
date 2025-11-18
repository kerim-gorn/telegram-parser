import asyncio
import os
import re
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv

# Ensure project root on sys.path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import settings  # noqa: E402
from core.session_manager import SessionManager  # noqa: E402
from core.telethon_client import create_client_from_session  # noqa: E402
from core.anti_ban import handle_flood_wait  # noqa: E402

from telethon import functions  # noqa: E402
from telethon.errors import UsernameNotOccupiedError, RPCError  # noqa: E402
from telethon.tl.types import Chat, Channel  # noqa: E402
from telethon.utils import get_peer_id  # noqa: E402


_RE_TME_C = re.compile(r"^https?://t\.me/c/(\d+)(?:/.*)?$", re.IGNORECASE)
_RE_TME_USERNAME = re.compile(r"^https?://t\.me/([A-Za-z0-9_]{5,})(?:/.*)?$", re.IGNORECASE)
_RE_TG_RESOLVE = re.compile(r"^tg://resolve\?domain=([A-Za-z0-9_]{5,})", re.IGNORECASE)
_RE_TME_JOINCHAT = re.compile(r"^https?://t\.me/(?:joinchat/|\+)([A-Za-z0-9_\-]+)$", re.IGNORECASE)
_RE_TG_JOIN = re.compile(r"^tg://join\?invite=([A-Za-z0-9_\-]+)$", re.IGNORECASE)


def _parse_numeric_chat_id(identifier: str) -> Optional[int]:
    s = identifier.strip()
    if s.startswith("@"):
        return None
    # -100... channel/group id
    if s.startswith("-100") and s[4:].isdigit():
        try:
            return int(s)
        except ValueError:
            return None
    # pure integer (may be user or basic chat); still return as-is
    if s.lstrip("-").isdigit():
        try:
            return int(s)
        except ValueError:
            return None
    # t.me/c/<internal_id>/... → chat_id = -100<internal_id>
    m = _RE_TME_C.match(s)
    if m:
        return int(f"-100{m.group(1)}")
    return None


def _extract_username(identifier: str) -> Optional[str]:
    s = identifier.strip()
    if s.startswith("@"):
        return s[1:]
    m = _RE_TME_USERNAME.match(s)
    if m:
        return m.group(1)
    m = _RE_TG_RESOLVE.match(s)
    if m:
        return m.group(1)
    return None


def _extract_invite_hash(identifier: str) -> Optional[str]:
    s = identifier.strip()
    m = _RE_TME_JOINCHAT.match(s)
    if m:
        return m.group(1)
    m = _RE_TG_JOIN.match(s)
    if m:
        return m.group(1)
    return None


@handle_flood_wait(max_retries=5)
async def _safe_get_entity(client, arg):
    return await client.get_entity(arg)


@handle_flood_wait(max_retries=5)
async def _safe_check_invite(client, invite_hash: str):
    return await client(functions.messages.CheckChatInviteRequest(invite_hash))


@handle_flood_wait(max_retries=5)
async def _safe_import_invite(client, invite_hash: str):
    return await client(functions.messages.ImportChatInviteRequest(invite_hash))


async def resolve_chat_id(
    account_phone: str,
    identifier: str,
    accept_invite: bool = False,
) -> Tuple[int, Optional[str]]:
    """
    Resolve a wide range of identifiers to a chat_id:
      - @username
      - https://t.me/<username>[/...]
      - tg://resolve?domain=<username>
      - https://t.me/c/<internal_id>[/...]
      - numeric ids (e.g. -100123..., 12345)
      - invite links: https://t.me/+hash, https://t.me/joinchat/hash, tg://join?invite=hash
        (for private invites, id may be unavailable unless --accept-invite is used)
    Returns (chat_id, title_or_none)
    """
    # Fast-path: parse numeric patterns (including t.me/c mapping)
    numeric = _parse_numeric_chat_id(identifier)
    if numeric is not None:
        return numeric, None

    # Load session
    session_manager = SessionManager(
        redis_url=settings.redis_url,
        key_prefix=settings.telegram_session_prefix,
        encryption_key=settings.session_crypto_key,
    )
    try:
        string_session = await session_manager.get_string_session(account_phone)
        if not string_session:
            raise RuntimeError(f"No session found for account '{account_phone}'")
        client = create_client_from_session(string_session)
        async with client:
            # 1) Try username and general resolution via Telethon
            username = _extract_username(identifier)
            try_args = []
            if username:
                try_args.append(username)
            try_args.append(identifier)

            last_err: Optional[Exception] = None
            for arg in try_args:
                try:
                    entity = await _safe_get_entity(client, arg)
                    peer_id = get_peer_id(entity)
                    title = None
                    if isinstance(entity, (Channel, Chat)):
                        title = getattr(entity, "title", None)
                    return peer_id, title
                except UsernameNotOccupiedError as e:
                    last_err = e
                except ValueError as e:
                    last_err = e
                except RPCError as e:
                    last_err = e

            # 2) Try invite links
            invite_hash = _extract_invite_hash(identifier)
            if invite_hash:
                try:
                    info = await _safe_check_invite(client, invite_hash)
                except RPCError as e:
                    raise RuntimeError(f"Invite check failed: {e}") from e

                # If already a participant, info contains the chat
                chat_obj = getattr(info, "chat", None)
                if chat_obj is not None:
                    peer_id = get_peer_id(chat_obj)
                    title = getattr(chat_obj, "title", None)
                    return peer_id, title

                if not accept_invite:
                    raise RuntimeError(
                        "Invite link points to a private chat. "
                        "ID недоступен без вступления. Повторите с --accept-invite."
                    )

                # Join the chat to obtain its id
                updates = await _safe_import_invite(client, invite_hash)
                chats = getattr(updates, "chats", None) or []
                if chats:
                    chat_entity = chats[0]
                    peer_id = get_peer_id(chat_entity)
                    title = getattr(chat_entity, "title", None)
                    return peer_id, title

                # Fallback: attempt to get entity again
                entity = await _safe_get_entity(client, identifier)
                peer_id = get_peer_id(entity)
                title = getattr(entity, "title", None)
                return peer_id, title

            if last_err is not None:
                raise RuntimeError(f"Unable to resolve identifier: {last_err}") from last_err
            raise RuntimeError("Unable to resolve identifier (unknown format).")
    finally:
        await session_manager.close()


def _build_arg_parser() -> ArgumentParser:
    p = ArgumentParser(description="Resolve Telegram identifiers to chat_id using Telethon StringSession.")
    p.add_argument("identifier", help="Identifier: @username | t.me/... | tg://... | invite link | numeric id")
    p.add_argument("--phone", default=os.getenv("TELEGRAM_PHONE"), help="Account phone used as session key in Redis")
    p.add_argument("--accept-invite", action="store_true", help="Accept private invite to resolve id")
    return p


async def _amain() -> int:
    load_dotenv()
    parser = _build_arg_parser()
    args = parser.parse_args()

    if not args.phone:
        print("Ошибка: TELEGRAM_PHONE не задан и не передан через --phone")
        return 2

    try:
        chat_id, title = await resolve_chat_id(
            account_phone=args.phone,
            identifier=args.identifier,
            accept_invite=bool(args.accept_invite),
        )
        if title:
            print(f"title: {title}")
        print(f"chat_id: {chat_id}")
        # Also print raw id for easy scripting
        print(chat_id)
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"Ошибка: {e}")
        return 1


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()


