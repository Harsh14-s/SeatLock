import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app.models.booking import Booking
from app.models.enums import BookingStatus, SeatStatus
from app.models.seat import Seat

logger = logging.getLogger(__name__)


async def expire_pending_holds(db: AsyncSession) -> int:
    """
    Reverts expired seat holds back to AVAILABLE and marks bookings as EXPIRED.
    Returns the count of seats freed.
    """
    now = datetime.now(timezone.utc)

    # 1. Select all expired PENDING bookings
    expired_bookings_stmt = (
        select(Booking)
        .where(
            Booking.status == BookingStatus.PENDING,
            Booking.expires_at <= now,
        )
        .with_for_update(skip_locked=True)  # Don't block active payment transactions
    )
    result = await db.execute(expired_bookings_stmt)
    expired_bookings = result.scalars().all()

    if not expired_bookings:
        # Also clean up any orphan HELD seats where held_until passed
        orphan_seats_stmt = (
            update(Seat)
            .where(
                Seat.status == SeatStatus.HELD,
                Seat.held_until <= now,
            )
            .values(
                status=SeatStatus.AVAILABLE,
                held_by=None,
                held_until=None,
            )
        )
        orphan_res = await db.execute(orphan_seats_stmt)
        await db.commit()
        return orphan_res.rowcount

    seat_ids = [b.seat_id for b in expired_bookings]

    # 2. Mark bookings as EXPIRED
    for b in expired_bookings:
        b.status = BookingStatus.EXPIRED

    # 3. Release the seats back to AVAILABLE
    seats_stmt = (
        update(Seat)
        .where(Seat.id.in_(seat_ids), Seat.status == SeatStatus.HELD)
        .values(
            status=SeatStatus.AVAILABLE,
            held_by=None,
            held_until=None,
        )
    )
    await db.execute(seats_stmt)
    await db.commit()

    return len(seat_ids)


async def background_cleanup_loop(interval_seconds: int = 5):
    """Continuous background loop running during application lifespan."""
    logger.info("Hold expiry background cleaner started.")
    while True:
        try:
            async with AsyncSessionLocal() as session:
                freed = await expire_pending_holds(session)
                if freed > 0:
                    logger.info(f"Released {freed} expired seat holds back to AVAILABLE.")
        except asyncio.CancelledError:
            logger.info("Hold expiry cleaner cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in hold expiry cleaner: {e}")

        await asyncio.sleep(interval_seconds)
