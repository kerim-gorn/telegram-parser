import asyncio
import json
from typing import Any, Iterable, Union, Set

import aio_pika
from aio_pika import ExchangeType, Message, DeliveryMode
from aio_pika.abc import AbstractRobustConnection, AbstractChannel, AbstractExchange
from telethon import events
from telethon.errors.rpcerrorlist import AuthKeyUnregisteredError, SessionExpiredError
from telethon.utils import get_peer_id

from core.config import settings
from core.session_manager import SessionManager
from core.telethon_client import create_client_from_session
from redis.asyncio import Redis
from app.assignment_store import AssignmentStore
from app.config_loader import get_chats_from_config


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
            chats.append(token)
    return chats


async def _setup_rabbitmq() -> tuple[AbstractRobustConnection, AbstractChannel, AbstractExchange]:
    """
    Establish robust AMQP connection and declare a durable fanout exchange.
    """
    connection: AbstractRobustConnection = await aio_pika.connect_robust(settings.celery_broker_url)
    channel: AbstractChannel = await connection.channel()
    exchange: AbstractExchange = await channel.declare_exchange(
        settings.realtime_exchange_name, ExchangeType.FANOUT, durable=True
    )
    return connection, channel, exchange


async def _publish_message(exchange: AbstractExchange, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    msg = Message(body=body, content_type="application/json", delivery_mode=DeliveryMode.PERSISTENT)
    # Fanout ignores routing_key
    await exchange.publish(msg, routing_key="")


async def run_realtime_worker(account_id: str | None = None) -> None:
    """
    Persistent realtime worker:
      - Loads encrypted StringSession from Redis (stateless worker).
      - Connects to Telegram once and listens for events.NewMessage.
      - Immediately publishes message payloads to RabbitMQ fanout exchange.
    """
    acct_id = account_id or settings.telegram_account_id
    # Use chats from config file if provided; fallback to env
    chats_filter: list[Union[int, str]] = get_chats_from_config() or _parse_chats(settings.realtime_chats_raw)

    session_manager = SessionManager(
        settings.redis_url,
        settings.telegram_session_prefix,
        settings.session_crypto_key,
    )
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    store = AssignmentStore(redis, key_prefix=settings.realtime_assignment_redis_prefix)
    allowed_ids: Set[int] = set()
    dialog_ids: Set[int] = set()
    dialog_titles: dict[int, str] = {}

    while True:
        client = None
        amqp_connection: AbstractRobustConnection | None = None
        try:
            string_session = await session_manager.get_string_session(acct_id)
            if not string_session:
                raise RuntimeError(
                    f"No StringSession found in Redis for account '{acct_id}'. "
                    "Run scripts/onboard_account.py to bootstrap."
                )

            client = create_client_from_session(string_session)
            amqp_connection, channel, exchange = await _setup_rabbitmq()

            async with client:
                # Identify self and collect dialogs for observability (once at start)
                try:
                    me = await client.get_me()
                    me_name = getattr(me, "username", None) or getattr(me, "phone", None) or str(getattr(me, "id", ""))
                except Exception:
                    me_name = "unknown"
                try:
                    dialog_ids = set()
                    dialog_titles = {}
                    async for d in client.iter_dialogs():
                        try:
                            pid = int(get_peer_id(d.entity))
                            dialog_ids.add(pid)
                            title = getattr(d.entity, "title", None) or getattr(d.entity, "username", None) or str(pid)
                            dialog_titles[pid] = str(title)
                        except Exception:
                            continue
                except Exception:
                    pass
                print(
                    f"[Realtime] Account={acct_id} user={me_name} dialogs={len(dialog_ids)} "
                    f"configured_targets={len(chats_filter)}"
                )
                # Lightweight, rate-limited stats (once per 60s)
                stats: dict[str, Any] = {
                    "received": 0,
                    "published": 0,
                    "failed": 0,
                    "last_event": None,
                }

                async def _stats_reporter() -> None:
                    while True:
                        try:
                            await asyncio.sleep(60)
                            rcv = stats.get("received", 0)
                            pub = stats.get("published", 0)
                            fail = stats.get("failed", 0)
                            last = stats.get("last_event")
                            print(
                                f"[Realtime] stats: received={rcv} published={pub} failed={fail} last={last} "
                                f"(allowed={len(allowed_ids)})"
                            )
                            stats["received"] = 0
                            stats["published"] = 0
                            stats["failed"] = 0
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            # Do not spam on stats errors; continue
                            pass

                async def _refresh_allowed() -> None:
                    nonlocal allowed_ids
                    try:
                        new_allowed = await store.get_allowed_for_account(acct_id)
                        if new_allowed != allowed_ids:
                            old_set = allowed_ids
                            old_count = len(old_set)
                            allowed_ids = new_allowed
                            added = sorted(list(allowed_ids - old_set))
                            removed = sorted(list(old_set - allowed_ids))
                            def _sample(lst: list[int], limit: int = 5) -> list[str]:
                                out = []
                                for cid in lst[:limit]:
                                    name = dialog_titles.get(cid, str(cid))
                                    out.append(f"{cid}:{name}")
                                return out
                            joined_allowed = allowed_ids & dialog_ids if dialog_ids else allowed_ids
                            print(
                                f"[Realtime] Assignment updated: {old_count} -> {len(allowed_ids)} channels; "
                                f"joined_now={len(joined_allowed)}; "
                                f"add={len(added)} remove={len(removed)}; "
                                f"samples add={_sample(added)} remove={_sample(removed)}"
                            )
                    except Exception as e:  # noqa: BLE001
                        print(f"[Realtime] Failed to refresh assignment: {e}")

                async def _assignment_listener() -> None:
                    """
                    Subscribe to Redis pub/sub notification to refresh assignment immediately on changes.
                    """
                    await _refresh_allowed()
                    channel = f"{settings.realtime_assignment_redis_prefix}notify"
                    pubsub = redis.pubsub()
                    try:
                        await pubsub.subscribe(channel)
                        print(f"[Realtime] Subscribed to assignment notifications on '{channel}'")
                        while True:
                            try:
                                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
                                if message:
                                    await _refresh_allowed()
                            except asyncio.CancelledError:
                                raise
                            except Exception:
                                # swallow and continue listening
                                await asyncio.sleep(1)
                    finally:
                        try:
                            await pubsub.aclose()
                        except Exception:
                            pass

                stats_task = asyncio.create_task(_stats_reporter())
                listener_task = asyncio.create_task(_assignment_listener())

                @client.on(events.NewMessage())
                async def _handler(event: Any) -> None:
                    try:
                        cid = int(event.chat_id) if event.chat_id is not None else None
                        if allowed_ids:
                            if cid is None or cid not in allowed_ids:
                                return
                            stats["received"] = int(stats.get("received", 0)) + 1
                            stats["last_event"] = {
                                "chat_id": int(event.chat_id) if event.chat_id is not None else None,
                                "message_id": int(event.message.id),
                            }
                            # Best-effort usernames without extra network calls:
                            # Telethon sets .sender/.chat when available in the update; we do NOT call get_*()
                            sender_username = None
                            chat_username = None
                            try:
                                su = getattr(getattr(event.message, "sender", None), "username", None)
                                if isinstance(su, str) and su:
                                    sender_username = su if su.startswith("@") else f"@{su}"
                            except Exception:
                                sender_username = None
                            try:
                                cu = getattr(getattr(event.message, "chat", None), "username", None)
                                if isinstance(cu, str) and cu:
                                    chat_username = cu if cu.startswith("@") else f"@{cu}"
                            except Exception:
                                chat_username = None
                            payload = {
                                "event": "NewMessage",
                                "chat_id": int(event.chat_id) if event.chat_id is not None else None,
                                "message_id": int(event.message.id),
                                "message": event.message.to_dict(),
                                "sender_username": sender_username,
                                "chat_username": chat_username,
                            }
                            await _publish_message(exchange, payload)
                            stats["published"] = int(stats.get("published", 0)) + 1
                    except Exception as e:  # noqa: BLE001
                        stats["failed"] = int(stats.get("failed", 0)) + 1
                        print(f"[Handler] Failed to publish message: {e}")

                try:
                    await client.run_until_disconnected()
                finally:
                    try:
                        stats_task.cancel()
                        listener_task.cancel()
                    except Exception:
                        pass
            print("[Realtime] Client disconnected gracefully. Restarting in 10s.")
            await asyncio.sleep(10)

        except (AuthKeyUnregisteredError, SessionExpiredError) as e:
            print(f"[Realtime] CRITICAL: Session invalid or expired: {e}. Sleeping 1h.")
            await asyncio.sleep(3600)
            break  # Let the container orchestrator restart us
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[Realtime] Unhandled error: {e}. Retrying in 30s.")
            await asyncio.sleep(30)
        finally:
            if client is not None and client.is_connected():
                try:
                    await client.disconnect()
                except Exception:
                    pass
            if amqp_connection is not None:
                try:
                    await amqp_connection.close()
                except Exception:
                    pass
            try:
                await redis.aclose()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(run_realtime_worker())

