import json
from datetime import datetime, timedelta, timezone
from typing import Annotated
from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DatabaseSession
from app.models.booking import Booking
from app.models.enums import BookingStatus, PaymentStatus, SeatStatus
from app.models.idempotency import IdempotencyKey
from app.models.payment import Payment
from app.models.seat import Seat
from app.schemas.payment import PaymentRequest, PaymentResponse

router = APIRouter(prefix="/bookings", tags=["Payments"])


@router.post(
    "/{booking_id}/pay",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Process payment for a held seat with strict idempotency",
)
async def process_payment(
    booking_id: int,
    payload: PaymentRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    db: AsyncSession = DatabaseSession,
):
    """
    💳 IDEMPOTENT PAYMENT PROCESSING:
    
    1. Idempotency Check:
       - If Idempotency-Key was already processed successfully, return the cached result immediately.
         (Prevents double charges when users double click or network retries occur).
       - If key is currently IN_PROGRESS, reject duplicate concurrent attempt with 409 Conflict.
    
    2. Hold & Expiration Check (with FOR UPDATE):
       - Verifies the hold has not expired past its TTL.
       - If expired, marks the booking as EXPIRED, releases the seat to AVAILABLE, and returns 410 Gone.
    
    3. State Transition:
       - Booking: PENDING -> CONFIRMED
       - Seat: HELD -> CONFIRMED
       - Payment: Recorded & linked to Idempotency-Key
    """
    now = datetime.now(timezone.utc)

    # --- 1. IDEMPOTENCY KEY CHECK ---
    key_res = await db.execute(
        select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key)
    )
    existing_key = key_res.scalar_one_or_none()

    if existing_key:
        if existing_key.status == PaymentStatus.COMPLETED and existing_key.response_body:
            cached_data = json.loads(existing_key.response_body)
            cached_data["idempotent_replay"] = True
            return PaymentResponse(**cached_data)

        if existing_key.status == PaymentStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A payment with this Idempotency-Key is currently being processed. Please do not retry immediately.",
            )

    # Reserve the idempotency key in PENDING status
    if not existing_key:
        new_key = IdempotencyKey(
            key=idempotency_key,
            user_id="anonymous",
            endpoint=f"/bookings/{booking_id}/pay",
            status=PaymentStatus.PENDING,
            expires_at=now + timedelta(hours=24),
        )
        db.add(new_key)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Concurrent request detected with the same Idempotency-Key.",
            )

    # --- 2. RETRIEVE BOOKING WITH ROW LOCK ---
    booking_stmt = (
        select(Booking)
        .where(Booking.id == booking_id)
        .with_for_update()
    )
    b_res = await db.execute(booking_stmt)
    booking = b_res.scalar_one_or_none()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Booking {booking_id} not found",
        )

    # If already confirmed
    if booking.status == BookingStatus.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Booking {booking_id} is already CONFIRMED.",
        )

    # Check if hold expired
    if booking.status == BookingStatus.EXPIRED or booking.expires_at <= now:
        booking.status = BookingStatus.EXPIRED

        # Release seat
        seat_stmt = (
            select(Seat)
            .where(Seat.id == booking.seat_id)
            .with_for_update()
        )
        s_res = await db.execute(seat_stmt)
        seat = s_res.scalar_one_or_none()
        if seat and seat.status == SeatStatus.HELD:
            seat.status = SeatStatus.AVAILABLE
            seat.held_by = None
            seat.held_until = None

        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Seat hold has expired. The seat has been released back to the pool.",
        )

    # --- 3. RETRIEVE SEAT AND CONFIRM RESERVATION ---
    seat_stmt = (
        select(Seat)
        .where(Seat.id == booking.seat_id)
        .with_for_update()
    )
    s_res = await db.execute(seat_stmt)
    seat = s_res.scalar_one_or_none()

    if not seat or seat.status != SeatStatus.HELD:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Seat is not in a valid HELD state to complete payment.",
        )

    # Transition states
    booking.status = BookingStatus.CONFIRMED
    seat.status = SeatStatus.CONFIRMED
    seat.held_until = None

    # Record Payment
    payment = Payment(
        booking_id=booking.id,
        user_id=booking.user_id,
        amount=payload.amount,
        payment_method=payload.payment_method,
        idempotency_key=idempotency_key,
        status=PaymentStatus.COMPLETED,
    )
    db.add(payment)
    await db.flush()

    response_dict = {
        "payment_id": payment.id,
        "booking_id": booking.id,
        "user_id": booking.user_id,
        "seat_id": seat.id,
        "amount": float(payment.amount),
        "status": PaymentStatus.COMPLETED,
        "idempotent_replay": False,
    }

    # Finalize Idempotency Key
    key_record_res = await db.execute(
        select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key)
    )
    key_record = key_record_res.scalar_one()
    key_record.user_id = booking.user_id
    key_record.status = PaymentStatus.COMPLETED
    key_record.response_code = 200
    key_record.response_body = json.dumps(response_dict)

    await db.commit()

    # Sync Redis state: Seat is permanently confirmed
    from app.redis import confirm_redis_seat
    try:
        await confirm_redis_seat(seat.id)
    except Exception:
        pass  # Redis status sync is best-effort; PostgreSQL is the source of truth

    return PaymentResponse(**response_dict)

