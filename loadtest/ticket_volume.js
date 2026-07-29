// k6 sustained write-throughput test — doc 10 §6's NFR table row 2:
// "1,000 tickets/day." That's ~0.012 tickets/sec average — far too low a
// rate to meaningfully load-test on its own (any working system clears
// it trivially). This scenario instead runs a constant-arrival-rate test
// at a rate scaled well above the literal daily average, for a short
// window, to answer the question the NFR actually implies: can the
// system absorb a full day's ticket volume comfortably, including
// bursts, not just the flat average. Read `RATE_PER_SEC`/`DURATION`
// below before treating the pass/fail as a literal 24h claim.
//
// Usage: k6 run ticket_volume.js
//   BASE_URL   default http://localhost:8000
//   DEV_USER   default dev-employee (config/dev_users.yaml id)

import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const DEV_USER = __ENV.DEV_USER || "dev-employee";

// 1,000/day = ~0.0116/s average. Scaled to 10x for a 5-minute burst check
// (this is a burst/soak proxy, not a literal day-long run — see header).
const RATE_PER_SEC = 0.116;

export const options = {
  scenarios: {
    ticket_creation: {
      executor: "constant-arrival-rate",
      rate: Math.max(1, Math.round(RATE_PER_SEC * 60)), // k6 rate is per `timeUnit`
      timeUnit: "1m",
      duration: "5m",
      preAllocatedVUs: 5,
      maxVUs: 20,
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<12000"], // doc 10 §6 interactive-turn NFR
    http_req_failed: ["rate<0.01"],
  },
};

export function setup() {
  const res = http.post(
    `${BASE_URL}/api/dev/login`,
    JSON.stringify({ user_id: DEV_USER }),
    { headers: { "Content-Type": "application/json" } }
  );
  check(res, { "dev login 200": (r) => r.status === 200 });
  return { token: res.json("token") };
}

export default function (data) {
  const headers = {
    Authorization: `Bearer ${data.token}`,
    "Content-Type": "application/json",
  };
  const res = http.post(
    `${BASE_URL}/api/tickets`,
    JSON.stringify({ channel: "web", category: "device", priority: "P3" }),
    { headers }
  );
  check(res, { "create_ticket 200": (r) => r.status === 200 });
}
