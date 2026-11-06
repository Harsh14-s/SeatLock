import asyncio
import uuid
import httpx
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models.booking import Booking
from app.models.enums import BookingStatus, SeatStatus
from app.models.payment import Payment
from app.models.seat import Seat

BASE_URL = "http://127.0.0.1:8000/api/v1"


async def reset_seat(seat_id: int):
    """Reset a seat and clear its previous bookings and payments."""
    async with AsyncSessionLocal() as session:
        # Delete payments for bookings of this seat
        b_res = await session.execute(select(Booking.id).where(Booking.seat_id == seat_id))
        b_ids = b_res.scalars().all()
        if b_ids:
            p_res = await session.execute(select(Payment).where(Payment.booking_id.in_(b_ids)))
            for p in p_res.scalars().all():
                await session.delete(p)

        # Delete bookings
        bookings = await session.execute(select(Booking).where(Booking.seat_id == seat_id))
        for b in bookings.scalars():
            await session.delete(b)

        # Reset seat
        seat_res = await session.execute(select(Seat).where(Seat.id == seat_id))
        seat = seat_res.scalar_one_or_none()
        if seat:
            seat.status = SeatStatus.AVAILABLE
            seat.held_by = None
            seat.held_until = None
            seat.version = 1

        await session.commit()


async def test_idempotent_payment():
    print("\n" + "=" * 65)
    print("TEST 1: IDEMPOTENT PAYMENT RETRY (Network Retry / Double Click)")
    print("=" * 65)
    seat_id = 10
    await reset_seat(seat_id)

    async with httpx.AsyncClient() as client:
        # 1. Hold seat
        hold_res = await client.post(
            f"{BASE_URL}/bookings/atomic-hold",
            json={"seat_id": seat_id, "user_id": "alice"},
        )
        assert hold_res.status_code == 201, f"Failed to hold seat: {hold_res.text}"
        booking = hold_res.json()
        booking_id = booking["id"]
        print(f"  * Alice held Seat {seat_id} -> Booking ID {booking_id}")

        # 2. First Payment Attempt
        idempotency_key = str(uuid.uuid4())
        headers = {"Idempotency-Key": idempotency_key}
        pay_payload = {"amount": 250.0, "payment_method": "credit_card"}

        pay_res_1 = await client.post(
            f"{BASE_URL}/bookings/{booking_id}/pay",
            json=pay_payload,
            headers=headers,
        )
        assert pay_res_1.status_code == 200, f"Pay 1 failed: {pay_res_1.text}"
        data_1 = pay_res_1.json()
        print(f"  * Attempt 1 (First Charge): HTTP {pay_res_1.status_code} | Payment ID: {data_1['payment_id']} | Status: {data_1['status']}")
        assert data_1["idempotent_replay"] is False

        # 3. Simulate 3 rapid retries with the EXACT SAME Idempotency-Key
        print("  * Simulating 3 client retries (network timeout / user double click)...")
        for i in range(2, 5):
            retry_res = await client.post(
                f"{BASE_URL}/bookings/{booking_id}/pay",
                json=pay_payload,
                headers=headers,
            )
            assert retry_res.status_code == 200, f"Retry {i} failed: {retry_res.text}"
            data_retry = retry_res.json()
            assert data_retry["payment_id"] == data_1["payment_id"]
            assert data_retry["idempotent_replay"] is True
            print(f"    -> Attempt {i}: HTTP 200 (Replayed from cache) | Payment ID: {data_retry['payment_id']}")

        # 4. Check Database: Exactly ONE payment record must exist
        async with AsyncSessionLocal() as session:
            count_res = await session.execute(
                select(func.count(Payment.id)).where(Payment.booking_id == booking_id)
            )
            payment_rows = count_res.scalar()

            seat_res = await session.execute(select(Seat).where(Seat.id == seat_id))
            seat = seat_res.scalar_one()

        print(f"  * Database Truth: Total Payment rows created: {payment_rows}")
        print(f"  * Final Seat Status: {seat.status}")
        assert payment_rows == 1, f"Expected 1 payment row, found {payment_rows}!"
        assert seat.status == SeatStatus.CONFIRMED
        print("  -> PASSED: Card charged exactly ONCE despite multiple retries!")


async def test_hold_expiration_and_release():
    print("\n" + "=" * 65)
    print("TEST 2: 5-MINUTE HOLD EXPIRATION & SEAT RECOVERY")
    print("=" * 65)
    seat_id = 11
    await reset_seat(seat_id)

    async with httpx.AsyncClient() as client:
        # 1. Hold seat with a short TTL (2 seconds for testing)
        print("  * User Bob holds Seat 11 with 2-second TTL...")
        hold_res = await client.post(
            f"{BASE_URL}/bookings/atomic-hold",
            json={"seat_id": seat_id, "user_id": "bob", "ttl_seconds": 2},
        )
        assert hold_res.status_code == 201
        booking_id = hold_res.json()["id"]

        # 2. Wait 3 seconds for hold to expire
        print("  * Waiting 3 seconds for hold timer to expire...")
        await asyncio.sleep(3)

        # 3. Bob tries to pay after expiration
        print("  * Bob attempts to pay for expired hold...")
        pay_res = await client.post(
            f"{BASE_URL}/bookings/{booking_id}/pay",
            json={"amount": 100.0},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        print(f"  * Response: HTTP {pay_res.status_code} ({pay_res.json().get('detail')})")
        assert pay_res.status_code == 410, f"Expected 410 Gone, got {pay_res.status_code}"

        # 4. Trigger / verify seat is returned to AVAILABLE
        clean_res = await client.post(f"{BASE_URL}/bookings/cleanup-expired")
        print(f"  * Cleaner worker executed: {clean_res.json()}")

        # 5. User Charlie now tries to grab the newly released seat
        print("  * User Charlie attempts to book the freed seat...")
        charlie_res = await client.post(
            f"{BASE_URL}/bookings/atomic-hold",
            json={"seat_id": seat_id, "user_id": "charlie"},
        )
        assert charlie_res.status_code == 201, f"Charlie failed to book: {charlie_res.text}"
        print(f"  * Charlie successfully secured Seat {seat_id} (Booking ID: {charlie_res.json()['id']})!")

        # 6. Verify in DB
        async with AsyncSessionLocal() as session:
            seat_res = await session.execute(select(Seat).where(Seat.id == seat_id))
            seat = seat_res.scalar_one()

        print(f"  * Seat Current Status: {seat.status} (Held by: {seat.held_by})")
        assert seat.held_by == "charlie"
        print("  -> PASSED: Expired holds are released and re-bookable!")


async def main():
    print("=================================================================")
    print("    SEATLOCK MILESTONE 3: PAYMENT IDEMPOTENCY & HOLD EXPIRATION  ")
    print("=================================================================")
    await test_idempotent_payment()
    await test_hold_expiration_and_release()


if __name__ == "__main__":
    asyncio.run(main())
