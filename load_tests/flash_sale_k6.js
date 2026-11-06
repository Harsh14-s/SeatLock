import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

// Custom Metrics for SeatLock Flash Sale
export const successfulBookings = new Counter('successful_bookings_201');
export const conflictRejections = new Counter('conflict_rejections_409');
export const errorRate = new Rate('unexpected_errors');
export const bookingLatency = new Trend('booking_latency_ms');

export const options = {
  scenarios: {
    flash_sale_spike: {
      executor: 'per-vu-iterations',
      vus: 50,              // 50 concurrent virtual users
      iterations: 20,       // 20 requests per VU = 1,000 total requests
      maxDuration: '30s',
    },
  },
  thresholds: {
    // 95% of requests must complete under 200ms
    http_req_duration: ['p(95)<200'],
    // Unexpected errors (not 201 or 409) must be 0%
    unexpected_errors: ['rate<0.01'],
  },
};

const BASE_URL = 'http://127.0.0.1:8000/api/v1';

export default function () {
  // 1,000 requests compete randomly for 100 seats (Seats 1 to 100)
  const seatId = Math.floor(Math.random() * 100) + 1;
  const userId = `k6_user_${__VU}_${__ITER}`;

  const payload = JSON.stringify({
    seat_id: seatId,
    user_id: userId,
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
    },
  };

  const startTime = Date.now();
  // Target the Redis-backed distributed hold endpoint
  const res = http.post(`${BASE_URL}/bookings/redis-hold`, payload, params);
  const latency = Date.now() - startTime;
  bookingLatency.add(latency);

  if (res.status === 201) {
    successfulBookings.add(1);
    check(res, { 'seat booked': (r) => r.status === 201 });
  } else if (res.status === 409) {
    conflictRejections.add(1);
    check(res, { 'contention conflict': (r) => r.status === 409 });
  } else {
    errorRate.add(1);
    check(res, { 'unexpected status': (r) => false });
  }
}
