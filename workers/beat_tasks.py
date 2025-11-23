from __future__ import annotations

import asyncio
from typing import Any, List, Tuple, Union, Optional, Dict
from datetime import datetime, timedelta, timezone

from core.config import settings
from workers.celery_app import celery_app
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncEngine
from db.models import Message as DBMessage
from db.session import create_loop_bound_session_factory
from core.session_manager import SessionManager
from core.telethon_client import create_client_from_session
from telethon.utils import get_peer_id
from core.anti_ban import handle_flood_wait
from redis.asyncio import Redis
from typing import Dict, Set, Iterable, Any as _Any
from app.assignment import assign_channels_balanced, format_assignment_summary
from app.assignment_store import AssignmentStore
from app.weights import compute_channel_weights


def _parse_list(raw: str) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_chats(raw: str) -> list[Union[int, str]]:
    chats: list[Union[int, str]] = []
    for item in _parse_list(raw):
        try:
            chats.append(int(item))
        except ValueError:
            chats.append(item)
    return chats


def _pair_accounts_with_chats(
    accounts: List[str], chats: List[Union[int, str]]
) -> List[Tuple[str, Union[int, str]]]:
    if not chats:
        return []
    if not accounts:
        return []
    if len(accounts) == 1 and len(chats) >= 1:
        return [(accounts[0], chat) for chat in chats]
    size = min(len(accounts), len(chats))
    return [(accounts[i], chats[i]) for i in range(size)]


@celery_app.task(name="workers.beat_tasks.schedule_parsing", bind=True)
def schedule_parsing(self) -> dict[str, Any]:
    """
    Periodic scheduler:
      - Reads SCHEDULED_CHATS and SCHEDULED_ACCOUNTS (comma-separated)
      - Pairs accounts to chats (1-to-1; if one account is provided, uses it for all chats)
      - Enqueues workers.historical_worker.parse_history tasks
    """
    chats = _parse_chats(settings.scheduled_chats_raw)
    accounts = _parse_list(settings.scheduled_accounts_raw)
    days = int(settings.scheduled_history_days)

    pairs = _pair_accounts_with_chats(accounts, chats)
    enqueued: list[str] = []

    for account_phone, chat_entity in pairs:
        task = celery_app.send_task(
            "workers.historical_worker.backfill_chat",
            kwargs={"account_phone": account_phone, "chat_entity": chat_entity, "days": days},
        )
        enqueued.append(task.id)

    return {
        "configured_chats": len(chats),
        "configured_accounts": len(accounts),
        "scheduled_pairs": len(pairs),
        "enqueued_task_ids": enqueued,
        "days": days,
    }


async def _resolve_numeric_ids_if_needed(
    accounts: List[str], chats: List[Union[int, str]]
) -> List[int]:
    """
    Try to resolve string identifiers to numeric chat ids using the first account.
    If no accounts are provided, only numeric chats are returned.
    """
    numeric: list[int] = []
    primary_account: Optional[str] = accounts[0] if accounts else None
    # Fast-path for numeric inputs
    for c in chats:
        if isinstance(c, int):
            numeric.append(int(c))
    # Resolve string identifiers if we have an account to use
    to_resolve = [c for c in chats if not isinstance(c, int)]
    if primary_account and to_resolve:
        try:
            from scripts.resolve_chat_id import resolve_chat_id  # lazy import to avoid startup cost
        except Exception:
            to_resolve = []  # cannot resolve without helper
        else:
            for s in to_resolve:
                try:
                    cid, _ = await resolve_chat_id(account_phone=primary_account, identifier=str(s), accept_invite=False)
                    numeric.append(int(cid))
                except Exception:
                    # skip non-resolvable identifiers
                    continue
    # Deduplicate while preserving order
    seen: set[int] = set()
    unique_numeric: list[int] = []
    for cid in numeric:
        if cid not in seen:
            seen.add(cid)
            unique_numeric.append(cid)
    return unique_numeric


async def _resolve_token_id_map(
    accounts: List[str], chats: List[Union[int, str]]
) -> Dict[Union[int, str], int]:
    """
    Resolve each provided chat token to its numeric chat_id, preserving a mapping
    from the original token (int or str) to the resolved numeric id.
    """
    mapping: Dict[Union[int, str], int] = {}
    primary_account: Optional[str] = accounts[0] if accounts else None
    if not chats:
        return mapping
    # Int tokens map to themselves
    for c in chats:
        if isinstance(c, int):
            mapping[c] = int(c)
    # Resolve string identifiers if we have an account to use
    to_resolve = [c for c in chats if not isinstance(c, int)]
    if primary_account and to_resolve:
        try:
            from scripts.resolve_chat_id import resolve_chat_id  # lazy import
        except Exception:
            # Fallback: resolve via minimal inline logic with Telethon
            session_manager = SessionManager(
                redis_url=settings.redis_url,
                key_prefix=settings.telegram_session_prefix,
                encryption_key=settings.session_crypto_key,
            )

            @handle_flood_wait(max_retries=5)
            async def _safe_get_entity(client, arg):
                return await client.get_entity(arg)

            try:
                string_session = await session_manager.get_string_session(primary_account)
                if not string_session:
                    return mapping
                client = create_client_from_session(string_session)
                async with client:
                    for s in to_resolve:
                        try:
                            entity = await _safe_get_entity(client, str(s))
                            mapping[s] = int(get_peer_id(entity))
                        except Exception:
                            continue
            finally:
                await session_manager.close()
        else:
            for s in to_resolve:
                try:
                    cid, _ = await resolve_chat_id(
                        account_phone=primary_account, identifier=str(s), accept_invite=False
                    )
                    mapping[s] = int(cid)
                except Exception:
                    # skip non-resolvable identifiers
                    continue
    return mapping


async def _find_new_channel_ids(engine: AsyncEngine, candidate_chat_ids: List[int]) -> List[int]:
    if not candidate_chat_ids:
        return []
    threshold = datetime.now(tz=timezone.utc) - timedelta(minutes=15, seconds=1)
    async with engine.connect() as conn:
        result = await conn.execute(
            select(DBMessage.chat_id)
            .where(
                DBMessage.chat_id.in_(candidate_chat_ids),
                DBMessage.message_date < threshold,
            )
            .group_by(DBMessage.chat_id)
        )
        # Channels that already have messages older than the threshold
        have_old_messages = {int(chat_id) for chat_id in result.scalars()}
    # Treat channels as "new" if they do NOT have any messages older than threshold
    return [cid for cid in candidate_chat_ids if cid not in have_old_messages]


@celery_app.task(name="workers.beat_tasks.bootstrap_new_channels", bind=True)
def bootstrap_new_channels(self) -> dict[str, Any]:
    """
    Frequently run scheduler for new channels:
      - Determine which configured channels have zero rows in DB
      - Enqueue backfill tasks only for those channels
    """
    chats = _parse_chats(settings.scheduled_chats_raw)
    accounts = _parse_list(settings.scheduled_accounts_raw)
    days = int(settings.scheduled_history_days)

    # Resolve identifiers to numeric ids and keep mapping to original tokens
    new_ids: list[int] = []
    loop_engine, _ = create_loop_bound_session_factory()
    try:
        token_to_id = asyncio.run(_resolve_token_id_map(accounts, chats))
        numeric_ids = list({int(v) for v in token_to_id.values()})
        # Determine which ids are new in DB
        new_ids = asyncio.run(_find_new_channel_ids(loop_engine, numeric_ids))
    finally:
        # Dispose engine we created in this task
        try:
            asyncio.run(loop_engine.dispose())
        except Exception:
            pass

    # Prepare only those original tokens that correspond to "new" numeric ids
    new_tokens: list[Union[int, str]] = []
    if new_ids:
        new_ids_set = set(int(x) for x in new_ids)
        for token, cid in token_to_id.items():
            if int(cid) in new_ids_set:
                new_tokens.append(token)

    # Pair accounts with only new channel tokens (keep original identifiers for Telethon resolution)
    pairs = _pair_accounts_with_chats(accounts, new_tokens)
    enqueued: list[str] = []
    for account_phone, chat_entity in pairs:
        task = celery_app.send_task(
            "workers.historical_worker.backfill_chat",
            kwargs={"account_phone": account_phone, "chat_entity": chat_entity, "days": days},
        )
        enqueued.append(task.id)

    return {
        "configured_chats": len(chats),
        "configured_accounts": len(accounts),
        "new_channel_ids": new_ids,
        "scheduled_pairs": len(pairs),
        "enqueued_task_ids": enqueued,
        "days": days,
    }


async def _collect_dialog_chat_ids(account_id: str) -> Set[int]:
    """
    Connects to Telegram with given account_id and returns the set of numeric chat ids from dialogs.
    """
    session_manager = SessionManager(
        redis_url=settings.redis_url,
        key_prefix=settings.telegram_session_prefix,
        encryption_key=settings.session_crypto_key,
    )
    string_session = await session_manager.get_string_session(account_id)
    if not string_session:
        await session_manager.close()
        return set()
    client = create_client_from_session(string_session)
    chat_ids: Set[int] = set()
    try:
        async with client:
            async for d in client.iter_dialogs():
                try:
                    chat_ids.add(int(get_peer_id(d.entity)))
                except Exception:
                    continue
    finally:
        await session_manager.close()
    return chat_ids


async def _reassign_realtime_async() -> dict[str, _Any]:
    # accounts to consider
    accounts = _parse_list(settings.realtime_accounts_raw) or _parse_list(settings.scheduled_accounts_raw)
    # targets (tokens may be ints or strings)
    targets_tokens = _parse_chats(settings.realtime_chats_raw)
    token_to_id = await _resolve_token_id_map(accounts, targets_tokens)
    target_ids: List[int] = list({int(v) for v in token_to_id.values()})

    # compute eligible mapping: channel_id -> list[account_id]
    eligible: Dict[int, list[str]] = {cid: [] for cid in target_ids}
    for acct in accounts:
        dialog_ids = await _collect_dialog_chat_ids(acct)
        for cid in target_ids:
            if cid in dialog_ids:
                eligible[cid].append(acct)

    # weights
    weights = await compute_channel_weights(alpha=float(settings.weight_alpha), min_weight=float(settings.weight_min))

    # capacity per account
    if settings.realtime_account_capacity_default is None:
        capacities: Dict[str, float] = {a: float("inf") for a in accounts}
    else:
        capacities = {a: float(settings.realtime_account_capacity_default) for a in accounts}

    # run assignment
    assignment = assign_channels_balanced(
        channels=target_ids,
        eligible=eligible,
        channel_weight=weights,
        accounts=accounts,
        account_capacity=capacities,
    )

    # store in Redis with summary
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    store = AssignmentStore(redis, key_prefix=settings.realtime_assignment_redis_prefix)
    prev = await store.read_all(accounts)
    summary = format_assignment_summary(prev, assignment, weights, capacities, target_ids)
    print(summary)
    await store.write_all(assignment, summary=summary)
    await redis.aclose()

    # return compact dict for task result
    coverage = sum(1 for _ in set().union(*assignment.values()) if True)
    return {
        "accounts_considered": len(accounts),
        "targets": len(target_ids),
        "covered": coverage,
    }


@celery_app.task(name="workers.beat_tasks.reassign_realtime", bind=True)
def reassign_realtime(self) -> dict[str, Any]:
    """
    Periodic task to:
      - compute channel activity weights,
      - discover account eligibility (joined dialogs),
      - assign channels to accounts with balancing,
      - store assignments in Redis, and log a compact summary.
    """
    return asyncio.run(_reassign_realtime_async())
