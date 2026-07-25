"""SQLAlchemy async unit-of-work — doc 11 §3.

`make_engine` accepts any SQLAlchemy async URL: `postgresql+asyncpg://...` in
prod/compose, `sqlite+aiosqlite:///:memory:` for fast unit tests that don't
need a real Postgres (contract tests against testcontainers-postgres are
separate and exercise the real driver/RLS behavior).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def make_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    return create_async_engine(database_url, echo=echo, pool_pre_ping=True)


class UnitOfWork:
    """Callable factory: `async with uow() as session: ...` per doc 11 §3's
    `async with uow() as u:` tool pattern."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    @contextlib.asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        async with self._sessionmaker() as session, session.begin():
            yield session
