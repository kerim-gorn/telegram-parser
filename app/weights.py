from __future__ import annotations

from typing import Dict

from sqlalchemy import text

from db.session import create_loop_bound_session_factory


async def compute_channel_weights(alpha: float = 0.7, min_weight: float = 0.05) -> Dict[int, float]:
    """
    Compute per-channel weights as blended short/long activity rates:
      r15 = msgs per minute over last 15 minutes (excluding likely backfill)
      r24 = msgs per minute over last 24 hours
      w = alpha * r15 + (1 - alpha) * r24, floored at min_weight
    """
    sql = text(
        """
        SELECT
          chat_id,
          COUNT(*) FILTER (
            WHERE message_date >= now() - interval '15 minutes'
              AND (indexed_at - message_date) <= interval '5 minutes'
          )::float / 15.0 AS r15,
          COUNT(*) FILTER (
            WHERE message_date >= now() - interval '24 hours'
          )::float / 1440.0 AS r24
        FROM messages
        GROUP BY chat_id
        """
    )
    engine, _ = create_loop_bound_session_factory()
    try:
        async with engine.begin() as conn:
            rows = (await conn.execute(sql)).mappings().all()
        weights: Dict[int, float] = {}
        for row in rows:
            r15 = float(row.get("r15") or 0.0)
            r24 = float(row.get("r24") or 0.0)
            w = alpha * r15 + (1.0 - alpha) * r24
            cid = int(row["chat_id"])
            weights[cid] = max(w, float(min_weight))
        return weights
    finally:
        await engine.dispose()


