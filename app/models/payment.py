from sqlalchemy import String, Integer, ForeignKey, Numeric, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin
from app.models.enums import PaymentStatus


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(50), default="mock_card", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus, name="payment_status_record_enum", native_enum=False),
        default=PaymentStatus.COMPLETED,
        nullable=False,
    )
