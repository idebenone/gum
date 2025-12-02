from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import (
    Table,
    Column,
    Integer,
    ForeignKey,
)

class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all database models."""
    pass


# Junction table for many-to-many relationship between observations and propositions
observation_proposition = Table(
    "observation_proposition",
    Base.metadata,
    Column(
        "observation_id",
        Integer,
        ForeignKey("observations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "proposition_id",
        Integer,
        ForeignKey("propositions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
