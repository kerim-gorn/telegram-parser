# Telegram Parser (Realtime Assignment)

This project ingests Telegram messages using Telethon and a Producer–Queue–Consumer architecture (RabbitMQ, Celery, PostgreSQL). Realtime parsing is balanced across multiple Telegram accounts using Redis-based assignments with pub/sub updates (no restarts on redistribution).

## Prerequisites

- Docker + Docker Compose
- Python 3.11 (for onboarding and helper scripts)
- A `.env` file based on the example below

## Environment (.env)

Copy this as `.env` and adjust values:

```bash
APP_ENV=development
LOG_LEVEL=INFO
API_PORT=8000

TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash_here
# Bot-based signals (aiogram)
TELEGRAM_BOT_TOKEN=your_bot_token_here
SIGNALS_BOT_CHAT_ID=-1001234567890

TELEGRAM_ACCOUNT_ID=default
TELEGRAM_SESSION_PREFIX=telegram:sessions:
SESSION_CRYPTO_KEY=your_fernet_key

REALTIME_CONFIG_JSON=realtime_config.json

REALTIME_EXCHANGE=realtime_fanout
HISTORICAL_EXCHANGE=historical_fanout
BACKFILL_VIA_RABBIT=true

WEIGHT_ALPHA=0.7
WEIGHT_MIN=0.05

POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=telegram_parser
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/telegram_parser

RABBITMQ_DEFAULT_USER=guest
RABBITMQ_DEFAULT_PASS=guest
RABBITMQ_PORT=5672
CELERY_BROKER_URL=amqp://guest:guest@rabbitmq:5672//
CELERY_RESULT_BACKEND=redis://redis:6379/1

# Ingestor prefilter (optional)
PREFILTER_CONFIG_JSON=/prefilter_rules.json
PREFILTER_RELOAD_SECONDS=60

SCHEDULED_CHATS=
SCHEDULED_ACCOUNTS=
SCHEDULED_HISTORY_DAYS=7

REDIS_URL=redis://redis:6379/0
```

Notes:

- `REALTIME_CONFIG_JSON` points to a unified JSON config for accounts and chats.
- Realtime assignment uses Redis pub/sub, so redistribution applies instantly without restarts.

## Message Classification Schema

The ingestor processes messages in batches (50 messages at a time) and uses an advanced LLM classification schema with the following fields:

### Classification Fields

- **intents** (ARRAY[String]): List of detected user intentions:
  - `REQUEST`: User is looking for a product/service/info (potential lead)
  - `OFFER`: User is offering a product or service
  - `RECOMMENDATION`: User recommends a specific performer/place
  - `COMPLAINT`: Negative feedback or complaint about a problem
  - `INFO`: Neutral information sharing
  - `OTHER`: Greetings, emojis without text, meaningless phrases

- **domains** (JSONB): Array of domain objects with subcategories:
  - `CONSTRUCTION_AND_REPAIR`: `MAJOR_RENOVATION`, `REPAIR_SERVICES`
  - `RENTAL_OF_REAL_ESTATE`: `RENTAL_APARTMENT`, `RENTAL_HOUSE`, `RENTAL_PARKING`, `RENTAL_STORAGE`, `RENTAL_LAND`
  - `PURCHASE_OF_REAL_ESTATE`: `PURCHASE_APARTMENT`, `PURCHASE_HOUSE`, `PURCHASE_PARKING`, `PURCHASE_STORAGE`, `PURCHASE_LAND`
  - `SERVICES`: `BEAUTY_AND_HEALTH`, `HOUSEHOLD_SERVICES`, `CHILD_CARE_AND_EDUCATION`, `AUTO_SERVICES`, `DELIVERY_SERVICES`, `TECH_REPAIR`
  - `MARKETPLACE`: `BUY_SELL_GOODS`, `GIVE_AWAY`, `HOMEMADE_FOOD`, `BUYER_SERVICES`
  - `SOCIAL_CAPITAL`: `PARENTING`, `HOBBY_AND_SPORT`, `EVENTS`
  - `OPERATIONAL_MANAGEMENT`: `LOST_AND_FOUND`, `SECURITY`, `LIVING_ENVIRONMENT`, `MANAGEMENT_COMPANY_INTERACTION`
  - `REPUTATION`: `PERSONAL_BRAND`, `COMPANIES_REPUTATION`
  - `NONE`: No suitable domain found

- **urgency_score** (Integer, 1-5, indexed):
  - `5`: Emergency (fire, flood, fight, immediate danger)
  - `4`: Urgent problem requiring quick attention (elevator stuck, no water)
  - `3`: Standard problem/question
  - `1-2`: Non-urgent info/chatter

- **is_spam** (Boolean, indexed): True if message has signs of mass mailing, excessive emojis, external links, or is clearly not from a resident

- **reasoning** (Text): Brief explanation of the classification (max 1 sentence)

### Signal Detection

A message is considered a signal (and triggers notification) if:
- It has `REQUEST` intent AND
- It belongs to `CONSTRUCTION_AND_REPAIR` or `SERVICES` domains

## Ingestor Prefilter (skip/force before LLM)

- You can prefilter messages by substrings and regexes to:
  - force a message as signal (skip LLM): Messages matching `force` rules are classified with `REQUEST` intent and `CONSTRUCTION_AND_REPAIR` domain
  - skip a message as non-signal (skip LLM): Messages matching `skip` rules are classified with `OTHER` intent and `NONE` domain
- Configure with `PREFILTER_CONFIG_JSON` pointing to a JSON file. The file is hot-reloaded every `PREFILTER_RELOAD_SECONDS` seconds.
- Prefilter is applied **before** batch formation to avoid unnecessary LLM calls.

Example `prefilter_rules.json`:

```json
{
  "substrings": [
    { "pattern": "продам", "ignore_case": true, "action": "skip" },
    { "pattern": "срочно нужен электрик", "ignore_case": true, "action": "force" }
  ],
  "regexes": [
    { "pattern": "(?i)\\bищу мастера\\b", "action": "force" },
    { "pattern": "(?i)\\bакция\\b",          "action": "skip" }
  ]
}
```

Behavior on match:

- action `force`: Classified with `REQUEST` intent, `CONSTRUCTION_AND_REPAIR` domain, `urgency_score=3`, `reasoning` includes matched patterns
- action `skip`: Classified with `OTHER` intent, `NONE` domain, `urgency_score=1`, `reasoning` includes matched patterns
- Precedence: if both force and skip rules match, force wins.
- Prefilter results are stored in `llm_analysis` JSONB field with `forced: true` or `filtered: true` flags.

Notes:

- `matched` contains the patterns that triggered a decision.
- Messages filtered by prefilter are excluded from LLM batch processing to save costs.

## Batch Processing

The ingestor processes messages in batches:
- **Batch size**: 50 messages
- **Batch timeout**: 5 seconds (messages are processed when batch is full or timeout expires)
- Messages are accumulated in a buffer until batch size or timeout is reached
- Prefilter is applied before batch formation (forced/skipped messages are excluded from LLM calls)
- All messages in a batch are sent to LLM in a single API call using structured JSON schema

## Signal Notifications (via Telegram Bot)

- Signals are sent using a Telegram Bot (aiogram), not a user session.
- A message is considered a signal if it has `REQUEST` intent and belongs to `CONSTRUCTION_AND_REPAIR` or `SERVICES` domains.
- Required env variables:
  - `TELEGRAM_BOT_TOKEN` — Bot API token from BotFather
  - `SIGNALS_BOT_CHAT_ID` — chat id (e.g. `-100...`) or user id where the bot will post
- The message includes:
  - channel username, author username, message timestamp (UTC), and the original text
  - a deep link to the original post when channel username and message id are available

Quick smoke test (after setting env and installing requirements):

```bash
python scripts/notify_smoke_test.py --text "Test signal ✅"
```

## Realtime Config (accounts + chats)

Create `realtime_config.json` in the repo root:

```json
{
  "accounts": [
    { "account_id": "acc1", "phone": "+10000000001", "twofa": null },
    { "account_id": "acc2", "phone": "+10000000002", "twofa": null }
  ],
  "chats": [
    "@durov",
    "t.me/durov2",
    -1001234567890
  ]
}
```

- Supported chat formats: `@username`, `https://t.me/username`, `https://t.me/c/<internal_id>`, and numeric `-100...` ids.

### Realtime assignment uses numeric chat_id only

- For realtime distribution and parsing, only numeric `chat_id` entries from `realtime_config.json` are considered.  
  Items that have only an `identifier` (e.g. `@username` or `t.me/...`) are ignored until a numeric `chat_id` is present.
- To populate `chat_id` safely (without network resolves and without any auto-join), use membership-based filling:

```bash
python -m scripts.update_config_chat_ids --all-accounts --delay-min 0 --delay-max 0 --log-level INFO
```

- Redistribution does not call `get_entity` and never accepts invites or joins chats. It only assigns channels where each account is already a member (based on dialogs).

## Onboard Accounts (StringSession to Redis)

Run locally (not in container), it will process all accounts from `realtime_config.json` (or fallback to `accounts.json`):

```bash
python scripts/onboard_account.py
```

It stores encrypted `StringSession` in Redis keys: `telegram:sessions:{account_id}`.

## Build and Start Core Services

```bash
docker compose build
docker compose up -d postgres rabbitmq redis
# optional: apply DB migrations from inside API container
docker compose exec api alembic upgrade head
docker compose up -d api worker ingestor beat
```

The compose mounts `realtime_config.json` into `beat` and the base `realtime` service.

## Generate Realtime Services (one per account)

Generate a compose file with one realtime service per `account_id`:

```bash
python scripts/generate_realtime_compose.py
```

Then bring them up using the generated file alongside the base compose:

```bash
docker compose -f docker-compose.yml -f docker-compose.realtime.generated.yml up -d --remove-orphans
```

You can re-run the generator after changing `realtime_config.json`; the `up -d --remove-orphans` command will add/remove containers accordingly.

Note: the base `realtime` service in `docker-compose.yml` is put under the `manual` profile and won't start by default. This prevents duplication with the per-account realtime services. If you accidentally started it earlier, stop and remove it:

```bash
docker compose stop realtime || true
docker compose rm -f realtime || true
```

## Trigger Redistribution Now (optional)

By default, redistribution runs hourly. To apply immediately:

```bash
docker compose exec worker celery -A workers.celery_app.celery_app call workers.beat_tasks.reassign_realtime
```

Realtime workers will refresh assignments instantly via Redis pub/sub.

## Observability (Logs)

- Beat (assignment summary):

```bash
docker compose logs -f beat | egrep "Assign|coverage|imbalance"
```

- Realtime (per account container names are generated by the script):

```bash
docker compose logs -f telegram_parser_realtime_acc1 | egrep "Account=|Subscribed|Assignment updated|stats"
```

You will see:

- Account identity and dialog count on startup
- Pub/sub subscription notice
- Assignment updates with add/remove samples and counts
- Periodic stats including `(allowed=N)`

## Updating Accounts or Chats

1) Edit `realtime_config.json`.
2) Re-run:
   - `python scripts/generate_realtime_compose.py`
   - `docker compose -f docker-compose.yml -f docker-compose.realtime.generated.yml up -d --remove-orphans`
3) (Optional) Trigger redistribution as above.

No restarts are required for redistribution itself; workers refresh allowed channels immediately.

