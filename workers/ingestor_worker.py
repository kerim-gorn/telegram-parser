import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import aio_pika
from aio_pika import Message, DeliveryMode
from aio_pika.abc import AbstractRobustConnection, AbstractChannel, AbstractQueue
from sqlalchemy.dialects.postgresql import insert

from core.config import settings
from db.models import Message as DBMessage
from db.session import create_loop_bound_session_factory
from app.llm_analyzer import analyze_message_for_signal
from app.signal_notifier import notifier as signal_notifier


def _parse_datetime(value: Any) -> datetime:
    """
    Parse ISO-like datetime string to aware UTC datetime. Fallback to now.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)  # supports 'YYYY-MM-DDTHH:MM:SS+00:00'
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return datetime.now(tz=timezone.utc)


async def _persist_message(payload: dict[str, Any]) -> None:
    """
    Persist single message payload into PostgreSQL using upsert-like behavior.
    """
    chat_id = int(payload.get("chat_id")) if payload.get("chat_id") is not None else None
    message = payload.get("message") or {}
    message_id = int(payload.get("message_id") or message.get("id"))
    text = message.get("message")
    sender_id = None
    from_id = message.get("from_id")
    if isinstance(from_id, dict):
        # Telethon to_dict for Peer may look like {'_': 'PeerUser', 'user_id': 123}
        sender_id = from_id.get("user_id") or from_id.get("channel_id") or from_id.get("chat_id")
    elif isinstance(from_id, int):
        sender_id = from_id
    date_raw = message.get("date")
    message_date = _parse_datetime(date_raw)

    # LLM analysis (async) before persisting
    analysis_result: dict[str, Any] = {}
    llm_data: dict[str, Any] | None = None
    analysis_json: dict[str, Any] | None = None
    is_signal: bool = False
    if isinstance(text, str) and text.strip():
        try:
            analysis_result = await analyze_message_for_signal(text)
            if isinstance(analysis_result, dict):
                data = analysis_result.get("data")
                if isinstance(data, dict):
                    llm_data = data
                    is_signal = bool(data.get("is_signal", False))
                    # Persist unified JSON with top-level ok flag
                    analysis_json = {"ok": True, **data}
                else:
                    # Fallback: if analyzer returned the JSON directly (unlikely), try to use it
                    if isinstance(analysis_result, dict) and "is_signal" in analysis_result:
                        llm_data = analysis_result  # type: ignore[assignment]
                        is_signal = bool(analysis_result.get("is_signal", False))
                        analysis_json = {"ok": True, **analysis_result}  # type: ignore[arg-type]
                    else:
                        # Analyzer returned envelope with failure — capture minimal error info
                        if analysis_result.get("ok") is False:
                            err: dict[str, Any] = {"ok": False}
                            if isinstance(analysis_result.get("error"), str):
                                err["error"] = analysis_result.get("error")
                            if isinstance(analysis_result.get("message"), str):
                                err["message"] = analysis_result.get("message")
                            # Enrich with HTTP details when available
                            if isinstance(analysis_result.get("status_code"), int):
                                err["status_code"] = analysis_result.get("status_code")
                            if isinstance(analysis_result.get("body"), str):
                                err["body"] = analysis_result.get("body")
                            analysis_json = err
        except Exception:
            # Keep analysis_result empty on failure; we still persist the message
            analysis_result = {"ok": False, "error": "analysis_failed"}
            analysis_json = {"ok": False, "error": "analysis_failed"}

    if chat_id is None:
        # If chat_id missing, attempt to infer from peer_id
        peer = message.get("peer_id") or {}
        for k in ("channel_id", "chat_id", "user_id"):
            v = peer.get(k)
            if isinstance(v, int):
                chat_id = int(v) if k != "user_id" else int(v)  # fallback; may be a DM
                break

    if chat_id is None:
        # As a last resort, drop message (cannot key it)
        return

    loop_engine, _session_factory = create_loop_bound_session_factory()
    try:
        rows = [
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "sender_id": int(sender_id) if sender_id is not None else None,
                "text": text,
                "is_signal": is_signal,
                "llm_analysis": analysis_json if analysis_json is not None else llm_data,
                "message_date": message_date,
                "indexed_at": datetime.now(tz=timezone.utc),
            }
        ]
        stmt = insert(DBMessage).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["chat_id", "message_id"])
        async with loop_engine.begin() as conn:
            await conn.execute(stmt)
    finally:
        await loop_engine.dispose()

    # Notify to signals channel if configured and the message is a signal
    if is_signal and isinstance(text, str) and text.strip():
        try:
            # Fire-and-forget to avoid blocking ingestion loop
            asyncio.create_task(
                signal_notifier.send_signal(
                    text=text,
                    source_chat_id=chat_id,
                    sender_id=int(sender_id) if sender_id is not None else None,
                    source_message_id=message_id,
                )
            )
        except Exception:
            # Do not fail ingestion on notifier issues
            pass


async def _consume_queue(channel: AbstractChannel, queue_name: str) -> None:
    # Use passive declaration to avoid mismatched argument errors (definitions manage properties)
    queue: AbstractQueue = await channel.declare_queue(queue_name, durable=True, passive=True)
    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process(ignore_processed=True, requeue=False):
                try:
                    payload = json.loads(message.body.decode("utf-8"))
                    await _persist_message(payload)
                except Exception:
                    # nack without requeue to route to DLQ per queue policy
                    await message.reject(requeue=False)


async def main() -> None:
    connection: AbstractRobustConnection = await aio_pika.connect_robust(settings.celery_broker_url)
    try:
        channel: AbstractChannel = await connection.channel()
        await channel.set_qos(prefetch_count=100)
        await asyncio.gather(
            _consume_queue(channel, "realtime_raw"),
            _consume_queue(channel, "historical_raw"),
        )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
