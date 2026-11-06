import asyncio
import time
import uuid
import httpx
from sqlalchemy import select, func
import redis.asyncio as aioredis
from app.database import AsyncSessionLocal
from app.models.booking import Booking
from app.models.enums import SeatStatus
from app.models.payment import Payment
from app.models.seat import Seat

BASE_URL = "http://127.0.0.1:8000/api/v1"
NUM_CONCURRENT_USERS = 20


async def get_redis_client():
    return aioredis.from_url("redis://127.0.0.1:6379/0", decode_responses=True, protocol=2)


async def reset_seat_and_redis(seat_id: int):
    # 1. Reset Postgres
    async with AsyncSessionLocal() as session:
        b_res = await session.execute(select(Booking.id).where(Booking.seat_id == seat_id))
        b_ids = b_res.scalars().all()
        if b_ids:
            p_res = await session.execute(select(Payment).where(Payment.booking_id.in_(b_ids)))
            for p in p_res.scalars().all():
                await session.delete(p)

        bookings = await session.execute(select(Booking).where(Booking.seat_id == seat_id))
        for b in bookings.scalars():
            await session.delete(b)

        seat_res = await session.execute(select(Seat).where(Seat.id == seat_id))
        seat = seat_res.scalar_one_or_none()
        if seat:
            seat.status = SeatStatus.AVAILABLE
            seat.held_by = None
            seat.held_until = None
            seat.version = 1

        await session.commit()

    # 2. Reset Redis
    r = await get_redis_client()
    await r.delete(f"seat:{seat_id}:hold", f"seat:{seat_id}:status")
    await r.aclose()


async def attempt_booking(client: httpx.AsyncClient, endpoint: str, user_id: str, seat_id: int):
    try:
        res = await client.post(
            f"{BASE_URL}/bookings/{endpoint}",
            json={"seat_id": seat_id, "user_id": user_id},
            timeout=10.0,
        )
        return {"user_id": user_id, "status_code": res.status_code, "data": res.json()}
    except Exception as e:
        return {"user_id": user_id, "status_code": 500, "error": str(e)}


async def test_redis_hold_concurrency():
    print("\n" + "=" * 65)
    print("TEST 1: REDIS DISTRIBUTED HOLD CONCURRENCY")
    print(f"Scenario: {NUM_CONCURRENT_USERS} simultaneous users hitting Redis for Seat 25")
    print("=" * 65)

    seat_id = 25
    await reset_seat_and_redis(seat_id)

    start = time.perf_counter()
    async with httpx.AsyncClient() as client:
        tasks = [
            attempt_booking(client, "redis-hold", f"user_{i}", seat_id)
            for i in range(1, NUM_CONCURRENT_USERS + 1)
        ]
        results = await asyncio.gather(*tasks)
    elapsed_ms = (time.perf_counter() - start) * 1000

    successes = [r for r in results if r["status_code"] == 201]
    conflicts = [r for r in results if r["status_code"] == 409]

    # Verify DB truth
    async with AsyncSessionLocal() as session:
        count_res = await session.execute(
            select(func.count(Booking.id)).where(Booking.seat_id == seat_id)
        )
        db_bookings = count_res.scalar()

        seat_res = await session.execute(select(Seat).where(Seat.id == seat_id))
        seat = seat_res.scalar_one()

    # Verify Redis truth
    r = await get_redis_client()
    hold_value = await r.get(f"seat:{seat_id}:hold")
    hold_ttl = await r.ttl(f"seat:{seat_id}:hold")
    await r.aclose()

    print(f"Results:")
    print(f"  * Successful Holds (HTTP 201): {len(successes)}")
    print(f"  * Rejected by Redis (HTTP 409): {len(conflicts)}")
    print(f"  * DB Booking rows:             {db_bookings}")
    print(f"  * Seat Status in DB:           {seat.status}")
    print(f"  * Winner in DB:                {seat.held_by}")
    print(f"  * Winner in Redis:             {hold_value}")
    print(f"  * Redis Hold TTL Remaining:    {hold_ttl} seconds")
    print(f"  * Total Elapsed Time:          {elapsed_ms:.1f} ms")

    assert len(successes) == 1, "Exactly one user should succeed!"
    assert db_bookings == 1, "Database must contain strictly one booking row!"
    assert hold_value == seat.held_by, "Redis winner and DB winner must match!"
    print("  -> PASSED: Redis cleanly shielded DB with zero double-bookings!")


async def test_redis_lifecycle_and_payment():
    print("\n" + "=" * 65)
    print("TEST 2: REDIS STATE TRANSITION TO PERMANENT CONFIRMED")
    print("=" * 65)

    seat_id = 30
    await reset_seat_and_redis(seat_id)

    async with httpx.AsyncClient() as client:
        # 1. User holds seat via Redis
        hold_res = await client.post(
            f"{BASE_URL}/bookings/redis-hold",
            json={"seat_id": seat_id, "user_id": "alice"},
        )
        assert hold_res.status_code == 201
        booking_id = hold_res.json()["id"]
        print(f"  * Alice held Seat {seat_id} via Redis (Booking ID: {booking_id})")

        # 2. Complete payment
        pay_res = await client.post(
            f"{BASE_URL}/bookings/{booking_id}/pay",
            json={"amount": 150.0},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert pay_res.status_code == 200
        print(f"  * Payment confirmed! Status: {pay_res.json()['status']}")

        # 3. Verify Redis has marked seat as CONFIRMED
        r = await get_redis_client()
        status_in_redis = await r.get(f"seat:{seat_id}:status")
        hold_in_redis = await r.get(f"seat:{seat_id}:hold")
        await r.aclose()

        print(f"  * Redis status key: {status_in_redis}")
        print(f"  * Redis hold key:   {hold_in_redis} (Should be None/deleted)")
        assert status_in_redis == "CONFIRMED"
        assert hold_in_redis is None

        # 4. Another user tries to hold this confirmed seat
        print("  * Bob attempts to hold the now-confirmed seat...")
        bob_res = await client.post(
            f"{BASE_URL}/bookings/redis-hold",
            json={"seat_id": seat_id, "user_id": "bob"},
        )
        print(f"  * Bob's response: HTTP {bob_res.status_code} ({bob_res.json().get('detail')})")
        assert bob_res.status_code == 409
        assert "already booked" in bob_res.json().get("detail", "").lower()
        print("  -> PASSED: Redis immediately blocked attempt without touching PostgreSQL!")


async def main():
    print("=================================================================")
    print("    SEATLOCK MILESTONE 4: REDIS OPTIMIZATION LAYER SHOWDOWN       ")
    print("=================================================================")
    await test_redis_hold_concurrency()
    await test_redis_lifecycle_and_payment()


if __name__ == "__main__":
    asyncio.run(main())
