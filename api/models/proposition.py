from typing import Optional, TYPE_CHECKING
from sqlalchemy import (
    DateTime,
    String,
    Text,
    Integer,
    ForeignKey,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)
from sqlalchemy.sql import func
from .base import Base, observation_proposition

if TYPE_CHECKING:
    from .observation import Observation

class Proposition(Base):
    """Represents a proposition about user behavior."""
    __tablename__ = "propositions"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    confidence: Mapped[Optional[int]]
    decay: Mapped[Optional[int]]

    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    revision_group: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)

    observations: Mapped[set["Observation"]] = relationship(
        "Observation",
        secondary=observation_proposition,
        back_populates="propositions",
        collection_class=set,
        passive_deletes=True,
        lazy="selectin",
    )  # type: ignore

    def __repr__(self) -> str:
        preview = (self.text[:27] + "…") if len(self.text) > 30 else self.text
        return f"<Proposition(id={self.id}, text={preview})>"

