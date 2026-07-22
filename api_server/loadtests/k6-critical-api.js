import http from "k6/http";
import { check, sleep } from "k6";

const baseUrl = (__ENV.BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const accessToken = __ENV.ACCESS_TOKEN || "";

export const options = {
  scenarios: {
    critical_reads: {
      executor: "constant-arrival-rate",
      rate: Number(__ENV.REQUEST_RATE || 20),
      timeUnit: "1s",
      duration: __ENV.DURATION || "60s",
      preAllocatedVUs: Number(__ENV.PREALLOCATED_VUS || 20),
      maxVUs: Number(__ENV.MAX_VUS || 100),
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<750", "p(99)<1500"],
    checks: ["rate>0.99"],
  },
};

export default function () {
  const ready = http.get(`${baseUrl}/api/health/ready`, {
    tags: { endpoint: "readiness" },
  });
  check(ready, { "readiness is 200": (response) => response.status === 200 });

  if (!accessToken) {
    sleep(0.05);
    return;
  }

  const headers = { Authorization: `Bearer ${accessToken}` };
  const settings = http.get(`${baseUrl}/api/account/settings`, {
    headers,
    tags: { endpoint: "settings" },
  });
  check(settings, {
    "settings is 200": (response) => response.status === 200,
    "settings exposes revision": (response) => Boolean(response.headers.ETag),
  });

  if (settings.headers.ETag) {
    const cached = http.get(`${baseUrl}/api/account/settings`, {
      headers: { ...headers, "If-None-Match": settings.headers.ETag },
      tags: { endpoint: "settings-conditional" },
    });
    check(cached, { "unchanged settings is 304": (response) => response.status === 304 });
  }

  const history = http.get(
    `${baseUrl}/api/account/history/page?page_size=50&fields=id,jobPosition,updatedAt`,
    { headers, tags: { endpoint: "history-page" } },
  );
  check(history, { "history page is 200": (response) => response.status === 200 });
}
