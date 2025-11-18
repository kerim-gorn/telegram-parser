import asyncio
import os
import random
from typing import Any, Union

from telethon.errors.rpcerrorlist import (
    ChannelsTooMuchError,
    ChannelPrivateError,
    UserBannedInChannelError,
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    UserAlreadyParticipantError,
)

from core.config import settings
from core.session_manager import SessionManager
from core.telethon_client import create_client_from_session
from core.anti_ban import handle_flood_wait
from telethon.utils import get_peer_id
from telethon.tl.functions.channels import JoinChannelRequest


def _parse_chats(raw: str) -> list[Union[int, str]]:
    """
    Parse comma-separated chats into list of ints or usernames.
    Examples:
      CHATS_TO_LISTEN="-1001234567890,durov,  -10098765 "
    """
    if not raw:
        return []
    chats: list[Union[int, str]] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            chats.append(int(token))
        except ValueError:
            # strip leading '@' if present
            chats.append(token.lstrip("@"))
    return chats


@handle_flood_wait(max_retries=5, initial_jitter_min=7.0, initial_jitter_max=18.0)
async def _try_join(client: Any, target: Union[int, str]) -> str:
    """
    Attempt to join a single chat with robust flood-wait handling.
    Returns a status string: 'joined' | 'skipped' | 'failed' | 'private' | 'banned' | 'limit' | 'invalid_invite'
    """
    entity = await client.get_entity(target)
    try:
        await client(JoinChannelRequest(entity))
        return "joined"
    except UserAlreadyParticipantError:
        return "skipped"
    except ChannelPrivateError:
        return "private"
    except UserBannedInChannelError:
        return "banned"
    except ChannelsTooMuchError:
        return "limit"
    except (InviteHashExpiredError, InviteHashInvalidError):
        return "invalid_invite"


async def main() -> None:
    account_id = settings.telegram_account_id
    targets = _parse_chats(settings.realtime_chats_raw)
    if not targets:
        print("No CHATS_TO_LISTEN configured. Nothing to join.")
        return

    session_manager = SessionManager(
        settings.redis_url,
        settings.telegram_session_prefix,
        settings.session_crypto_key,
    )
    string_session = await session_manager.get_string_session(account_id)
    if not string_session:
        raise RuntimeError(
            f"No StringSession found in Redis for account '{account_id}'. "
            "Run scripts/onboard_account.py to bootstrap."
        )

    client = create_client_from_session(string_session)
    joined = 0
    skipped = 0
    failed = 0

    async with client:
        # Determine which targets are already in dialogs to avoid redundant joins
        existing_ids: set[int] = set()
        async for d in client.iter_dialogs():
            try:
                existing_ids.add(get_peer_id(d.entity))
            except Exception:
                pass

        # Resolve targets to numeric ids where possible to deduplicate
        resolved_targets: list[Union[int, str]] = []
        for t in targets:
            try:
                ent = await client.get_input_entity(t)
                resolved_targets.append(get_peer_id(ent))
            except Exception:
                resolved_targets.append(t)

        # Filter out already-present dialogs
        to_join: list[Union[int, str]] = []
        for t in resolved_targets:
            if isinstance(t, int) and t in existing_ids:
                skipped += 1
            else:
                to_join.append(t)

        # Optional limits and delay tuning via env
        join_limit = int(os.getenv("JOIN_LIMIT", "0") or "0")
        base_delay_min = float(os.getenv("BASE_DELAY_MIN", "15.0") or "15.0")
        base_delay_max = float(os.getenv("BASE_DELAY_MAX", "35.0") or "35.0")
        if join_limit > 0:
            to_join = to_join[: join_limit]

        print(f"[Join] Planned: to_join={len(to_join)} already_in_dialogs={len(existing_ids)} skipped_prefetch={skipped}")

        for t in to_join:
            # Anti-ban spacing between attempts (randomized base delay)
            base_delay = random.uniform(base_delay_min, base_delay_max)
            try:
                status = await _try_join(client, t)
                if status == "joined":
                    joined += 1
                    print(f"[Join] Joined: {t}")
                elif status == "skipped":
                    skipped += 1
                elif status in ("private", "banned", "limit", "invalid_invite"):
                    failed += 1
                    # Minimal logging for diagnostics without spam
                    print(f"[Join] Skipped ({status}): {t}")
                else:
                    failed += 1
                    print(f"[Join] Unknown status for {t}: {status}")
            except FloodWaitError as e:
                # Should be handled by decorator; fallback guard
                failed += 1
                print(f"[Join] Flood wait (fallback): wait {getattr(e, 'seconds', 5)}s for: {t}")
                break
            except Exception:
                failed += 1
                print(f"[Join] Failed to resolve/join: {t}")
            # Sleep after every attempt to avoid burst-joining
            await asyncio.sleep(base_delay)

    print(f"[Join] Summary: joined={joined} skipped={skipped} failed={failed} total={len(targets)}")


if __name__ == "__main__":
    asyncio.run(main())


