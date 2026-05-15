# Code Review — Phase 4: Checker interface and implementations

Files reviewed:
- `backend/src/heartbeat/checker/__init__.py`
- `backend/src/heartbeat/checker/real.py`
- `backend/src/heartbeat/checker/simulated.py`
- `backend/src/heartbeat/dependencies.py`
- `backend/src/heartbeat/main.py` (lifespan changes)
- `backend/tests/unit/test_real_checker.py`
- `backend/tests/unit/test_simulated_checker.py`

---

## Bugs / Must Fix

### 1. `http_client` always created in simulated mode (`main.py:25–36`)

An `httpx.AsyncClient` is constructed unconditionally, before the `if/else` that decides which checker to build. In simulated mode, the client is created, never passed anywhere, and then closed on shutdown. This allocates a connection pool that is never used.

```python
# current — always allocates
http_client = httpx.AsyncClient(...)
if settings.check_source == "real":
    app.state.checker = RealChecker(http_client=http_client, ...)
else:
    app.state.checker = SimulatedChecker(...)   # client discarded

yield
await http_client.aclose()   # closes a pool that never opened a connection
```

Fix: construct the client only when `check_source == "real"`.

```python
http_client: httpx.AsyncClient | None = None
if settings.check_source == "real":
    http_client = httpx.AsyncClient(
        follow_redirects=True,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    app.state.checker = RealChecker(http_client=http_client, clock=clock)
    logger.info("Checker: real (live HTTP requests)")
else:
    app.state.checker = SimulatedChecker(clock=clock, rng=random.Random())
    logger.info("Checker: simulated (no outbound HTTP)")

yield

if http_client is not None:
    await http_client.aclose()
await engine.dispose()
```

This matters most for the demo path (`CHECK_SOURCE=simulated`), which is the primary showcase mode.

---

### 2. `_clock` stored but never used in `RealChecker` (`real.py:13–15`)

`RealChecker.__init__` accepts `clock: Clock` and assigns `self._clock = clock`, but `self._clock` is never referenced anywhere in the class. The design spec includes clock in the signature (presumably for `checked_at` timestamps), but `CheckOutcome` has no `checked_at` field, so there is currently no use for it.

Storing a reference that is never used is misleading dead code and will confuse Phase 5 implementers who may wonder whether to rely on it. Two options:

- **Remove the parameter** if it truly has no role in Phase 4. Add it back in Phase 5 if it turns out to be needed.
- **Keep it but document why** with a short comment (e.g., reserved for Phase 5 `checked_at` stamping).

Either is acceptable; the current state — present, stored, silent — is the worst of both.

---

### 3. Dead `run()` function in `test_deterministic_with_same_seed` (`test_simulated_checker.py:112–118`)

```python
async def test_deterministic_with_same_seed():
    def run(seed: int) -> tuple:            # defined but never called
        checker = SimulatedChecker(...)
        import asyncio
        outcome = asyncio.get_event_loop().run_until_complete(checker.check(endpoint))
        ...

    r1 = SimulatedChecker(clock=FakeClock(_NOON), rng=random.Random(7))
    ...
```

`run()` is left over from an earlier draft and is never called. Beyond being dead code, if it were ever invoked, `asyncio.get_event_loop().run_until_complete()` inside an already-running async test would raise `RuntimeError: This event loop is already running`. Delete lines 112–118.

---

## Issues / Should Fix

### 4. Midnight-spanning outage windows silently produce wrong results (`simulated.py:21–23`)

The window check `start <= current < end` assumes `start < end`. A window like `{"start": "23:00", "end": "01:00"}` produces the comparison `23:00 <= current < 01:00`, which is always False because `01:00 < 23:00` in Python's `time` ordering.

The schema validator in Phase 3 does not validate outage window structure at all — `sim_outage_windows` is stored as opaque JSONB. A user who configures a midnight-crossing window will see no error and no outage, with no indication that anything is wrong.

For the MVP, the simplest mitigation is a validator on `EndpointCreate`/`EndpointUpdate` that rejects windows where `start >= end`. This makes the constraint explicit rather than a silent footgun. The DESIGN.md already states windows are "time-of-day" intervals without addressing midnight — update the spec note to explicitly say crossing midnight is not supported.

---

### 5. `__cause__`-based TLS and DNS detection is untested (`real.py:51–62`)

The two `isinstance` checks — `isinstance(cause, ssl.SSLError)` and `isinstance(cause, socket.gaierror)` — are never exercised by the test suite. All tests reach the correct category only through message-string matching. If the message-based path were removed or modified, the `isinstance` path would remain silently broken.

Add two tests that set `__cause__` correctly:

```python
async def test_tls_error_by_cause():
    exc = httpx.ConnectError("", request=_REQ)
    exc.__cause__ = ssl.SSLError("CERTIFICATE_VERIFY_FAILED")
    outcome = await _make_checker(exc=exc).check(_FakeEndpoint())
    assert outcome.error_category == ErrorCategory.tls

async def test_dns_error_by_cause():
    exc = httpx.ConnectError("", request=_REQ)
    exc.__cause__ = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    outcome = await _make_checker(exc=exc).check(_FakeEndpoint())
    assert outcome.error_category == ErrorCategory.dns
```

---

### 6. Unnecessary defensive check in `SimulatedChecker.check` (`simulated.py:36`)

```python
if _in_outage_window(now, endpoint.sim_outage_windows or []):
```

`sim_outage_windows` is `nullable=False` with `server_default='[]'::jsonb` on the model. It cannot be `None` when loaded from the database. The `or []` guard defends against a case that can't happen, which CLAUDE.md standard #1 explicitly prohibits ("no unnecessary defensive programming"). Remove the guard:

```python
if _in_outage_window(now, endpoint.sim_outage_windows):
```

---

### 7. Spurious quotes on `error_category` annotation in `CheckOutcome` (`checker/__init__.py:23`)

```python
error_category: "ErrorCategory | None"
```

`ErrorCategory` is defined in the same file, six lines above. The forward-reference string is unnecessary and inconsistent with the other field annotations. Use the bare type:

```python
error_category: ErrorCategory | None
```

---

## Observations / Nice to Have

### 8. `test_latency_always_non_negative` is a low-signal assertion (`test_real_checker.py:114–116`)

`latency_ms = int(...)` can only be zero or positive; the test can never fail. The assertion would be more meaningful if it bounded latency in context (e.g., `< 500` for a stub that returns instantly). As written it documents nothing useful. Consider removing it or strengthening it.

---

### 9. `test_always_success_with_zero_failure_rate` runs 20 iterations unnecessarily (`test_simulated_checker.py:29–36`)

With `failure_rate=0.0`, the outcome is deterministic — no RNG roll is made. The loop provides no additional coverage and runs 20× slower than a single call. One assertion suffices.

---

### 10. `_FakeEndpoint` in `test_real_checker.py` uses class-level attributes (`test_real_checker.py:15–17`)

```python
class _FakeEndpoint:
    url = "http://example.com"
    timeout_seconds = 10
```

`test_simulated_checker.py` uses `__init__` with instance attributes. The inconsistency is harmless but makes the real-checker stub less flexible (can't vary URL or timeout per test without subclassing). Not worth changing just for consistency, but if a Phase 5 test needs a varying URL or timeout in a `RealChecker` unit test, remember to update this stub.

---

## Summary

| # | Severity | File | Description |
|---|----------|------|-------------|
| 1 | Must fix | `main.py` | `http_client` allocated in simulated mode and immediately discarded |
| 2 | Must fix | `real.py` | `_clock` stored but never used — dead code |
| 3 | Must fix | `test_simulated_checker.py` | Dead `run()` function with a latent `run_until_complete` bug |
| 4 | Should fix | `simulated.py` + schema | Midnight-spanning windows silently fail; needs validation or documentation |
| 5 | Should fix | `test_real_checker.py` | `__cause__` code paths for TLS/DNS detection are untested |
| 6 | Should fix | `simulated.py` | Unnecessary `or []` defensive check on non-nullable field |
| 7 | Should fix | `checker/__init__.py` | Spurious forward-reference quotes on `error_category` annotation |
| 8 | Nice to have | `test_real_checker.py` | `test_latency_always_non_negative` cannot fail; low value |
| 9 | Nice to have | `test_simulated_checker.py` | 20-iteration loop where 1 iteration would suffice |
| 10 | Nice to have | `test_real_checker.py` | Class-level vs. instance-level stub inconsistency |

Issues 1, 2, and 3 should be fixed before Phase 5 starts. Issues 4–7 should be fixed in this phase (they are correctness or coverage gaps, not just style). Issues 8–10 can be deferred.
