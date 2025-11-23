from __future__ import annotations

import json
from typing import Dict, Iterable, Optional, Set

from redis.asyncio import Redis

from app.assignment import Assignment


class AssignmentStore:
    """
    Redis-backed storage for realtime channel assignments per account.
    """

    def __init__(self, redis: Redis, key_prefix: str = "rt:assign:") -> None:
        self._redis = redis
        self._key_prefix = key_prefix.rstrip(":") + ":"

    def _set_key(self, account_id: str) -> str:
        return f"{self._key_prefix}{account_id}"

    def _meta_key(self) -> str:
        return f"{self._key_prefix}meta"

    async def read_all(self, accounts: Iterable[str]) -> Assignment:
        out: Assignment = {}
        for a in accounts:
            members = await self._redis.smembers(self._set_key(a))
            # smembers may return str; ensure int conversion where possible
            chans: Set[int] = set()
            for m in members:
                try:
                    chans.add(int(m))
                except (TypeError, ValueError):
                    continue
            out[a] = chans
        return out

    async def write_all(self, assignment: Assignment, summary: Optional[str] = None) -> None:
        # store sets atomically via pipeline
        async with self._redis.pipeline(transaction=True) as pipe:
            # delete old sets and write new ones
            for a, chans in assignment.items():
                key = self._set_key(a)
                await pipe.delete(key)
                if chans:
                    await pipe.sadd(key, *[int(c) for c in chans])
            # bump version and store last_summary for observability
            meta_key = self._meta_key()
            await pipe.hincrby(meta_key, "version", 1)
            if summary:
                await pipe.hset(meta_key, "last_summary", summary)
            await pipe.execute()
        # publish lightweight notification for realtime workers to refresh
        try:
            channel = f"{self._key_prefix}notify"
            await self._redis.publish(channel, "updated")
        except Exception:
            # best-effort notify; workers still fall back to initial refresh on start
            pass

    async def get_allowed_for_account(self, account_id: str) -> Set[int]:
        members = await self._redis.smembers(self._set_key(account_id))
        out: Set[int] = set()
        for m in members:
            try:
                out.add(int(m))
            except (TypeError, ValueError):
                continue
        return out

    async def read_last_summary(self) -> Optional[str]:
        val = await self._redis.hget(self._meta_key(), "last_summary")
        return str(val) if val is not None else None


