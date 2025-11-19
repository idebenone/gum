from __future__ import annotations

from typing import Optional
import pathlib
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from ..models import Base, create_fts_table, create_observations_fts


async def init_db(
    db_path: str = "gum.db",
    db_directory: Optional[str] = None,
):
    """Create the SQLite file, ORM tables & FTS5 index (first run only)."""
    if db_directory:
        path = pathlib.Path(db_directory).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        db_path = str(path / db_path)

    engine: AsyncEngine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        future=True,
        connect_args={
            "timeout": 30,
            "isolation_level": None,
        },
        poolclass=None,
    )

    async with engine.begin() as conn:
        await conn.execute(sql_text("PRAGMA journal_mode=WAL"))
        await conn.execute(sql_text("PRAGMA busy_timeout=30000"))

        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(create_fts_table)
        await conn.run_sync(create_observations_fts)

    Session = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )
    return engine, Session
