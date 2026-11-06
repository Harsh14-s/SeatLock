import asyncio
import time
import httpx
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models.booking import Booking
from app.models.seat import Seat
from app.models.enums import SeatStatus

BASE_URL = "http://127.0.0.1:8000/api/v1"
TARGET_SEAT_ID = 1
NUM_CONCURRENT_USERS = 20


async def reset_seat(seat_id: int):
    """Reset the target seat to AVAILABLE and clear previous bookings."""
    async with AsyncSessionLocal() as session:
        # Reset seat
        result = await session.execute(select(Seat).where(Seat.id == seat_id))
        seat = result.scalar_one_or_none()
        if seat:
            seat.status = SeatStatus.AVAILABLE
            seat.held_by = None
            seat.held_until = None
            seat.version = 1

        # Delete existing bookings for this seat
        bookings = await session.execute(select(Booking).where(Booking.seat_id == seat_id))
        for b in bookings.scalars():
            await session.delete(b)

        await session.commit()


async def attempt_booking(client: httpx.AsyncClient, endpoint: str, user_id: str, seat_id: int):
    """Single booking request to a given endpoint."""
    try:
        response = await client.post(
            f"{BASE_URL}/bookings/{endpoint}",
            json={"seat_id": seat_id, "user_id": user_id},
            timeout=10.0,
        )
        return {
            "user_id": user_id,
            "status_code": response.status_code,
            "data": response.json(),
        }
    except Exception as e:
        return {"user_id": user_id, "status_code": 500, "error": str(e)}


async def test_endpoint(endpoint_name: str, label: str):
    print("\n" + "=" * 65)
    print(f"TESTING: {label}")
    print(f"Endpoint: POST /api/v1/bookings/{endpoint_name}")
    print(f"Concurrency: {NUM_CONCURRENT_USERS} simultaneous users -> Seat {TARGET_SEAT_ID}")
    print("=" * 65)

    await reset_seat(TARGET_SEAT_ID)

    start_time = time.perf_counter()
    async with httpx.AsyncClient() as client:
        tasks = [
            attempt_booking(client, endpoint_name, f"user_{i}", TARGET_SEAT_ID)
            for i in range(1, NUM_CONCURRENT_USERS + 1)
        ]
        results = await asyncio.gather(*tasks)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    successes = [r for r in results if r["status_code"] == 201]
    conflicts = [r for r in results if r["status_code"] == 409]
    others = [r for r in results if r["status_code"] not in (201, 409)]

    # Query DB truth
    async with AsyncSessionLocal() as session:
        count_res = await session.execute(
            select(func.count(Booking.id)).where(Booking.seat_id == TARGET_SEAT_ID)
        )
        db_booking_count = count_res.scalar()

        seat_res = await session.execute(select(Seat).where(Seat.id == TARGET_SEAT_ID))
        seat = seat_res.scalar_one()

    print(f"Results:")
    print(f"  * Successful (HTTP 201): {len(successes)}")
    print(f"  * Conflict   (HTTP 409): {len(conflicts)}")
    if others:
        print(f"  * Errors     (Other):    {len(others)}")
    print(f"  * DB Booking rows:       {db_booking_count}")
    print(f"  * Seat Status:           {seat.status}")
    print(f"  * Winner User:           {seat.held_by}")
    print(f"  * Elapsed Time:          {elapsed_ms:.1f} ms")

    if db_booking_count == 1 and len(successes) == 1:
        print("  -> PASSED: ZERO DOUBLE-BOOKINGS! Perfect concurrency control.")
    else:
        print(f"  -> FAILED: RACE CONDITION! {db_booking_count} duplicate bookings detected.")


async def main():
    print("=================================================================")
    print("    SEATLOCK CONCURRENCY SHOWDOWN: NAIVE vs PESSIMISTIC vs ATOMIC")
    print("=================================================================")
    
    # 1. Test Pessimistic Locking (SELECT ... FOR UPDATE)
    await test_endpoint("pessimistic-hold", "PESSIMISTIC ROW LOCKING (SELECT ... FOR UPDATE)")

    # 2. Test Atomic Conditional Update
    await test_endpoint("atomic-hold", "ATOMIC CONDITIONAL UPDATE (UPDATE ... WHERE status='AVAILABLE')")


if __name__ == "__main__":
    asyncio.run(main())
