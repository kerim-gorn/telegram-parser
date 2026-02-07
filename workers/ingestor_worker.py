import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import aio_pika
from aio_pika import Message, DeliveryMode
from aio_pika.abc import AbstractRobustConnection, AbstractChannel, AbstractQueue
from sqlalchemy.dialects.postgresql import insert

from core.config import settings
from db.models import Message as DBMessage
from db.session import create_loop_bound_session_factory
from app.batch_llm_analyzer import analyze_messages_batch
from app.signal_notifier import notifier as signal_notifier
from app.prefilter import get_prefilter
from app.domain_router import get_domain_router
from app.config_loader import get_chat_locations_from_config, normalize_chat_identifier
from app.classification import IntentType, DomainInfo

# Batch processing configuration
READ_BATCH_SIZE = 70
READ_BATCH_TIMEOUT_SECONDS = 5.0
LLM_BATCH_SIZE = settings.llm_batch_size


async def _stats_reporter(stats: dict[str, Any]) -> None:
    """
    Periodically print and reset ingestion statistics (every 60 seconds).
    """
    while True:
        try:
            await asyncio.sleep(60)
            consumed = int(stats.get("consumed", 0))
            persisted = int(stats.get("persisted", 0))
            failed = int(stats.get("failed", 0))
            notifications_sent = int(stats.get("notifications_sent", 0))
            forced = int(stats.get("forced", 0))
            filtered = int(stats.get("filtered", 0))
            urgency_distribution = stats.get("urgency_distribution", {})
            last = stats.get("last_event")
            print(
                f"[Ingestor] stats: consumed={consumed} persisted={persisted} failed={failed} "
                f"notifications={notifications_sent} forced={forced} filtered={filtered} "
                f"urgency={urgency_distribution} last={last}",
                flush=True,
            )
            stats["consumed"] = 0
            stats["persisted"] = 0
            stats["failed"] = 0
            stats["notifications_sent"] = 0
            stats["forced"] = 0
            stats["filtered"] = 0
            stats["urgency_distribution"] = defaultdict(int)
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


def _extract_message_data(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Extract and normalize message data from payload.
    Returns dict with chat_id, message_id, sender_id, usernames, text, message_date.
    Returns None if chat_id cannot be determined.
    """
    chat_id = int(payload.get("chat_id")) if payload.get("chat_id") is not None else None
    message = payload.get("message") or {}
    message_id = int(payload.get("message_id") or message.get("id"))
    text = message.get("message")
    
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
    
    sender_id = None
    from_id = message.get("from_id")
    if isinstance(from_id, dict):
        sender_id = from_id.get("user_id") or from_id.get("channel_id") or from_id.get("chat_id")
    elif isinstance(from_id, int):
        sender_id = from_id
    
    date_raw = message.get("date")
    message_date = _parse_datetime(date_raw)
    
    if chat_id is None:
        # Try to infer from peer_id
        peer = message.get("peer_id") or {}
        for k in ("channel_id", "chat_id", "user_id"):
            v = peer.get(k)
            if isinstance(v, int):
                chat_id = int(v)
                break
    
    if chat_id is None:
        return None
    
    return {
        "chat_id": chat_id,
        "message_id": message_id,
        "sender_id": int(sender_id) if sender_id is not None else None,
        "sender_username": sender_username,
        "chat_username": chat_username,
        "text": text,
        "message_date": message_date,
        "original_payload": payload,  # Keep for notification
    }


async def _prefilter_batch(
    payloads: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[int]]:
    """
    Process a batch of message payloads:
    1. Apply prefilter to each message
    2. Split into forced/skip/llm_candidates
    3. Return results for immediate persistence + LLM candidates
    """
    results: list[dict[str, Any]] = []
    llm_candidates: list[dict[str, Any]] = []
    llm_candidate_indices: list[int] = []
    
    # Process each payload with prefilter
    for idx, payload in enumerate(payloads):
        msg_data = _extract_message_data(payload)
        if msg_data is None:
            # Cannot determine chat_id, skip this message
            results.append({
                "skipped": True,
                "reason": "no_chat_id",
                "payload": payload,
            })
            continue
        
        text = msg_data.get("text")
        decision: str | None = None
        matched: list[str] = []
        
        # Apply prefilter
        if isinstance(text, str) and text.strip():
            try:
                decision, matched = await get_prefilter().match(text)
            except Exception:
                decision, matched = (None, [])
        
        if decision == "force":
            # Forced message - mark as signal with default classification
            results.append({
                "msg_data": msg_data,
                "prefilter_decision": "force",
                "prefilter_matched": matched,
                "intents": ["REQUEST"],
                "domains": [{"domain": "CONSTRUCTION_AND_REPAIR", "subcategories": []}],
                "is_spam": False,
                "urgency_score": 3,
                "reasoning": f"Forced by prefilter (matched: {', '.join(matched)})",
                "llm_analysis": {"ok": True, "forced": True, "matched": matched},
                "openrouter_response": None,
            })
        elif decision == "skip":
            # Skipped message - mark as non-signal with minimal classification
            results.append({
                "msg_data": msg_data,
                "prefilter_decision": "skip",
                "prefilter_matched": matched,
                "intents": ["OTHER"],
                "domains": [{"domain": "NONE", "subcategories": []}],
                "is_spam": False,
                "urgency_score": 1,
                "reasoning": f"Filtered by prefilter (matched: {', '.join(matched)})",
                "llm_analysis": {"ok": True, "filtered": True, "matched": matched},
                "openrouter_response": None,
            })
        else:
            # Candidate for LLM analysis
            if isinstance(text, str) and text.strip():
                llm_candidates.append(msg_data)
                llm_candidate_indices.append(len(results))
                # Placeholder result, will be updated after LLM
                results.append({
                    "msg_data": msg_data,
                    "prefilter_decision": None,
                    "llm_pending": True,
                })
            else:
                # Empty text, minimal classification
                results.append({
                    "msg_data": msg_data,
                    "prefilter_decision": None,
                    "intents": ["OTHER"],
                    "domains": [{"domain": "NONE", "subcategories": []}],
                    "is_spam": False,
                    "urgency_score": 1,
                    "reasoning": "Empty or no text content",
                    "llm_analysis": None,
                    "openrouter_response": None,
                })
    
    return results, llm_candidates, llm_candidate_indices


async def _process_llm_batch(
    llm_candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """
    Process a batch of LLM candidates (strictly sized).
    Returns (results, error_info). error_info is set for requeue decisions.
    """
    if not llm_candidates:
        return [], None

    # Prepare messages for LLM
    llm_messages = [
        {
            "id": f"{msg['chat_id']}_{msg['message_id']}",
            "text": msg["text"] or "",
        }
        for msg in llm_candidates
    ]
    try:
        payload_preview = json.dumps(llm_messages, ensure_ascii=False)
        if len(payload_preview) > 2000:
            payload_preview = payload_preview[:2000] + "...(truncated)"
        print(f"[Ingestor] LLM payload: {payload_preview}", flush=True)
    except Exception:
        # Never break ingestion because of logging issues
        pass

    # Call batch LLM analyzer
    llm_result = await analyze_messages_batch(llm_messages)

    results: list[dict[str, Any]] = []
    if llm_result.get("ok") is True:
        openrouter_response = llm_result.get("raw")
        data = llm_result.get("data", {})
        classified_messages = data.get("classified_messages", [])
        parse_errors = llm_result.get("parse_errors") or []
        parse_error_map: dict[str, str] = {}
        for err in parse_errors:
            err_id = str(err.get("id", "")).strip()
            err_msg = str(err.get("error", "")).strip() or "unknown_parse_error"
            if err_id:
                parse_error_map[err_id] = err_msg

        # Map LLM results back to candidates
        llm_result_map: dict[str, dict[str, Any]] = {}
        for classified in classified_messages:
            msg_id = classified.get("id", "")
            llm_result_map[msg_id] = classified

        # Update results with LLM classification
        for msg_data in llm_candidates:
            msg_id = f"{msg_data['chat_id']}_{msg_data['message_id']}"
            classified = llm_result_map.get(msg_id, {})

            if classified:
                intents = [intent for intent in classified.get("intents", [])]
                domains = classified.get("domains", [])
                is_spam = classified.get("is_spam", False)
                urgency_score = classified.get("urgency_score", 1)
                reasoning = classified.get("reasoning", "LLM classification")
                llm_analysis = {"ok": True, **classified}
            else:
                parse_reason = parse_error_map.get(msg_id)
                if parse_reason:
                    reasoning = f"LLM parse failed: {parse_reason}"
                    llm_analysis = {"ok": False, "error": "parse_error", "message": parse_reason}
                else:
                    reasoning = "LLM result missing for message"
                    llm_analysis = {"ok": False, "error": "missing_result"}
                intents = ["OTHER"]
                domains = [{"domain": "NONE", "subcategories": []}]
                is_spam = False
                urgency_score = 1

            results.append(
                {
                    "msg_data": msg_data,
                    "prefilter_decision": None,
                    "intents": intents,
                    "domains": domains,
                    "is_spam": is_spam,
                    "urgency_score": urgency_score,
                    "reasoning": reasoning,
                    "llm_analysis": llm_analysis,
                    "openrouter_response": openrouter_response,
                }
            )
        return results, None
    else:
        # LLM failed, mark candidates with detailed error info
        error_type = llm_result.get("error") or "unknown_error"
        status_code = llm_result.get("status_code")
        body = llm_result.get("body")
        base_message = llm_result.get("message")

        # Build human-readable error message with as much context as possible
        parts: list[str] = [error_type]
        if status_code is not None:
            parts.append(f"status={status_code}")
        if body:
            # Truncate body to avoid huge payloads in reasoning
            body_snippet = str(body)
            if len(body_snippet) > 500:
                body_snippet = body_snippet[:500] + "...(truncated)"
            parts.append(f"body_snippet={body_snippet}")
        if base_message and base_message not in parts:
            parts.append(f"message={base_message}")
        error_msg = "; ".join(parts)

        # Store full LLM error payload (except ok flag) in llm_analysis for debugging
        error_payload = {k: v for k, v in llm_result.items() if k != "ok"}
        openrouter_response = llm_result.get("raw") or error_payload or None

        # Log once per failed batch for easier debugging in container logs
        try:
            print(
                "[Ingestor] LLM batch error: "
                + json.dumps(error_payload, ensure_ascii=False)[:1000],
                flush=True,
            )
        except Exception:
            # Never break ingestion because of logging issues
            pass

        if (
            error_type == "http_error"
            and isinstance(status_code, int)
            and 400 <= status_code < 600
        ):
            return [], {
                "requeue": True,
                "error": error_type,
                "status_code": status_code,
                "message": error_msg,
                "payload": error_payload,
            }

        for msg_data in llm_candidates:
            results.append(
                {
                    "msg_data": msg_data,
                    "prefilter_decision": None,
                    "intents": ["OTHER"],
                    "domains": [{"domain": "NONE", "subcategories": []}],
                    "is_spam": False,
                    "urgency_score": 1,
                    "reasoning": f"LLM analysis failed: {error_msg}",
                    "llm_analysis": {"ok": False, **error_payload},
                    "openrouter_response": openrouter_response,
                }
            )

    return results, None


async def _persist_batch(results: list[dict[str, Any]], stats: dict[str, Any]) -> None:
    """
    Persist a batch of processed message results to PostgreSQL.
    """
    rows: list[dict[str, Any]] = []
    notifications: list[dict[str, Any]] = []
    
    # Get domain router instance and chat location map
    domain_router = get_domain_router()
    chat_locations_map = get_chat_locations_from_config()
    
    for result in results:
        if result.get("skipped"):
            stats["failed"] = int(stats.get("failed", 0)) + 1
            continue
        
        msg_data = result.get("msg_data")
        if not msg_data:
            stats["failed"] = int(stats.get("failed", 0)) + 1
            continue
        
        # Prepare row for database
        row = {
            "chat_id": msg_data["chat_id"],
            "message_id": msg_data["message_id"],
            "sender_id": msg_data["sender_id"],
            "sender_username": msg_data["sender_username"],
            "chat_username": msg_data["chat_username"],
            "text": msg_data["text"],
            "intents": result.get("intents"),
            "domains": result.get("domains"),
            "urgency_score": result.get("urgency_score"),
            "is_spam": result.get("is_spam", False),
            "reasoning": result.get("reasoning"),
            "llm_analysis": result.get("llm_analysis"),
            "openrouter_response": result.get("openrouter_response"),
            "message_date": msg_data["message_date"],
            "indexed_at": datetime.now(tz=timezone.utc),
        }
        rows.append(row)
        
        # Check if this message should be sent to Telegram groups
        # Only messages with REQUEST intent are routed
        intents = result.get("intents", [])
        domains_raw = result.get("domains", [])
        
        # Check if REQUEST intent is present
        has_request_intent = False
        if intents:
            # Handle both string and IntentType enum values
            intent_values = [str(intent) if not isinstance(intent, str) else intent for intent in intents]
            has_request_intent = IntentType.REQUEST.value in intent_values or "REQUEST" in intent_values
        
        if has_request_intent and isinstance(msg_data.get("text"), str) and msg_data["text"].strip():
            # Convert domains from dict format to DomainInfo objects
            domain_infos: list[DomainInfo] = []
            for domain_dict in domains_raw:
                if isinstance(domain_dict, dict):
                    try:
                        domain_info = DomainInfo(**domain_dict)
                        domain_infos.append(domain_info)
                    except Exception:
                        # Skip invalid domain info
                        continue
                elif isinstance(domain_dict, DomainInfo):
                    domain_infos.append(domain_dict)
            
            # Get chat_ids for these domains (location-aware if configured)
            source_chat_id = msg_data["chat_id"]
            source_locations = chat_locations_map.get(source_chat_id, [])
            if not source_locations:
                identifier_key = normalize_chat_identifier(msg_data.get("chat_username"))
                if identifier_key:
                    source_locations = chat_locations_map.get(identifier_key, [])
            target_chat_ids = domain_router.get_chat_ids_for_domains(
                domain_infos,
                locations=source_locations,
            )
            
            # Create notification entry for each target chat_id
            for target_chat_id in target_chat_ids:
                notifications.append({
                    "text": msg_data["text"],
                    "source_chat_id": msg_data["chat_id"],
                    "sender_id": msg_data["sender_id"],
                    "source_message_id": msg_data["message_id"],
                    "sender_username": msg_data.get("sender_username"),
                    "chat_username": msg_data.get("chat_username"),
                    "message_date": msg_data["message_date"],
                    "target_chat_id": target_chat_id,
                })
        
        # Update statistics
        prefilter_decision = result.get("prefilter_decision")
        if prefilter_decision == "force":
            stats["forced"] = int(stats.get("forced", 0)) + 1
        elif prefilter_decision == "skip":
            stats["filtered"] = int(stats.get("filtered", 0)) + 1
        
        urgency_score = result.get("urgency_score")
        if urgency_score:
            if "urgency_distribution" not in stats:
                stats["urgency_distribution"] = defaultdict(int)
            stats["urgency_distribution"][urgency_score] += 1
    
    if not rows:
        return
    
    # Batch insert
    loop_engine, _session_factory = create_loop_bound_session_factory()
    try:
        stmt = insert(DBMessage).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["chat_id", "message_id"])
        async with loop_engine.begin() as conn:
            await conn.execute(stmt)
        
        stats["persisted"] = int(stats.get("persisted", 0)) + len(rows)
    except Exception as e:
        stats["failed"] = int(stats.get("failed", 0)) + len(rows)
        print(f"[Ingestor] Error persisting batch: {e}", flush=True)
        raise
    finally:
        await loop_engine.dispose()
    
    # Send notifications (fire-and-forget)
    for notif in notifications:
        try:
            asyncio.create_task(signal_notifier.send_signal(**notif))
            stats["notifications_sent"] = int(stats.get("notifications_sent", 0)) + 1
        except Exception:
            # Do not fail ingestion on notifier issues
            pass


async def _consume_queue(channel: AbstractChannel, queue_name: str, stats: dict[str, Any]) -> None:
    """
    Consume messages from queue with batch processing.
    Accumulates messages in buffer until batch size or timeout is reached.
    """
    queue: AbstractQueue = await channel.declare_queue(queue_name, durable=True, passive=True)
    print(
        "[Ingestor] Consuming "
        f"'{queue_name}' (read_batch={READ_BATCH_SIZE}, timeout={READ_BATCH_TIMEOUT_SECONDS}s, "
        f"llm_batch={LLM_BATCH_SIZE})",
        flush=True,
    )
    
    buffer: list[aio_pika.IncomingMessage] = []
    buffer_lock = asyncio.Lock()
    last_batch_time = asyncio.get_event_loop().time()
    llm_pending: list[dict[str, Any]] = []
    
    async def process_buffered() -> None:
        """Process all messages currently in buffer."""
        nonlocal last_batch_time
        async with buffer_lock:
            if not buffer:
                return
            
            messages_to_process = buffer[:]
            buffer.clear()
            last_batch_time = asyncio.get_event_loop().time()
        
        if not messages_to_process:
            return
        
        # Parse payloads
        payloads: list[dict[str, Any]] = []
        ack_messages: list[aio_pika.IncomingMessage] = []
        
        for message in messages_to_process:
            try:
                raw = message.body or b""
                payload = json.loads(raw.decode("utf-8"))
                payloads.append(payload)
                ack_messages.append(message)
            except Exception as e:
                stats["failed"] = int(stats.get("failed", 0)) + 1
                snippet = (message.body or b"")[:300].decode("utf-8", errors="replace")
                print(f"[Ingestor] Error parsing message from '{queue_name}': {e}. body_snippet={snippet}", flush=True)
                await message.reject(requeue=False)
        
        if not payloads:
            return
        
        try:
            stats["consumed"] = int(stats.get("consumed", 0)) + len(payloads)
            
            # Prefilter batch
            results, llm_candidates, llm_candidate_indices = await _prefilter_batch(payloads)
            
            # Persist non-LLM results immediately
            results_for_persist = [result for result in results if not result.get("llm_pending")]
            if results_for_persist:
                await _persist_batch(results_for_persist, stats)
                
                # Update last event
                last_result = results_for_persist[-1]
                msg_data = last_result.get("msg_data")
                if msg_data:
                    stats["last_event"] = {
                        "queue": queue_name,
                        "chat_id": msg_data.get("chat_id"),
                        "message_id": msg_data.get("message_id"),
                    }
            
            # Ack non-LLM messages after persistence
            for idx, result in enumerate(results):
                if result.get("llm_pending"):
                    continue
                try:
                    await ack_messages[idx].ack()
                except Exception:
                    pass
            
            # Buffer LLM candidates for later processing; ack only after persistence
            llm_batches_to_process: list[list[dict[str, Any]]] = []
            async with buffer_lock:
                if llm_candidates:
                    llm_entries: list[dict[str, Any]] = []
                    for msg_data, idx in zip(llm_candidates, llm_candidate_indices):
                        if idx < len(ack_messages):
                            llm_entries.append(
                                {
                                    "msg_data": msg_data,
                                    "queue_message": ack_messages[idx],
                                }
                            )
                    llm_pending.extend(llm_entries)
                    while len(llm_pending) >= LLM_BATCH_SIZE:
                        llm_batches_to_process.append(llm_pending[:LLM_BATCH_SIZE])
                        del llm_pending[:LLM_BATCH_SIZE]
            
            # Process any full LLM batches
            for llm_batch in llm_batches_to_process:
                batch_candidates = [entry["msg_data"] for entry in llm_batch]
                llm_results, llm_error = await _process_llm_batch(batch_candidates)
                if llm_error and llm_error.get("requeue"):
                    for entry in llm_batch:
                        try:
                            await entry["queue_message"].reject(requeue=True)
                        except Exception:
                            pass
                    continue

                if llm_results:
                    await _persist_batch(llm_results, stats)

                    last_result = llm_results[-1]
                    msg_data = last_result.get("msg_data")
                    if msg_data:
                        stats["last_event"] = {
                            "queue": queue_name,
                            "chat_id": msg_data.get("chat_id"),
                            "message_id": msg_data.get("message_id"),
                        }

                for entry in llm_batch:
                    try:
                        await entry["queue_message"].ack()
                    except Exception:
                        pass
        except Exception as e:
            stats["failed"] = int(stats.get("failed", 0)) + len(payloads)
            print(f"[Ingestor] Error processing batch from '{queue_name}': {e}", flush=True)
            # Reject all messages in failed batch
            for message in ack_messages:
                await message.reject(requeue=False)
    
    async def timeout_processor() -> None:
        """Periodically check if buffer needs to be flushed due to timeout."""
        while True:
            try:
                await asyncio.sleep(1.0)  # Check every second
                now = asyncio.get_event_loop().time()
                async with buffer_lock:
                    if buffer and (now - last_batch_time) >= READ_BATCH_TIMEOUT_SECONDS:
                        # Trigger processing
                        asyncio.create_task(process_buffered())
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
    
    # Start timeout processor
    timeout_task = asyncio.create_task(timeout_processor())
    
    try:
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with buffer_lock:
                    buffer.append(message)
                    
                    # Process immediately if batch size reached
                    if len(buffer) >= READ_BATCH_SIZE:
                        asyncio.create_task(process_buffered())
    finally:
        timeout_task.cancel()
        try:
            await timeout_task
        except asyncio.CancelledError:
            pass
        
        # Process remaining messages in buffer
        await process_buffered()


async def main() -> None:
    print(
        "[Ingestor] Starting (batch mode). "
        f"Broker={settings.celery_broker_url} "
        f"ReadBatch={READ_BATCH_SIZE} "
        f"ReadTimeout={READ_BATCH_TIMEOUT_SECONDS}s "
        f"LlmBatch={LLM_BATCH_SIZE} "
        f"Prefilter={settings.prefilter_config_json or 'disabled'} "
        f"Reload={settings.prefilter_reload_seconds}s",
        flush=True,
    )
    connection: AbstractRobustConnection = await aio_pika.connect_robust(settings.celery_broker_url)
    try:
        channel: AbstractChannel = await connection.channel()
        await channel.set_qos(prefetch_count=200)  # Increased for batch processing
        print("[Ingestor] Consuming queues: realtime_raw, historical_raw", flush=True)
        stats: dict[str, Any] = {
            "consumed": 0,
            "persisted": 0,
            "failed": 0,
            "notifications_sent": 0,
            "forced": 0,
            "filtered": 0,
            "urgency_distribution": defaultdict(int),
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
