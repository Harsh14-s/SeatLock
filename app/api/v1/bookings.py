import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DatabaseSession
from app.config import settings
from app.models.booking import Booking
from app.models.enums import BookingStatus, SeatStatus
from app.models.seat import Seat
from app.schemas.booking import BookingResponse, HoldSeatRequest

router = APIRouter(prefix="/bookings", tags=["Bookings"])


# -------------------------------------------------------------------------
# 1. NAIVE / BUGGY ENDPOINT (Demonstrates the Race Condition)
# -------------------------------------------------------------------------
@router.post(
    "/naive-hold",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[NAIVE / BUGGY] Hold a seat without locking (Vulnerable to Race Conditions)",
)
async def naive_hold_seat(
    payload: HoldSeatRequest,
    db: AsyncSession = DatabaseSession,
):
    """
    ⚠️ INTENTIONALLY BUGGY:
    Reads seat status and checks availability, but does NOT lock the row.
    Multiple concurrent requests pass the check and create duplicate bookings.
    """
    result = await db.execute(select(Seat).where(Seat.id == payload.seat_id))
    seat = result.scalar_one_or_none()

    if not seat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Seat {payload.seat_id} not found",
        )

    if seat.status != SeatStatus.AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Seat {payload.seat_id} is already {seat.status}",
        )

    # Simulated delay to widen the race window
    await asyncio.sleep(0.05)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.HOLD_TTL_SECONDS)

    seat.status = SeatStatus.HELD
    seat.held_by = payload.user_id
    seat.held_until = expires_at

    booking = Booking(
        user_id=payload.user_id,
        seat_id=seat.id,
        status=BookingStatus.PENDING,
        expires_at=expires_at,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    return booking


# -------------------------------------------------------------------------
# 2. PESSIMISTIC LOCKING ENDPOINT (SELECT ... FOR UPDATE)
# -------------------------------------------------------------------------
@router.post(
    "/pessimistic-hold",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[PESSIMISTIC LOCK] Hold a seat using PostgreSQL SELECT ... FOR UPDATE",
)
async def pessimistic_hold_seat(
    payload: HoldSeatRequest,
    db: AsyncSession = DatabaseSession,
):
    """
    🛡️ PESSIMISTIC LOCKING PATTERN:
    Uses PostgreSQL's `SELECT ... FOR UPDATE` row-level exclusive lock.
    
    How it works:
    1. Transaction begins.
    2. `SELECT ... FOR UPDATE` acquires an exclusive lock on that specific seat row.
    3. Any other transaction requesting the same seat is paused by PostgreSQL until this transaction completes.
    4. Once acquired, we verify status == AVAILABLE.
    5. Update to HELD, insert booking, and commit.
    6. Lock is released on commit. Next queued transaction reads the new status ('HELD') and gets 409 Conflict.
    """
    # with_for_update() appends "FOR UPDATE" to the SQL query
    stmt = (
        select(Seat)
        .where(Seat.id == payload.seat_id)
        .with_for_update()
    )
    result = await db.execute(stmt)
    seat = result.scalar_one_or_none()

    if not seat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Seat {payload.seat_id} not found",
        )

    # Safe check: Because we hold the exclusive row lock, NO other transaction can modify this row
    if seat.status != SeatStatus.AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Seat {payload.seat_id} is already {seat.status}",
        )

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.HOLD_TTL_SECONDS)

    seat.status = SeatStatus.HELD
    seat.held_by = payload.user_id
    seat.held_until = expires_at

    booking = Booking(
        user_id=payload.user_id,
        seat_id=seat.id,
        status=BookingStatus.PENDING,
        expires_at=expires_at,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    return booking


# -------------------------------------------------------------------------
# 3. ATOMIC CONDITIONAL UPDATE (Compare-And-Swap Pattern)
# -------------------------------------------------------------------------
@router.post(
    "/atomic-hold",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[ATOMIC CONDITIONAL UPDATE] Hold a seat using atomic UPDATE ... WHERE status='AVAILABLE'",
)
async def atomic_hold_seat(
    payload: HoldSeatRequest,
    db: AsyncSession = DatabaseSession,
):
    """
    ⚡ ATOMIC CONDITIONAL UPDATE (Compare-and-Swap / Optimistic Pattern):
    Executes a single SQL statement that only updates if status is still AVAILABLE:
    `UPDATE seats SET status='HELD', ... WHERE id=:id AND status='AVAILABLE' RETURNING id`
    
    How it works:
    1. We don't read first. We attempt an atomic UPDATE immediately.
    2. PostgreSQL evaluates the WHERE clause atomically on the row.
    3. Exactly ONE transaction modifies the row (returns 1 row).
    4. All other concurrent transactions find 0 matching rows (returns None).
    5. Highly efficient: No explicit row lock wait overhead!
    """
    ttl = payload.ttl_seconds or settings.HOLD_TTL_SECONDS
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl)

    stmt = (
        update(Seat)
        .where(Seat.id == payload.seat_id, Seat.status == SeatStatus.AVAILABLE)
        .values(
            status=SeatStatus.HELD,
            held_by=payload.user_id,
            held_until=expires_at,
        )
        .returning(Seat.id)
    )
    result = await db.execute(stmt)
    updated_seat_id = result.scalar_one_or_none()

    if not updated_seat_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Seat {payload.seat_id} is already booked or held",
        )

    booking = Booking(
        user_id=payload.user_id,
        seat_id=payload.seat_id,
        status=BookingStatus.PENDING,
        expires_at=expires_at,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    return booking


@router.post(
    "/redis-hold",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[REDIS DISTRIBUTED HOLD] In-memory fast gatekeeper shielding PostgreSQL",
)
async def redis_hold_seat(
    payload: HoldSeatRequest,
    db: AsyncSession = DatabaseSession,
):
    """
    ⚡ REDIS DISTRIBUTED HOLD ARCHITECTURE:
    
    1. Phase 1: In-Memory Pre-Hold (Sub-millisecond gatekeeper)
       - Evaluates an atomic Lua script in Redis.
       - If seat is held or booked, rejects in < 1ms with HTTP 409 Conflict.
       - Shields PostgreSQL connection pool and CPU from 99% of flash-sale traffic!
    
    2. Phase 2: Relational Persistence
       - Only the 1 winning request touches PostgreSQL to record the booking.
       - If DB write fails, compensating transaction rolls back the Redis key.
    """
    from app.redis import try_acquire_redis_hold, release_redis_hold

    ttl = payload.ttl_seconds or settings.HOLD_TTL_SECONDS
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl)

    # 1. Acquire Redis Hold atomically
    hold_result = await try_acquire_redis_hold(payload.seat_id, payload.user_id, ttl)

    if hold_result == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Seat {payload.seat_id} is currently held by another user (shielded by Redis)",
        )
    elif hold_result == -1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Seat {payload.seat_id} is already booked and confirmed",
        )

    # 2. Persist to PostgreSQL (Only the winner runs this query!)
    try:
        stmt = (
            update(Seat)
            .where(Seat.id == payload.seat_id, Seat.status == SeatStatus.AVAILABLE)
            .values(
                status=SeatStatus.HELD,
                held_by=payload.user_id,
                held_until=expires_at,
            )
            .returning(Seat.id)
        )
        result = await db.execute(stmt)
        updated_seat_id = result.scalar_one_or_none()

        if not updated_seat_id:
            # DB was out of sync with Redis
            await release_redis_hold(payload.seat_id)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Seat {payload.seat_id} is already taken in database",
            )

        booking = Booking(
            user_id=payload.user_id,
            seat_id=payload.seat_id,
            status=BookingStatus.PENDING,
            expires_at=expires_at,
        )
        db.add(booking)
        await db.commit()
        await db.refresh(booking)

        return booking

    except Exception as e:
        # Compensating transaction: release Redis lock on unexpected failure
        await release_redis_hold(payload.seat_id)
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database write failed: {str(e)}",
        )


@router.post(
    "/cleanup-expired",
    summary="Trigger immediate cleanup of expired holds",
)
async def trigger_cleanup(db: AsyncSession = DatabaseSession):
    from app.workers.cleanup import expire_pending_holds
    freed_count = await expire_pending_holds(db)
    return {"status": "ok", "released_seats": freed_count}


