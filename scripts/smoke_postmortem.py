"""Smoke test for Phase 9: AI postmortem generation.

Runs against a live backend at http://localhost:8000. The backend must be up
with CHECK_SOURCE=simulated and OPENROUTER_API_KEY set.

Usage (from the repo root):
    python scripts/smoke_postmortem.py
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api/v1"


def api(method, path, data=None):
    url = BASE + path
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def poll(fn, label, timeout=180, interval=5):
    print(f"  waiting: {label}", flush=True)
    deadline = time.time() + timeout
    dots = 0
    while time.time() < deadline:
        result = fn()
        if result:
            print()
            return result
        print(".", end="", flush=True)
        dots += 1
        if dots % 20 == 0:
            print()
        time.sleep(interval)
    print()
    raise TimeoutError(f"Timed out after {timeout}s waiting for: {label}")


def main():
    print("=== Phase 9 smoke test: AI postmortem generation ===\n")

    status, body = api("GET", "/system/status")
    if status != 200:
        print(f"Backend not reachable at {BASE} (status {status}). Is the stack running?")
        sys.exit(1)
    print(f"Backend: check_source={body['check_source']}, email_sink={body['email_sink']}")
    if body["check_source"] != "simulated":
        print("Note: check_source=real — real HTTP requests will be made to the test endpoint URL.")

    # 1. Create endpoint with 100% failure rate, shortest interval
    status, ep = api(
        "POST",
        "/endpoints",
        {
            "name": "Smoke Test — Phase 9",
            "url": "https://smoke-test.invalid/health",
            "check_interval_seconds": 30,
            "timeout_seconds": 10,
            "sim_failure_rate": 1.0,
            "sim_latency_min_ms": 50,
            "sim_latency_max_ms": 150,
        },
    )
    if status != 201:
        print(f"Failed to create endpoint: {ep}")
        sys.exit(1)
    ep_id = ep["id"]
    print(f"Created endpoint id={ep_id} (30s interval, 100% failure rate)\n")

    try:
        # 2. Wait for incident to open (needs N=3 consecutive failures)
        def incident_open():
            _, incidents = api("GET", f"/incidents?endpoint_id={ep_id}&state=active")
            return incidents[0] if incidents else None

        print(f"Step 1/3: waiting for incident to open (N=3 failures at 30s interval, ~90s)")
        incident = poll(incident_open, "active incident")
        incident_id = incident["id"]
        print(f"  Incident {incident_id} opened at {incident['started_at']}")

        # 3. Set failure rate to 0 so the incident closes
        status, _ = api("PUT", f"/endpoints/{ep_id}", {"sim_failure_rate": 0.0})
        if status != 200:
            print("Failed to update endpoint failure rate")
            sys.exit(1)
        print("\nStep 2/3: set failure rate to 0% — waiting for incident to close (M=2 successes, ~60s)")

        def incident_closed():
            _, inc = api("GET", f"/incidents/{incident_id}")
            return inc if inc.get("ended_at") else None

        incident = poll(incident_closed, "incident closed")
        tl_len = len(incident["frozen_timeline"]) if incident["frozen_timeline"] else 0
        print(f"  Incident closed at {incident['ended_at']}")
        print(f"  Duration: {incident['duration_seconds']}s, frozen_timeline: {tl_len} entries")

        # 4. Generate postmortem
        print("\nStep 3/3: generating postmortem via OpenRouter...")
        status, pm = api("POST", f"/incidents/{incident_id}/postmortem/generate")
        if status == 503:
            print(
                "ERROR 503: OPENROUTER_API_KEY is not set in the running container.\n"
                "  Add it to .env and rebuild: scripts/start.ps1"
            )
            sys.exit(1)
        elif status == 502:
            print(f"ERROR 502: upstream AI error — {pm.get('detail')}")
            sys.exit(1)
        elif status != 200:
            print(f"ERROR {status}: {pm}")
            sys.exit(1)

        print(f"\n{'=' * 60}")
        print("POSTMORTEM DRAFT")
        print("=" * 60)
        print(pm["content"])
        print("=" * 60)
        print(f"\ngenerated_at : {pm['generated_at']}")
        print(f"edited_at    : {pm['edited_at']}")
        print("\nSmoke test PASSED.")

    finally:
        api("DELETE", f"/endpoints/{ep_id}")
        print(f"\n(Cleaned up endpoint {ep_id})")


if __name__ == "__main__":
    main()
