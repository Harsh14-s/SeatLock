# SeatLock 🎟️🔒

> **High-concurrency ticket booking engine guaranteeing zero double-bookings, idempotent payments, and sub-millisecond distributed hold gates under flash-sale traffic.**

[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-In--Memory-DC382D?logo=redis)](https://redis.io/)
[![k6](https://img.shields.io/badge/Load_Testing-Grafana_k6-7D64FF?logo=k6)](https://k6.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 📌 The Real-World Problem

Think of **BookMyShow**, **IRCTC Tatkal**, or **Ticketmaster**. A popular concert opens booking, and thousands of users attempt to grab a limited number of seats at the exact same millisecond.

The backend must strictly guarantee four invariants:
1. **Zero Double-Bookings:** Exactly one person gets a seat.
2. **Zero Duplicate Charges:** Network retries and double clicks never charge a customer twice.
3. **Automatic Abandonment Expiration:** A held seat is reserved for 5 minutes, but automatically released if checkout is abandoned.
4. **Sub-Millisecond Edge Rejections:** The system shields the relational database from CPU and connection pool starvation during flash-sale spikes.

---

## ⚡ Concurrency Showdown: Results Under Contention

When 20 concurrent requests compete for Seat 1 at the exact same millisecond:

| Implementation Pattern | Endpoint | Successful (201) | Conflicts (409) | DB Duplicate Rows | Execution Time | Result |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Naive Read-then-Write** | `/bookings/naive-hold` | **11** | 9 | **11** | 72 ms | 💥 **11 users sold the same seat!** |
| **Pessimistic Row Locking** | `/bookings/pessimistic-hold` | **1** | 19 | **1** | 667.1 ms | ✅ Zero double-bookings |
| **Atomic Conditional Update** | `/bookings/atomic-hold` | **1** | 19 | **1** | 284.9 ms | ⚡ **2.3x faster than row locking** |
| **Redis Distributed Hold** | `/bookings/redis-hold` | **1** | 19 | **1** | < 1 ms (gate) | 🚀 **Shields DB from 99% traffic** |

---

## 🚀 Grafana k6 Load Test Results (1,000 Concurrent Requests)

Benchmarked with **1,000 requests competing for 100 seats** under maximum concurrency:

```text
          /\      |‾‾| /‾‾/   /‾‾/   
     /\  /  \     |  |/  /   /  /    
    /  \/    \    |     (   /   ‾‾\  
   /          \   |  |\  \ |  (‾)  | 
  / __________ \  |__| \__\ \_____/ .io

     scenarios: 50 VUs x 20 iterations = 1,000 total requests
     duration:  1.4 seconds total execution time

     ✓ checks.....................: 100.00% (1,000 / 1,000)
     ✓ unexpected_errors..........: 0.00%
     ✓ throughput (RPS)...........: 722.4 requests / second
     ✓ http_req_duration (avg)....: 64.38 ms
     ✓ http_req_duration (p50)....: 59.51 ms
     ✓ http_req_duration (p90)....: 71.61 ms
     ✓ http_req_duration (p95)....: 118.16 ms
```

### Database Invariant Verification
```sql
-- Ran immediately after the 1,000-request load test:
SELECT seat_id, count(*) 
FROM bookings 
WHERE status IN ('PENDING', 'CONFIRMED') 
GROUP BY seat_id 
HAVING count(*) > 1;

-- Output: 0 rows (ZERO double-bookings across all 100 seats)
```

---

## 🏗️ Architecture & Core Engineering Concepts

```
                       [ 1,000+ Concurrent Requests ]
                                     |
                                     v
                       +---------------------------+
                       |    FastAPI (Async ASGI)   |
                       +-------------+-------------+
                                     |
                      +--------------+--------------+
                      |                             |
                      v                             v
          +-----------------------+     +-----------------------+
          |   Redis (In-Memory)   |     | PostgreSQL 16 (ACID)  |
          |  - Atomic Lua Script  |     |  - Atomic CAS Updates |
          |  - Sub-ms Gatekeeper  |     |  - SELECT FOR UPDATE  |
          |  - Automatic TTL      |     |  - Partial Unique Idx |
          +-----------------------+     +-----------------------+
```

### 1. Atomic Lua Script Distributed Hold (`app/redis.py`)
Redis evaluates an atomic Lua script in RAM before touching PostgreSQL:
```lua
local current_status = redis.call("GET", KEYS[1])
if current_status == "CONFIRMED" then return -1 end

local acquired = redis.call("SET", KEYS[2], ARGV[1], "NX", "EX", ARGV[2])
if acquired then return 1 else return 0 end
```
* **The Shield:** When 1,000 users compete for a seat, 999 are rejected by Redis in **0.2 ms**. Only 1 query touches PostgreSQL.
* **Compensating Transactions:** If the PostgreSQL write fails, the application deletes the Redis key to prevent ghost locks.

### 2. Database Partial Unique Index (`app/models/booking.py`)
```sql
CREATE UNIQUE INDEX uq_active_seat_booking 
ON bookings (seat_id) 
WHERE status IN ('PENDING', 'CONFIRMED');
```
* Allows a seat to have dozens of historical `EXPIRED` or `CANCELLED` bookings.
* Physically blocks more than one active booking per seat at the database storage engine layer.

### 3. Stripe-Standard Payment Idempotency (`app/api/v1/payments.py`)
* Client passes `Idempotency-Key: <UUID>` header.
* Completed operations return cached JSON responses with `idempotent_replay: true`.
* Concurrent duplicate requests are rejected with `409 Conflict` (`Request in-flight`).

### 4. Background Cleaner with `SKIP LOCKED` (`app/workers/cleanup.py`)
* Runs periodically in the FastAPI lifespan to release expired holds.
* Uses `SELECT ... FOR UPDATE SKIP LOCKED` to bypass rows actively checking out, eliminating deadlock risks and user-facing latency spikes.

---

## 🛠️ Project Structure

```
SeatLock/
├── app/
│   ├── api/
│   │   ├── deps.py               # Dependency injection
│   │   └── v1/
│   │       ├── bookings.py       # Naive, Pessimistic, Atomic, Redis endpoints
│   │       ├── payments.py       # Idempotent payment processing
│   │       └── router.py         # API aggregation
│   ├── models/
│   │   ├── booking.py            # Booking model + Partial Unique Index
│   │   ├── enums.py              # SeatStatus, BookingStatus, PaymentStatus
│   │   ├── event.py              # Event model
│   │   ├── idempotency.py        # IdempotencyKey model
│   │   ├── payment.py            # Payment model
│   │   └── seat.py               # Seat model with version column
│   ├── schemas/                  # Pydantic request/response schemas
│   ├── workers/
│   │   └── cleanup.py            # Background hold expiry worker
│   ├── config.py                 # Pydantic Settings
│   ├── database.py               # SQLAlchemy 2.0 Async Session Factory
│   ├── main.py                   # FastAPI application lifespan
│   └── redis.py                  # Redis connection pool & Lua scripts
├── load_tests/
│   ├── flash_sale_k6.js          # Grafana k6 load script
│   └── run_load_test.py          # Python 1,000-request benchmark engine
├── scripts/
│   └── seed_data.py              # Database seeder (100 test seats)
├── tests/
│   ├── test_race_condition.py    # Milestone 1 & 2 concurrency showdown
│   ├── test_milestone3.py        # Payment idempotency & expiration tests
│   └── test_redis_benchmark.py   # Redis distributed hold tests
├── docker-compose.yml            # PostgreSQL 16 & Redis setup
├── requirements.txt              # Project dependencies
└── README.md
```

---

## 🚀 Quickstart Guide

### Option A: Run the Entire Stack in One Command (Docker)
No local Python or database installation needed. Clones and runs the full stack (API, PostgreSQL 16, Redis, and auto-seeding):

```bash
git clone https://github.com/<your-username>/SeatLock.git
cd SeatLock

# Build and start all services in one command
docker compose up --build
```
Interactive Swagger API documentation will be immediately live at: **`http://localhost:8000/docs`**

---

### Option B: Local Python Development
```bash
git clone https://github.com/<your-username>/SeatLock.git
cd SeatLock

# 1. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate       # On Linux/macOS
.\.venv\Scripts\activate        # On Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start PostgreSQL & Redis services via Docker
docker compose up -d postgres redis

# 4. Seed 100 test seats and start server
python -m scripts.seed_data
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
API Documentation live at: **`http://127.0.0.1:8000/docs`**


---

## 🧪 Running the Concurrency Tests

```bash
# 1. Run the Race Condition Showdown (Naive vs Pessimistic vs Atomic)
python -m tests.test_race_condition

# 2. Run Payment Idempotency & Hold Expiration Test
python -m tests.test_milestone3

# 3. Run Redis Distributed Hold Test
python -m tests.test_redis_benchmark

# 4. Run 1,000-Request Flash Sale Benchmark Engine
python -m load_tests.run_load_test

# 5. Run Grafana k6 Load Test
k6 run load_tests/flash_sale_k6.js
```

---

## 📄 License
This project is open-source and licensed under the [MIT License](LICENSE).
