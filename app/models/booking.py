from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import (
    String,
    Integer,
    ForeignKey,
    DateTime,
    Enum as SQLEnum,
    Index,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin
from app.models.enums import BookingStatus

if TYPE_CHECKING:
    from app.models.seat import Seat


class Booking(Base, TimestampMixin):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    seat_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("seats.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[BookingStatus] = mapped_column(
        SQLEnum(BookingStatus, name="booking_status_enum", native_enum=False),
        default=BookingStatus.PENDING,
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    
    # Relationships
    seat: Mapped["Seat"] = relationship("Seat", back_populates="bookings")

    __table_args__ = (
        Index("ix_bookings_user_status", "user_id", "status"),
        Index("ix_bookings_seat_status", "seat_id", "status"),
        # Partial unique index: Guarantees at the database level that no seat
        # can have more than one active ('PENDING' or 'CONFIRMED') booking at the same time.
        Index(
            "uq_active_seat_booking",
            "seat_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'CONFIRMED')"),
        ),
    )
