"""Database initialization for the API layer.

This module contains the database initialization function and FTS table setup.
Database models are in: user.py, observation.py, proposition.py
"""

from __future__ import annotations

import pathlib
from typing import Optional

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from .base import Base

FTS_TOKENIZER = "porter ascii"


def create_fts_table(conn) -> None:
    """Create FTS5 virtual table and triggers for proposition search."""
    exists = conn.execute(
        sql_text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='propositions_fts'"
        )
    ).fetchone()
    if exists:
        return

    conn.execute(
        sql_text(
            f"""
            CREATE VIRTUAL TABLE propositions_fts
            USING fts5(
                text,
                reasoning,
                content='propositions',
                content_rowid='id',
                tokenize='{FTS_TOKENIZER}'
            );
        """
        )
    )
    conn.execute(
        sql_text(
            """
            CREATE TRIGGER propositions_ai
            AFTER INSERT ON propositions BEGIN
                INSERT INTO propositions_fts(rowid, text, reasoning)
                VALUES (new.id, new.text, new.reasoning);
            END;
        """
        )
    )
    conn.execute(
        sql_text(
            """
            CREATE TRIGGER propositions_ad
            AFTER DELETE ON propositions BEGIN
                DELETE FROM propositions_fts WHERE rowid = old.id;
            END;
        """
        )
    )
    conn.execute(
        sql_text(
            """
            CREATE TRIGGER propositions_au
            AFTER UPDATE ON propositions BEGIN
                DELETE FROM propositions_fts WHERE rowid = old.id;
                INSERT INTO propositions_fts(rowid, text, reasoning)
                VALUES (new.id, new.text, new.reasoning);
            END;
        """
        )
    )


def create_observations_fts(conn) -> None:
    """Create FTS5 virtual table and triggers for observation search."""
    exists = conn.execute(
        sql_text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='observations_fts'"
        )
    ).fetchone()
    if exists:
        return

    conn.execute(
        sql_text(
            f"""
            CREATE VIRTUAL TABLE observations_fts
            USING fts5(
                content,
                observer_name,
                content='observations',
                content_rowid='id',
                tokenize='{FTS_TOKENIZER}'
            );
        """
        )
    )
    conn.execute(
        sql_text(
            """
            CREATE TRIGGER observations_ai
            AFTER INSERT ON observations BEGIN
                INSERT INTO observations_fts(rowid, content, observer_name)
                VALUES (new.id, new.content, new.observer_name);
            END;
        """
        )
    )
    conn.execute(
        sql_text(
            """
            CREATE TRIGGER observations_ad
            AFTER DELETE ON observations BEGIN
                DELETE FROM observations_fts WHERE rowid = old.id;
            END;
        """
        )
    )
    conn.execute(
        sql_text(
            """
            CREATE TRIGGER observations_au
            AFTER UPDATE ON observations BEGIN
                DELETE FROM observations_fts WHERE rowid = old.id;
                INSERT INTO observations_fts(rowid, content, observer_name)
                VALUES (new.id, new.content, new.observer_name);
            END;
        """
        )
    )
