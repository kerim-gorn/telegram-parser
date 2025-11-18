from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from core.config import settings

# Global engine/session factory (OK for web app single-loop use)
engine: AsyncEngine = create_async_engine(settings.database_url, future=True)
async_session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """
    FastAPI-style dependency to yield an AsyncSession.
    """
    async with async_session_factory() as session:
        yield session


def create_loop_bound_session_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """
    Creates a new AsyncEngine and session factory bound to the CURRENT event loop.
    Use this in asyncio.run() contexts (e.g., Celery tasks) to avoid cross-loop issues.
    Caller is responsible for disposing the engine.
    """
    loop_engine: AsyncEngine = create_async_engine(
        settings.database_url,
        future=True,
        poolclass=NullPool,
    )
    loop_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=loop_engine, expire_on_commit=False, class_=AsyncSession
    )
    return loop_engine, loop_session_factory


