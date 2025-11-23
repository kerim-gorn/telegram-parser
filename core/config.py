from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: str = Field("development", alias="APP_ENV")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    api_port: int = Field(8000, alias="API_PORT")

    # Telegram
    telegram_api_id: int = Field(..., alias="TELEGRAM_API_ID")
    telegram_api_hash: str = Field(..., alias="TELEGRAM_API_HASH")
    telegram_account_id: str = Field("default", alias="TELEGRAM_ACCOUNT_ID")
    telegram_session_prefix: str = Field("telegram:sessions:", alias="TELEGRAM_SESSION_PREFIX")
    # Notifier (signals)
    signals_channel: str = Field("", alias="SIGNALS_CHANNEL")
    signals_account_id: str | None = Field(default=None, alias="SIGNALS_ACCOUNT_ID")
    # Realtime worker configuration
    realtime_chats_raw: str = Field("", alias="CHATS_TO_LISTEN")
    realtime_exchange_name: str = Field("realtime_fanout", alias="REALTIME_EXCHANGE")
    historical_exchange_name: str = Field("historical_fanout", alias="HISTORICAL_EXCHANGE")
    backfill_via_rabbit: bool = Field(True, alias="BACKFILL_VIA_RABBIT")
    # Realtime dynamic assignment
    # Список аккаунтов (через запятую), которые участвуют в realtime-парсинге и между которыми мы распределяем каналы.
    realtime_accounts_raw: str = Field("", alias="REALTIME_ACCOUNTS")
    # Период перераспределения в секундах (более информативный параметр; фактический запуск делает Celery Beat — по умолчанию ежечасно).
    realtime_assignment_tick_seconds: int = Field(3600, alias="REALTIME_ASSIGNMENT_TICK_SECONDS")
    # Префикс ключей в Redis для хранения назначения: rt:assign:{account_id} -> set(channel_ids).
    realtime_assignment_redis_prefix: str = Field("rt:assign:", alias="REALTIME_ASSIGNMENT_REDIS_PREFIX")
    # Базовая емкость аккаунта (в условных единицах нагрузки сообщений/мин). None — без жесткого лимита, балансируем только по весам.
    realtime_account_capacity_default: float | None = Field(None, alias="REALTIME_ACCOUNT_CAPACITY_DEFAULT")
    # Weight model
    # Доля краткосрочной активности (последние 15 минут) в итоговом весе: w = α*r15 + (1-α)*r24.
    weight_alpha: float = Field(0.7, alias="WEIGHT_ALPHA")
    # Минимальный вес канала (чтобы совсем неактивные каналы не «обнулялись» и участвовали в распределении).
    weight_min: float = Field(0.05, alias="WEIGHT_MIN")

    # Database
    postgres_host: str = Field("postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, alias="POSTGRES_PORT")
    postgres_db: str = Field("telegram_parser", alias="POSTGRES_DB")
    postgres_user: str = Field("postgres", alias="POSTGRES_USER")
    postgres_password: str = Field("postgres", alias="POSTGRES_PASSWORD")
    database_url: str = Field(..., alias="DATABASE_URL")

    # RabbitMQ / Celery
    rabbitmq_host: str = Field("rabbitmq", alias="RABBITMQ_HOST")
    rabbitmq_port: int = Field(5672, alias="RABBITMQ_PORT")
    rabbitmq_user: str = Field("guest", alias="RABBITMQ_DEFAULT_USER")
    rabbitmq_pass: str = Field("guest", alias="RABBITMQ_DEFAULT_PASS")
    celery_broker_url: str = Field(..., alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(..., alias="CELERY_RESULT_BACKEND")
    # Periodic schedule configuration (comma-separated lists)
    scheduled_chats_raw: str = Field("", alias="SCHEDULED_CHATS")
    scheduled_accounts_raw: str = Field("", alias="SCHEDULED_ACCOUNTS")
    scheduled_history_days: int = Field(7, alias="SCHEDULED_HISTORY_DAYS")

    # Redis
    redis_url: str = Field(..., alias="REDIS_URL")

    # Encryption
    session_crypto_key: str | None = Field(default=None, alias="SESSION_CRYPTO_KEY")

    # Demo / testing
    test_public_chat_id: int | None = Field(default=None, alias="TEST_PUBLIC_CHAT_ID")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()


