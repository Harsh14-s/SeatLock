from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import (
    String,
    Integer,
    ForeignKey,
    DateTime,
    Enum as SQLEnum,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin
from app.models.enums import SeatStatus

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.booking import Booking


class Seat(Base, TimestampMixin):
    __tablename__ = "seats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seat_number: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Current status of the seat
    status: Mapped[SeatStatus] = mapped_column(
        SQLEnum(SeatStatus, name="seat_status_enum", native_enum=False),
        default=SeatStatus.AVAILABLE,
        nullable=False,
        index=True,
    )
    
    # ID of the user holding the seat (if status == HELD)
    held_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Expiration time for the hold
    held_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    
    # Version column for Optimistic Locking comparisons
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="seats")
    bookings: Mapped[list["Booking"]] = relationship("Booking", back_populates="seat")

    __table_args__ = (
        UniqueConstraint("event_id", "seat_number", name="uq_event_seat"),
        Index("ix_seats_event_status", "event_id", "status"),
    )
