from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.settings.config import settings


def create_engine() -> AsyncEngine:
    return create_async_engine(settings.postgres.async_url, pool_pre_ping=True)
