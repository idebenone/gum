from __future__ import annotations

from typing import Optional
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from ..models import Base


async def init_db(
    db_url: Optional[str] = None,
):
    """Create the Postgres database tables (first run only)."""
    if db_url is None:
        db_url = "postgresql+asyncpg://postgres:root@localhost:5432/gum"

    engine: AsyncEngine = create_async_engine(
        db_url,
        future=True,
        echo=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )
    return engine, Session
