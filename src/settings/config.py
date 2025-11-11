from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Telegram API
    telegram_api_id: int = Field(..., env="TELEGRAM_API_ID")
    telegram_api_hash: str = Field(..., env="TELEGRAM_API_HASH")
    
    # PostgreSQL
    postgres_user: str = Field(default="postgres", env="POSTGRES_USER")
    postgres_password: str = Field(default="postgres", env="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="parser_llm", env="POSTGRES_DB")
    postgres_host: str = Field(default="postgres", env="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, env="POSTGRES_PORT")
    
    @property
    def database_url(self) -> str:
        """Construct database URL."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    # RabbitMQ
    rabbitmq_user: str = Field(default="guest", env="RABBITMQ_USER")
    rabbitmq_password: str = Field(default="guest", env="RABBITMQ_PASSWORD")
    rabbitmq_host: str = Field(default="rabbitmq", env="RABBITMQ_HOST")
    rabbitmq_port: int = Field(default=5672, env="RABBITMQ_PORT")
    rabbitmq_management_port: int = Field(default=15672, env="RABBITMQ_MANAGEMENT_PORT")
    
    @property
    def celery_broker_url(self) -> str:
        """Construct Celery broker URL."""
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}//"
        )
    
    # Redis
    redis_host: str = Field(default="redis", env="REDIS_HOST")
    redis_port: int = Field(default=6379, env="REDIS_PORT")
    redis_password: str = Field(default="redis", env="REDIS_PASSWORD")
    redis_db: int = Field(default=0, env="REDIS_DB")
    
    @property
    def redis_url(self) -> str:
        """Construct Redis URL."""
        return (
            f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        )
    
    @property
    def celery_result_backend(self) -> str:
        """Construct Celery result backend URL."""
        return (
            f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        )
    
    # Application
    app_env: str = Field(default="development", env="APP_ENV")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    # Parser settings
    parser_chat_ids: Optional[str] = Field(default=None, env="PARSER_CHAT_IDS")
    
    @property
    def chat_ids_list(self) -> List[int]:
        """Parse chat IDs from comma-separated string."""
        if not self.parser_chat_ids:
            return []
        return [int(chat_id.strip()) for chat_id in self.parser_chat_ids.split(",") if chat_id.strip()]
    
    # Anti-Ban settings
    flood_wait_max_retries: int = Field(default=5, env="FLOOD_WAIT_MAX_RETRIES")
    flood_wait_base_delay: float = Field(default=1.0, env="FLOOD_WAIT_BASE_DELAY")
    flood_wait_max_delay: float = Field(default=300.0, env="FLOOD_WAIT_MAX_DELAY")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
