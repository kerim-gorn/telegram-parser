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
    chats_filter: list[Union[int, str]] = _parse_chats(settings.realtime_chats_raw)

    session_manager = SessionManager(
        settings.redis_url,
        settings.telegram_session_prefix,
        settings.session_crypto_key,
    )
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    store = AssignmentStore(redis, key_prefix=settings.realtime_assignment_redis_prefix)
    allowed_ids: Set[int] = set()

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
                            print(f"[Realtime] stats: received={rcv} published={pub} failed={fail} last={last}")
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
                            old_count = len(allowed_ids)
                            allowed_ids = new_allowed
                            print(
                                f"[Realtime] Assignment updated: {old_count} -> {len(allowed_ids)} channels "
                                f"for account {acct_id}"
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
                        payload = {
                            "event": "NewMessage",
                            "chat_id": int(event.chat_id) if event.chat_id is not None else None,
                            "message_id": int(event.message.id),
                            "message": event.message.to_dict(),
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

