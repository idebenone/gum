from typing import TYPE_CHECKING
from sqlalchemy import (
    DateTime,
    String,
    Text,
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
    from .proposition import Proposition

class Observation(Base):
    """Represents an observation of user behavior."""
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    observer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)

    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    propositions: Mapped[set["Proposition"]] = relationship(
        "Proposition",
        secondary=observation_proposition,
        back_populates="observations",
        collection_class=set,
        passive_deletes=True,
        lazy="selectin",
    )  # type: ignore

    def __repr__(self) -> str:
        return f"<Observation(id={self.id}, observer={self.observer_name})>"

