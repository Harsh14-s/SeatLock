from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin
from app.models.enums import PaymentStatus


class IdempotencyKey(Base, TimestampMixin):
    """
    Tracks incoming requests with Idempotency-Key headers.
    Guarantees that retry attempts or duplicate clicks produce identical results
    without executing side-effects (like charging a credit card) multiple times.
    """
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(255), primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Status of the operation
    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus, name="idempotency_status_enum", native_enum=False),
        default=PaymentStatus.PENDING,
        nullable=False,
        index=True,
    )
    
    # Cached response for instant reply on retries
    response_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Expiry for the key retention (e.g. 24 hours)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
