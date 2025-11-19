from typing import Optional, TYPE_CHECKING
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)
from sqlalchemy import (
    Date,
    String,
)
from .base import Base

if TYPE_CHECKING:
    from .observation import Observation
    from .proposition import Proposition

class User(Base):
    """Represents a user owning observations and propositions."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    dob: Mapped[Optional[str]] = mapped_column(Date, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    password: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    observations: Mapped[list["Observation"]] = relationship(
        "Observation",
        backref="user",
        collection_class=list,
        lazy="selectin",
    )  # type: ignore

    propositions: Mapped[list["Proposition"]] = relationship(
        "Proposition",
        backref="user",
        collection_class=list,
        lazy="selectin",
    )  # type: ignore

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username})>"
