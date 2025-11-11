from __future__ import annotations

from dataclasses import dataclass
import os


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class PostgresSettings:
    host: str = _env("POSTGRES_HOST", "postgres")
    port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    db: str = _env("POSTGRES_DB", "parser_llm")
    user: str = _env("POSTGRES_USER", "parser_llm")
    password: str = _env("POSTGRES_PASSWORD", "parser_llm_password")
    url_override: str = _env("DATABASE_URL", "")

    @property
    def async_url(self) -> str:
        if self.url_override:
            return self.url_override
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db}"
        )


@dataclass(frozen=True)
class RedisSettings:
    host: str = _env("REDIS_HOST", "redis")
    port: int = int(os.getenv("REDIS_PORT", "6379"))
    db: int = int(os.getenv("REDIS_DB", "0"))
    password: str = _env("REDIS_PASSWORD", "redis_password")
    url_override: str = _env("REDIS_URL", "")

    @property
    def url(self) -> str:
        if self.url_override:
            return self.url_override
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


@dataclass(frozen=True)
class RabbitMQSettings:
    host: str = _env("RABBITMQ_HOST", "rabbitmq")
    port: int = int(os.getenv("RABBITMQ_PORT", "5672"))
    user: str = _env("RABBITMQ_USER", "parser_llm")
    password: str = _env("RABBITMQ_PASSWORD", "rabbitmq_password")
    vhost: str = _env("RABBITMQ_VHOST", "/")
    amqp_url_override: str = _env("AMQP_URL", "")

    @property
    def amqp_url(self) -> str:
        if self.amqp_url_override:
            return self.amqp_url_override
        return f"amqp://{self.user}:{self.password}@{self.host}:{self.port}/{self.vhost}"


@dataclass(frozen=True)
class TelegramApiSettings:
    api_id: int = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash: str = _env("TELEGRAM_API_HASH", "")
    app_title: str = _env("TELEGRAM_APP_TITLE", "Parser-LLM")
    session_secret_key: str = _env("SESSION_SECRET_KEY", "")
    session_redis_prefix: str = _env("SESSION_REDIS_PREFIX", "telegram_session:")


@dataclass(frozen=True)
class CelerySettings:
    broker_url: str = _env("CELERY_BROKER_URL", "")
    result_backend: str = _env("CELERY_RESULT_BACKEND", "")


@dataclass(frozen=True)
class AppSettings:
    timezone: str = _env("TIMEZONE", "UTC")


@dataclass(frozen=True)
class Settings:
    postgres: PostgresSettings = PostgresSettings()
    redis: RedisSettings = RedisSettings()
    rabbitmq: RabbitMQSettings = RabbitMQSettings()
    telegram: TelegramApiSettings = TelegramApiSettings()
    celery: CelerySettings = CelerySettings()
    app: AppSettings = AppSettings()


settings = Settings()
