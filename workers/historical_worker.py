from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence, Union

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine
from telethon.tl.custom.message import Message as TGMessage
from telethon.utils import get_peer_id

from core.anti_ban import handle_flood_wait
from core.config import settings
from core.session_manager import SessionManager
from core.telethon_client import create_client_from_session
from db.models import Message as DBMessage
from db.session import create_loop_bound_session_factory
from workers.celery_app import celery_app
import aio_pika
from aio_pika import ExchangeType, Message, DeliveryMode
from aio_pika.abc import AbstractRobustConnection, AbstractChannel, AbstractExchange


@handle_flood_wait(max_retries=5)
async def _safe_get_entity(client, chat: Union[int, str]):
    return await client.get_entity(chat)


@handle_flood_wait(max_retries=5)
async def _safe_get_messages(client, chat, limit: int, offset_id: int):
    return await client.get_messages(chat, limit=limit, offset_id=offset_id)


async def _save_messages_batch(
    engine: AsyncEngine,
    messages: Sequence[TGMessage],
    chat_username: Optional[str] = None,
) -> int:
    rows: list[dict] = []
    # Normalize chat_username once
    if isinstance(chat_username, str) and chat_username.strip():
        norm_chat_username = chat_username if chat_username.startswith("@") else f"@{chat_username}"
    else:
        norm_chat_username = None
    for m in messages:
        if not isinstance(m, TGMessage):
            continue
        msg_dt = m.date
        if msg_dt.tzinfo is None:
            msg_dt = msg_dt.replace(tzinfo=timezone.utc)
        rows.append(
            {
                "chat_id": int(m.chat_id),
                "message_id": int(m.id),
                "sender_id": int(m.sender_id) if m.sender_id is not None else None,
                "sender_username": None,  # avoid extra per-message lookups
                "chat_username": norm_chat_username,
                "text": m.message,
                "message_date": msg_dt,
            }
        )
    if not rows:
        return 0
    stmt = insert(DBMessage).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["chat_id", "message_id"])
    async with engine.begin() as conn:
        await conn.execute(stmt)
    return len(rows)


async def _async_backfill_chat(
    account_phone: str,
    chat_entity: Union[int, str],
    days: int = 30,
    batch_size: int = 200,
) -> str:
    """
    Backfill parser:
    - Loads encrypted StringSession from Redis by account_phone
    - Resolves chat entity and determines last known message_id from DB
    - If last_known_message_id exists, fetches messages newer than that id
    - If not, fetches messages down to now - `days`
    - Persists messages into PostgreSQL in batches
    """
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
        saved = 0
        from_dt = datetime.now(tz=timezone.utc) - timedelta(days=max(0, int(days)))

        async with client:
            amqp_conn: AbstractRobustConnection | None = None
            exchange: AbstractExchange | None = None
            if settings.backfill_via_rabbit:
                # Establish AMQP connection and declare durable fanout exchange
                amqp_conn = await aio_pika.connect_robust(settings.celery_broker_url)
                channel: AbstractChannel = await amqp_conn.channel()
                exchange = await channel.declare_exchange(
                    settings.historical_exchange_name, ExchangeType.FANOUT, durable=True
                )
            target = await _safe_get_entity(client, chat_entity)
            if target is None:
                raise RuntimeError(f"Failed to resolve chat entity: {chat_entity}")

            chat_id_numeric = int(get_peer_id(target))
            target_username = getattr(target, "username", None)
            if isinstance(target_username, str) and target_username:
                norm_target_username = target_username if target_username.startswith("@") else f"@{target_username}"
            else:
                norm_target_username = None

            # Create engine/session factory bound to THIS event loop
            loop_engine, loop_session_factory = create_loop_bound_session_factory()
            try:
                # 1) Fetch last_known_message_id for this chat
                async with loop_engine.connect() as conn:
                    last_known_message_id: Optional[int] = await conn.scalar(
                        select(func.max(DBMessage.message_id)).where(DBMessage.chat_id == chat_id_numeric)
                    )

                # 2) Iterate messages from newest to oldest; stop according to last_known or date threshold
                buffer: list[TGMessage] = []
                async for m in client.iter_messages(entity=target):
                    if not isinstance(m, TGMessage):
                        continue
                    # If we have historical data, stop as soon as we reach or cross it
                    if last_known_message_id is not None and int(m.id) <= int(last_known_message_id):
                        break
                    # For brand new chats, respect the days horizon
                    if last_known_message_id is None:
                        md = m.date.replace(tzinfo=m.date.tzinfo or timezone.utc)
                        if md < from_dt:
                            break
                    if settings.backfill_via_rabbit:
                        # Publish immediately per message to avoid large memory spikes
                        payload = {
                            "event": "HistoricalMessage",
                            "chat_id": chat_id_numeric,
                            "message_id": int(m.id),
                            "message": m.to_dict(),
                            "chat_username": norm_target_username,
                        }
                        assert exchange is not None
                        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
                        msg = Message(body=body, content_type="application/json", delivery_mode=DeliveryMode.PERSISTENT)
                        await exchange.publish(msg, routing_key="")
                        saved += 1
                    else:
                        buffer.append(m)
                        if len(buffer) >= batch_size:
                            saved += await _save_messages_batch(loop_engine, buffer, norm_target_username)  # type: ignore[arg-type]
                            buffer.clear()
                # Flush remainder
                if not settings.backfill_via_rabbit and buffer:
                    saved += await _save_messages_batch(loop_engine, buffer, norm_target_username)  # type: ignore[arg-type]
            finally:
                await loop_engine.dispose()
                if settings.backfill_via_rabbit and amqp_conn is not None:
                    await amqp_conn.close()

        return f"parsed_and_saved={saved}"
    finally:
        await session_manager.close()


@celery_app.task(name="workers.historical_worker.backfill_chat", bind=True)
def backfill_chat(
    self,
    account_phone: str,
    chat_entity: Union[int, str],
    days: int = 30,
    batch_size: int = 200,
) -> str:
    """
    Historical backfill worker (ephemeral). Stateless by design.
    """
    return asyncio.run(_async_backfill_chat(account_phone, chat_entity, days=days, batch_size=batch_size))


@celery_app.task(name="workers.historical_worker.process_new_message", bind=True)
def process_new_message(
    self, chat_id: Union[int, str], message_id: int, text: str
) -> None:
    """
    Process a single new message pushed from the realtime worker.
    """
    _ = (chat_id, message_id, text)
    return None


