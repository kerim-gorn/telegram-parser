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
from app.prefilter import get_prefilter


async def _stats_reporter(stats: dict[str, Any]) -> None:
    """
    Periodically print and reset ingestion statistics (every 60 seconds).
    Mirrors the lightweight reporting style of the realtime worker.
    """
    while True:
        try:
            await asyncio.sleep(60)
            consumed = int(stats.get("consumed", 0))
            persisted = int(stats.get("persisted", 0))
            failed = int(stats.get("failed", 0))
            signals = int(stats.get("signals", 0))
            forced = int(stats.get("forced", 0))
            filtered = int(stats.get("filtered", 0))
            last = stats.get("last_event")
            print(
                f"[Ingestor] stats: consumed={consumed} persisted={persisted} failed={failed} "
                f"signals={signals} forced={forced} filtered={filtered} last={last}",
                flush=True,
            )
            stats["consumed"] = 0
            stats["persisted"] = 0
            stats["failed"] = 0
            stats["signals"] = 0
            stats["forced"] = 0
            stats["filtered"] = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            # Avoid log spam if something goes wrong in the reporter; continue running.
            pass


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


async def _persist_message(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Persist single message payload into PostgreSQL using upsert-like behavior.
    Returns a small outcome dict for metrics: is_signal and prefilter decision.
    """
    chat_id = int(payload.get("chat_id")) if payload.get("chat_id") is not None else None
    message = payload.get("message") or {}
    message_id = int(payload.get("message_id") or message.get("id"))
    text = message.get("message")
    sender_id = None
    # Optional usernames from payload (already best-effort in realtime/historical workers)
    sender_username = payload.get("sender_username")
    if isinstance(sender_username, str) and sender_username.strip():
        sender_username = sender_username if sender_username.startswith("@") else f"@{sender_username}"
    else:
        sender_username = None
    chat_username = payload.get("chat_username")
    if isinstance(chat_username, str) and chat_username.strip():
        chat_username = chat_username if chat_username.startswith("@") else f"@{chat_username}"
    else:
        chat_username = None
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
    decision: str | None = None  # "force" | "skip" | None
    if isinstance(text, str) and text.strip():
        # Prefilter (skip/force) before LLM
        try:
            decision, matched = await get_prefilter().match(text)
        except Exception:
            decision, matched = (None, [])
        if decision == "force":
            is_signal = True
            analysis_json = {"ok": True, "is_signal": True, "forced": True, "matched": matched}
        elif decision == "skip":
            is_signal = False
            analysis_json = {"ok": True, "is_signal": False, "filtered": True, "matched": matched}
        else:
            try:
                analysis_result = await analyze_message_for_signal(text)
                if isinstance(analysis_result, dict):
                    data = analysis_result.get("data")
                    if isinstance(data, dict):
                        llm_data = data
                        is_signal = bool(data.get("is_signal", False))
                        analysis_json = {"ok": True, **data}
                    else:
                        if isinstance(analysis_result, dict) and "is_signal" in analysis_result:
                            llm_data = analysis_result  # type: ignore[assignment]
                            is_signal = bool(analysis_result.get("is_signal", False))
                            analysis_json = {"ok": True, **analysis_result}  # type: ignore[arg-type]
                        else:
                            if analysis_result.get("ok") is False:
                                err: dict[str, Any] = {"ok": False}
                                if isinstance(analysis_result.get("error"), str):
                                    err["error"] = analysis_result.get("error")
                                if isinstance(analysis_result.get("message"), str):
                                    err["message"] = analysis_result.get("message")
                                if isinstance(analysis_result.get("text"), str) and analysis_result.get("text"):
                                    err["assistant_text"] = analysis_result.get("text")
                                if isinstance(analysis_result.get("status_code"), int):
                                    err["status_code"] = analysis_result.get("status_code")
                                if isinstance(analysis_result.get("body"), str):
                                    err["body"] = analysis_result.get("body")
                                analysis_json = err
            except Exception:
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
                "sender_username": sender_username,
                "chat_username": chat_username,
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
                    sender_username=payload.get("sender_username"),
                    chat_username=payload.get("chat_username"),
                    message_date=message_date,
                )
            )
        except Exception:
            # Do not fail ingestion on notifier issues
            pass
    return {
        "is_signal": is_signal,
        "decision": decision,
        "chat_id": chat_id,
        "message_id": message_id,
    }


async def _consume_queue(channel: AbstractChannel, queue_name: str, stats: dict[str, Any]) -> None:
    # Use passive declaration to avoid mismatched argument errors (definitions manage properties)
    queue: AbstractQueue = await channel.declare_queue(queue_name, durable=True, passive=True)
    print(f"[Ingestor] Consuming '{queue_name}'", flush=True)
    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process(ignore_processed=True, requeue=False):
                try:
                    stats["consumed"] = int(stats.get("consumed", 0)) + 1
                    raw = message.body or b""
                    payload = json.loads(raw.decode("utf-8"))
                    outcome = await _persist_message(payload)
                    stats["persisted"] = int(stats.get("persisted", 0)) + 1
                    if bool(outcome.get("is_signal", False)):
                        stats["signals"] = int(stats.get("signals", 0)) + 1
                    d = outcome.get("decision")
                    if d == "force":
                        stats["forced"] = int(stats.get("forced", 0)) + 1
                    elif d == "skip":
                        stats["filtered"] = int(stats.get("filtered", 0)) + 1
                    stats["last_event"] = {
                        "queue": queue_name,
                        "chat_id": outcome.get("chat_id"),
                        "message_id": outcome.get("message_id"),
                    }
                except Exception as e:
                    stats["failed"] = int(stats.get("failed", 0)) + 1
                    # Safe snippet of body for debugging (avoid flooding logs)
                    snippet: str
                    try:
                        snippet = (message.body or b"")[:300].decode("utf-8", errors="replace")
                    except Exception:
                        snippet = "<unprintable>"
                    print(
                        f"[Ingestor] Error processing message from '{queue_name}': {e}. body_snippet={snippet}",
                        flush=True,
                    )
                    # nack without requeue to route to DLQ per queue policy
                    await message.reject(requeue=False)


async def main() -> None:
    print(
        "[Ingestor] Starting. "
        f"Broker={settings.celery_broker_url} "
        f"Prefilter={settings.prefilter_config_json or 'disabled'} "
        f"Reload={settings.prefilter_reload_seconds}s",
        flush=True,
    )
    connection: AbstractRobustConnection = await aio_pika.connect_robust(settings.celery_broker_url)
    try:
        channel: AbstractChannel = await connection.channel()
        await channel.set_qos(prefetch_count=100)
        print("[Ingestor] Consuming queues: realtime_raw, historical_raw", flush=True)
        stats: dict[str, Any] = {
            "consumed": 0,
            "persisted": 0,
            "failed": 0,
            "signals": 0,
            "forced": 0,
            "filtered": 0,
            "last_event": None,
        }
        await asyncio.gather(
            _stats_reporter(stats),
            _consume_queue(channel, "realtime_raw", stats),
            _consume_queue(channel, "historical_raw", stats),
        )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
