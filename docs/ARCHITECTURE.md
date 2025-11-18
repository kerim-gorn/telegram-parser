## Architecture (Draft)

- Producer: FastAPI service (`app/`) schedules jobs into RabbitMQ via Celery.
- Queue: RabbitMQ.
- Consumers:
  - Historical worker (`workers/historical_worker.py`): ephemeral Celery task parses chat history.
  - Realtime worker (`workers/realtime_worker.py`): persistent Telethon listener pushes new messages to queue.
- Storage:
  - Postgres (SQLAlchemy + Alembic) for parsed data.
  - Redis for Telethon StringSession and Celery result backend.

Key principles:
- Stateless workers; sessions stored in Redis (`StringSession` only).
- Async I/O for Telegram, DB, and Redis.
- Config from environment variables (`core/config.py`).


