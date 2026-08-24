"""Async engine/session factory."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mirza.core.settings import get_settings


def make_engine():
    s = get_settings()
    return create_async_engine(s.db.url, echo=s.debug, pool_pre_ping=True)


def make_sessionmaker(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_models(engine) -> None:
    """Dev/boot convenience: create tables from metadata.
    Production path is Alembic (see migrations/)."""
    from mirza.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
