import asyncio
import math
import random
import statistics
import time
import httpx
from sqlalchemy import select, func, text
import redis.asyncio as aioredis

from app.database import AsyncSessionLocal
from app.models.booking import Booking
from app.models.enums import SeatStatus
from app.models.payment import Payment
from app.models.seat import Seat

BASE_URL = "http://127.0.0.1:8000/api/v1"
TOTAL_SEATS = 100
TOTAL_REQUESTS = 1000
CONCURRENCY_LIMIT = 50  # 50 in-flight simultaneous TCP connections


async def reset_all_seats():
    """Wipe bookings/payments and reset all 100 seats to AVAILABLE."""
    print("[RESET] Resetting database and Redis to clean initial state...")
    async with AsyncSessionLocal() as session:
        # Delete payments and bookings
        await session.execute(text("DELETE FROM payments;"))
        await session.execute(text("DELETE FROM bookings;"))
        await session.execute(
            text(
                "UPDATE seats SET status = 'AVAILABLE', held_by = NULL, held_until = NULL, version = 1;"
            )
        )
        await session.commit()

    # Flush Redis keys for all seats
    r = aioredis.from_url("redis://127.0.0.1:6379/0", protocol=2)
    await r.flushdb()
    await r.aclose()
    print("[RESET] Reset complete: 100 seats available, 0 bookings.")


async def send_booking_request(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    endpoint: str,
    user_id: str,
    seat_id: int,
):
    async with sem:
        t0 = time.perf_counter()
        try:
            res = await client.post(
                f"{BASE_URL}/bookings/{endpoint}",
                json={"seat_id": seat_id, "user_id": user_id},
                timeout=15.0,
            )
            elapsed = (time.perf_counter() - t0) * 1000
            return {
                "status_code": res.status_code,
                "latency_ms": elapsed,
                "seat_id": seat_id,
            }
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return {
                "status_code": 500,
                "latency_ms": elapsed,
                "error": str(e),
                "seat_id": seat_id,
            }


async def run_benchmark(endpoint: str, label: str):
    print("\n" + "=" * 70)
    print(f"LOAD TEST: {label}")
    print(f"Target: POST /api/v1/bookings/{endpoint}")
    print(f"Traffic: {TOTAL_REQUESTS} requests competing for {TOTAL_SEATS} seats")
    print(f"Max Concurrent Connections: {CONCURRENCY_LIMIT}")
    print("=" * 70)

    await reset_all_seats()

    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)
    limits = httpx.Limits(max_keepalive_connections=CONCURRENCY_LIMIT, max_connections=CONCURRENCY_LIMIT)

    # Generate 1,000 requests competing for 100 seats
    requests_data = [
        (f"load_user_{i}", (i % TOTAL_SEATS) + 1)
        for i in range(1, TOTAL_REQUESTS + 1)
    ]
    # Shuffle to simulate random arrival
    random.seed(42)
    random.shuffle(requests_data)

    print(f"Executing {TOTAL_REQUESTS} concurrent requests...")
    wall_start = time.perf_counter()

    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [
            send_booking_request(client, sem, endpoint, user_id, seat_id)
            for user_id, seat_id in requests_data
        ]
        results = await asyncio.gather(*tasks)

    total_wall_time = time.perf_counter() - wall_start

    # Metrics calculation
    latencies = [r["latency_ms"] for r in results]
    successes = [r for r in results if r["status_code"] == 201]
    conflicts = [r for r in results if r["status_code"] == 409]
    errors = [r for r in results if r["status_code"] not in (201, 409)]

    latencies.sort()
    avg_latency = statistics.mean(latencies)
    p50 = statistics.median(latencies)
    p90 = latencies[int(len(latencies) * 0.90)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    rps = TOTAL_REQUESTS / total_wall_time

    print(f"\nPerformance & Latency Metrics:")
    print(f"  * Total Requests Processed: {TOTAL_REQUESTS}")
    print(f"  * Total Wall Time:          {total_wall_time:.2f} seconds")
    print(f"  * Throughput:               {rps:.1f} Requests / Second (RPS)")
    print(f"  * Avg Latency:              {avg_latency:.2f} ms")
    print(f"  * Median (p50):             {p50:.2f} ms")
    print(f"  * 90th Percentile (p90):    {p90:.2f} ms")
    print(f"  * 95th Percentile (p95):    {p95:.2f} ms")
    print(f"  * 99th Percentile (p99):    {p99:.2f} ms")

    print(f"\nHTTP Status Distribution:")
    print(f"  * Successful Bookings (201 Created):  {len(successes)}")
    print(f"  * Contention Conflicts (409 Conflict): {len(conflicts)}")
    print(f"  * System Errors (500s / Dropped):      {len(errors)}")

    # Database Truth & Invariant Verification
    print(f"\nDatabase Invariant & Integrity Verification:")
    async with AsyncSessionLocal() as session:
        # Check total bookings created
        count_res = await session.execute(select(func.count(Booking.id)))
        total_db_bookings = count_res.scalar()

        # Check for ANY double-bookings across all seats
        dup_query = text("""
            SELECT seat_id, count(*) 
            FROM bookings 
            WHERE status IN ('PENDING', 'CONFIRMED') 
            GROUP BY seat_id 
            HAVING count(*) > 1;
        """)
        dup_res = await session.execute(dup_query)
        duplicates = dup_res.fetchall()

        # Check seat status count
        held_seats_res = await session.execute(
            select(func.count(Seat.id)).where(Seat.status == SeatStatus.HELD)
        )
        held_seats = held_seats_res.scalar()

    print(f"  * Total Bookings in Database:       {total_db_bookings}")
    print(f"  * Seats in 'HELD' Status:           {held_seats} / {TOTAL_SEATS}")
    print(f"  * Duplicate Bookings Detected:      {len(duplicates)}")

    if len(duplicates) == 0 and total_db_bookings == TOTAL_SEATS and len(successes) == TOTAL_SEATS:
        print("  -> PERFECT INTEGRITY: Exactly 100 seats booked, ZERO double-bookings!")
    else:
        print(f"  -> INTEGRITY FAILURE: Duplicates detected: {duplicates}")

    return {
        "label": label,
        "rps": rps,
        "avg": avg_latency,
        "p50": p50,
        "p90": p90,
        "p95": p95,
        "p99": p99,
        "successes": len(successes),
        "conflicts": len(conflicts),
        "errors": len(errors),
        "duplicates": len(duplicates),
    }


async def main():
    print("=======================================================================")
    print("      SEATLOCK FLASH-SALE LOAD TEST (1,000 CONCURRENT REQUESTS)        ")
    print("=======================================================================")

    # Test 1: Atomic PostgreSQL conditional update
    postgres_stats = await run_benchmark("atomic-hold", "PostgreSQL Atomic Conditional Update")

    # Test 2: Redis-Backed Distributed Hold
    redis_stats = await run_benchmark("redis-hold", "Redis Distributed Gatekeeper + PostgreSQL")

    # Final Summary Table
    print("\n" + "=" * 70)
    print("                 FINAL LOAD TEST COMPARISON SUMMARY                    ")
    print("=" * 70)
    print(f"{'Metric':<25} | {'Postgres Atomic':<20} | {'Redis Gatekeeper':<20}")
    print("-" * 70)
    print(f"{'Throughput (RPS)':<25} | {postgres_stats['rps']:<20.1f} | {redis_stats['rps']:<20.1f}")
    print(f"{'Avg Latency (ms)':<25} | {postgres_stats['avg']:<20.2f} | {redis_stats['avg']:<20.2f}")
    print(f"{'Median p50 (ms)':<25} | {postgres_stats['p50']:<20.2f} | {redis_stats['p50']:<20.2f}")
    print(f"{'p90 Latency (ms)':<25} | {postgres_stats['p90']:<20.2f} | {redis_stats['p90']:<20.2f}")
    print(f"{'p95 Latency (ms)':<25} | {postgres_stats['p95']:<20.2f} | {redis_stats['p95']:<20.2f}")
    print(f"{'p99 Latency (ms)':<25} | {postgres_stats['p99']:<20.2f} | {redis_stats['p99']:<20.2f}")
    print(f"{'Double-Bookings':<25} | {postgres_stats['duplicates']:<20} | {redis_stats['duplicates']:<20}")
    print(f"{'Unexpected Errors':<25} | {postgres_stats['errors']:<20} | {redis_stats['errors']:<20}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
