from typing import List, TYPE_CHECKING
from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.seat import Seat


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    total_seats: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    seats: Mapped[List["Seat"]] = relationship("Seat", back_populates="event", cascade="all, delete-orphan")
