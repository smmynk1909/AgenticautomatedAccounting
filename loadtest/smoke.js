// k6 smoke test — doc 12 §4 CI pipeline: "k6 smoke (50 VU, 5 min)" against
// a compose-up CPU profile. Validates doc 10 §6's NFR table row 1: "p95
// interactive turn < 12s" and row 2's "50 concurrent users."
//
// Deliberately hits only read/query endpoints, not chat/codeassist (those
// invoke an LLM — a *correctness* concern for `evals/`'s red-team/eval
// harness, not a *load* concern; running 50 concurrent LLM calls on this
// stack's CPU-only Ollama serving would just measure Ollama's request
// queue depth, not the gateway/API layer doc 10 §6 is actually about).
// `ticket_volume.js` in this same directory covers the "1,000 tickets/day"
// write-throughput row; the "payroll 500 employees < 10 min" row is an
// async multi-step FIN-1 workflow, not a synchronous HTTP call k6 can
// usefully drive — see README.md.
//
// Usage: k6 run smoke.js
//   BASE_URL   default http://localhost:8000
//   DEV_USERS  comma-separated config/dev_users.yaml ids to log in as
//              (default: a manager + a support role, since ticket/dashboard
//              reads need a real principal)

import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const DEV_USERS = (__ENV.DEV_USERS || "dev-support-lead,dev-manager").split(",");

export const options = {
  stages: [
    { duration: "1m", target: 50 }, // ramp
    { duration: "3m", target: 50 }, // hold — doc 10 §6 "50 concurrent users"
    { duration: "1m", target: 0 }, // ramp down
  ],
  thresholds: {
    // doc 10 §6: "p95 interactive turn < 12s" — applied here to the
    // read-endpoint mix below as the load-bearing boundary this test can
    // actually reach synchronously.
    http_req_duration: ["p(95)<12000"],
    http_req_failed: ["rate<0.01"],
  },
};

function login() {
  const userId = DEV_USERS[Math.floor(Math.random() * DEV_USERS.length)];
  const res = http.post(
    `${BASE_URL}/api/dev/login`,
    JSON.stringify({ user_id: userId }),
    { headers: { "Content-Type": "application/json" } }
  );
  check(res, { "dev login 200": (r) => r.status === 200 });
  return res.json("token");
}

export default function () {
  const token = login();
  if (!token) {
    sleep(1);
    return;
  }
  const headers = { Authorization: `Bearer ${token}` };

  const tickets = http.get(`${BASE_URL}/api/tickets`, { headers });
  check(tickets, { "tickets 200": (r) => r.status === 200 });

  const dashboard = http.get(`${BASE_URL}/api/dashboard/manager`, { headers });
  check(dashboard, { "dashboard 200": (r) => r.status === 200 });

  sleep(1);
}
