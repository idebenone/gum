
"""Database initialization for the API layer.

This module contains helper functions for Postgres full-text search.
Database models are in: user.py, observation.py, proposition.py
"""

from __future__ import annotations

import pathlib
from typing import Optional

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from .base import Base



# Postgres FTS helpers
from sqlalchemy import Column, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select

def fts_search_propositions(session, search_text):
    from .proposition import Proposition
    # Use to_tsvector and plainto_tsquery for FTS
    stmt = select(Proposition).where(
        func.to_tsvector('english', Proposition.text + ' ' + Proposition.reasoning).match(func.plainto_tsquery('english', search_text))
    )
    return session.execute(stmt).scalars().all()

def fts_search_observations(session, search_text):
    from .observation import Observation
    stmt = select(Observation).where(
        func.to_tsvector('english', Observation.content + ' ' + Observation.observer_name).match(func.plainto_tsquery('english', search_text))
    )
    return session.execute(stmt).scalars().all()
