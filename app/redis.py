from typing import AsyncGenerator
import redis.asyncio as aioredis
from app.config import settings

# Redis connection pool with RESP2 protocol (compatible with Redis 5.0 - 7.x)
redis_pool = aioredis.ConnectionPool(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=settings.REDIS_DB,
    decode_responses=True,
    protocol=2,
    max_connections=50,
)

redis_client = aioredis.Redis(connection_pool=redis_pool)


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI dependency yielding an async Redis client."""
    yield redis_client


# -------------------------------------------------------------------------
# ATOMIC LUA SCRIPT FOR SEAT HOLD
# -------------------------------------------------------------------------
# Lua scripts execute atomically in Redis's single-threaded event loop.
# No other command can interleave between reading the status and setting the hold!
LUA_HOLD_SCRIPT = """
local status_key = KEYS[1]
local hold_key = KEYS[2]
local user_id = ARGV[1]
local ttl_seconds = tonumber(ARGV[2])

-- 1. Check if seat is permanently booked/confirmed
local current_status = redis.call("GET", status_key)
if current_status == "CONFIRMED" then
    return -1
end

-- 2. Attempt atomic lock if not currently held
local acquired = redis.call("SET", hold_key, user_id, "NX", "EX", ttl_seconds)
if acquired then
    return 1 -- Hold granted
else
    return 0 -- Seat already held by someone else
end
"""


async def try_acquire_redis_hold(seat_id: int, user_id: str, ttl_seconds: int) -> int:
    """
    Executes the Lua script in Redis.
    Returns:
       1  -> Hold granted
       0  -> Seat is currently held by someone else
      -1  -> Seat is already CONFIRMED
    """
    status_key = f"seat:{seat_id}:status"
    hold_key = f"seat:{seat_id}:hold"
    
    result = await redis_client.eval(
        LUA_HOLD_SCRIPT,
        2,
        status_key,
        hold_key,
        user_id,
        ttl_seconds,
    )
    return int(result)


async def release_redis_hold(seat_id: int):
    """Release hold key from Redis (e.g. if DB write failed or user cancelled)."""
    hold_key = f"seat:{seat_id}:hold"
    await redis_client.delete(hold_key)


async def confirm_redis_seat(seat_id: int):
    """Mark seat as permanently CONFIRMED in Redis and delete hold."""
    status_key = f"seat:{seat_id}:status"
    hold_key = f"seat:{seat_id}:hold"
    pipe = redis_client.pipeline()
    pipe.set(status_key, "CONFIRMED")
    pipe.delete(hold_key)
    await pipe.execute()


async def sync_redis_cache_from_db(db):
    """Warm / populate Redis with current seat statuses from PostgreSQL."""
    from sqlalchemy import select
    from app.models.seat import Seat
    from app.models.enums import SeatStatus

    stmt = select(Seat.id, Seat.status).where(Seat.status == SeatStatus.CONFIRMED)
    res = await db.execute(stmt)
    confirmed_seats = res.all()

    if confirmed_seats:
        pipe = redis_client.pipeline()
        for seat_id, _ in confirmed_seats:
            pipe.set(f"seat:{seat_id}:status", "CONFIRMED")
        await pipe.execute()
