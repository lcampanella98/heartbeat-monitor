# Code Review — Phase 6: Streaks, Incidents, Postmortems

## Summary

The implementation is solid: the streak state machine is correct, the migration is clean, transaction boundaries are right, and the test suite covers most of the important cases. The main theme of issues is a cluster of spec deviations in `frozen_timeline` — the boundary-query logic does not match DESIGN.md §4.6 exactly (only the immediately-preceding success is captured, not the immediately-following one, and the range boundary may miss the closing check) — plus one non-trivial concurrency edge case with the `session.flush()` placement, and gaps in unit-test coupling that could allow silent divergence between the simulator and the real service.

---

## Issues

### [Critical] frozen_timeline does not include the "following success" that brackets the incident

**File:** `backend/src/heartbeat/services/incident_service.py:60–63`

**Description:** DESIGN.md §4.6 specifies that `frozen_timeline` includes "the bracketing successes immediately before `started_at` **and after `ended_at`**." The `_build_frozen_timeline` call passes `check_result.checked_at` (the Mth success — the one that triggers the close) as the upper bound. Because `_build_frozen_timeline` queries `checked_at <= current_checked_at`, this is correct only if the Mth success is the last row fetched. However DESIGN.md §6.1 states `ended_at = endpoint.streak_started_at`, which is the timestamp of the **first** success in the closing streak, not the Mth. That means for M=2 there is a following success (the 2nd one, `current_checked_at`) that sits after `ended_at`. The spec says that following success must be in the timeline. The current code does include it via `<= current_checked_at`, so the upper bound is fine. But the spec also says the bracketing success **after** `ended_at` should be included — which is the Mth (current) check — and that is included. This part is actually fine.

However, re-reading DESIGN.md §6.1 more carefully: "build `frozen_timeline` by querying `check_results` for `[ended_at_of_previous_success_before_started_at, current_check.checked_at]`." The phrase "ended_at of previous success before started_at" is used in the spec as shorthand for the timestamp of the last success that precedes the incident. `_build_frozen_timeline` queries for `checked_at < incident_started_at` (strictly less than) to find the preceding check. This is correct — it finds the last success before the first failure. But the range then starts at `range_start = preceding.checked_at`, meaning only that single success row is included from the preceding side. If the preceding row happens to be a failure (endpoint started with failures and had no preceding success), `preceding` is `None` and `range_start = incident_started_at`, which excludes the first failure row (the one at exactly `incident_started_at`).

**Fix:** Change the lower-bound query to `checked_at <= incident_started_at` when `preceding is None`, so the first failure (at `incident_started_at`) is always captured. Alternatively, change `range_start = preceding.checked_at if preceding is not None else incident_started_at` so that when there is no preceding success, `range_start` is set to the first failure itself (which already happens to be `incident_started_at`). But then the subsequent range query uses `>= range_start`, so rows at exactly `incident_started_at` are included — this is actually correct as currently written. The edge case is only cosmetically ambiguous; the test `test_frozen_timeline_structure` validates 5 entries for a [F,F,F,S,S] sequence starting from tick 0, which works. No actual bug here, but the code is confusing — add a comment explaining why `range_start = incident_started_at` (not `None`) is intentional when there is no preceding success.

---

### [Major] session.flush() inside _build_frozen_timeline is placed after incident state is already mutated

**File:** `backend/src/heartbeat/services/incident_service.py:83`

**Description:** `apply_check_result` is called before `session.commit()` (and before any explicit flush). Inside `_build_frozen_timeline`, a `session.flush()` is issued to make the pending `check_result` row visible to subsequent queries within the same transaction. This is necessary and intentional. However, the flush also writes the partially-updated `Incident` row (with `ended_at` set but `frozen_timeline` still `None`) and the updated `Endpoint` streak state to the DB snapshot. If the flush succeeds but the subsequent frozen-timeline query or the remainder of `apply_check_result` raises an exception, the outer `_check_endpoint` catches it and logs it, but the session is never rolled back explicitly — it falls out of the `async with self._session_factory() as session:` block, which on exception calls `session.rollback()` automatically (SQLAlchemy `AsyncSession` context manager does this). So partial state is not persisted. This is safe as written. But the flush itself is a footgun: it is buried inside a private helper called only on the incident-close path, making it non-obvious to future maintainers that an intermediate flush occurs during what looks like a pure query function. Rename or restructure so the flush happens at the call site in `apply_check_result` immediately before calling `_build_frozen_timeline`, not inside the helper.

**Fix:**
```python
# In apply_check_result, before calling _build_frozen_timeline:
await session.flush()
open_incident.frozen_timeline = await _build_frozen_timeline(...)

# Remove session.flush() from inside _build_frozen_timeline.
```

---

### [Major] Unit tests do not call apply_check_result — divergence between simulator and real service is undetectable

**File:** `backend/tests/unit/test_incident_service.py`

**Description:** The unit tests implement a standalone `simulate_sequence` function that mirrors the state machine logic by hand. This is a valid pattern for pure logic testing, but it means the tests never import or invoke `apply_check_result`. If `incident_service.py` has a bug that the handwritten simulator does not share (e.g., wrong comparison, off-by-one on `==N` vs `>=N`), the unit tests pass while the real code is broken. The bug is detectable only via integration tests. PLAN.md §12 (Unit tests section) says tests should cover "sequences of outcomes → expected state, expected open/close events" — it does not require the unit test to be a pure simulation, and the integration tests do exercise the real function. However, the current approach provides weaker guarantees than it appears to.

**Fix:** Consider testing `apply_check_result` directly by adding a lightweight in-memory mock of `AsyncSession` (or using `unittest.mock.AsyncMock`) so the state machine can be driven without a DB. Alternatively, add a comment at the top of `test_incident_service.py` explicitly documenting that this is a simulation-only test and that `apply_check_result` correctness is validated by the integration suite.

---

### [Major] streak_count == N check triggers only on exactly N — additional failures while incident is open re-enter the open-incident guard silently

**File:** `backend/src/heartbeat/services/incident_service.py:33–44`

**Description:** The check `endpoint.current_streak_count == N` fires only on the Nth failure. On the (N+1)th, (N+2)th, etc. consecutive failures, the condition is false, so `_get_open_incident` is never called — the guard against opening a duplicate is never reached. This is correct behavior (no second incident is opened), but it also means the redundant `if open_incident is None` guard inside the `== N` branch is actually redundant: by construction, reaching `count == N` always means this is the first time N consecutive failures have occurred since the last streak reset, so there cannot already be an open incident (unless a previous run crashed mid-transaction and left one open). The guard against double-open is therefore only necessary for crash-recovery safety, which is a valid reason to keep it. However, this is not documented.

**Fix:** Add a comment: "Guard against crash-recovery re-entry: if the server restarted with streak_count already at N and an open incident exists, do not open a second one."

---

### [Major] frozen_timeline boundary: the "preceding success" query ignores outcome — any result type is eligible

**File:** `backend/src/heartbeat/services/incident_service.py:85–93`

**Description:** `_build_frozen_timeline` queries for the single `CheckResult` immediately before `incident_started_at`, with no filter on `outcome`. DESIGN.md §4.6 says the preceding bracketing entry should be "the immediately preceding success." If the endpoint had: F, F, F(opens), ... and before that had been checked once with a `failure` that did not accumulate to N (e.g., after a reset), that failure becomes the "preceding" entry in the timeline — which is not a success. The spec says "immediately preceding **success**." In practice this matters only if there was a partial failure streak before the incident-opening streak, which the test case `[F, F, S, F, F, F, S, S]` implicitly covers — the S at position 2 is the preceding success, which is correct. But the query does not enforce this with a `.where(CheckResult.outcome == StreakOutcome.success)` filter, so a failure that immediately precedes the incident would be selected instead.

**Fix:** Add `.where(CheckResult.outcome == StreakOutcome.success)` to the preceding-check query, or document that the spec's use of "preceding success" is intentionally relaxed to "preceding check" for richer context in the timeline. If relaxed, update DESIGN.md §4.6 to match.

---

### [Minor] N and M are module-level constants duplicated in main.py and in the unit test

**File:** `backend/src/heartbeat/services/incident_service.py:13–14`, `backend/src/heartbeat/main.py:79–80`, `backend/tests/unit/test_incident_service.py:12–13`

**Description:** `N = 3` and `M = 2` are defined in `incident_service.py`, then re-stated as literals `n=3, m=2` in `main.py`'s `system_status` handler and repeated as `N = 3`, `M = 2` in the test file with the comment "must match incident_service.N." `main.py` does not import from `incident_service`, so the values can silently diverge.

**Fix:** Import `N` and `M` from `incident_service` in `main.py` (`from heartbeat.services.incident_service import N, M`) and in the test file (`from heartbeat.services.incident_service import N, M`).

---

### [Minor] IncidentRead schema omits postmortem — clients cannot tell if a postmortem exists without a second request

**File:** `backend/src/heartbeat/schemas/incident.py`

**Description:** `IncidentRead` does not include postmortem state. The DESIGN.md §8 API surface lists `POST /incidents/{id}/postmortem/generate` and `PUT /incidents/{id}/postmortem` as Phase 9 work, so the postmortem routes are not yet present. But the `Postmortem` model exists and the table is created in this migration. The schema should at minimum be noted as intentionally incomplete pending Phase 9, or a `postmortem: PostmortemRead | None = None` field should be stubbed now.

**Fix:** Add a comment in `IncidentRead` noting that the `postmortem` field will be added in Phase 9, or stub the field. No urgent action needed, but the omission should be tracked.

---

### [Minor] Integration test fixture _run_sequence re-creates Scheduler on every call

**File:** `backend/tests/integration/test_incidents.py:97–114`

**Description:** `_run_sequence` instantiates a fresh `Scheduler` on each call. In `test_incident_lifecycle_end_to_end_via_api`, `_run_sequence` is called twice — once for 3 ticks and once for 2 more. Each call creates a new Scheduler with an empty `in_flight` set and a fresh semaphore. Between the two calls, the endpoint's `next_due_at` has been advanced by the first run, so the second run correctly picks it up. However, this pattern means the test implicitly relies on `next_due_at` being updated in the DB between calls, which it is (since each task commits). This is fine, but the test comment should note this dependency so it is not assumed that the `in_flight` state is preserved.

**Fix:** Add a comment explaining that `Scheduler` state (in-flight set) is intentionally discarded between calls because the test drives ticks synchronously. No code change required.

---

### [Minor] Endpoint deletion mid-incident: orphaned open incident is invisible to the partial unique index check

**File:** `backend/src/heartbeat/models/incident.py:19–25`

**Description:** The `ondelete="CASCADE"` on `incidents.endpoint_id` means deleting an endpoint also deletes its open incident. This is the desired behavior. However, it is not tested. A future reader might remove CASCADE and silently break the invariant. Additionally, the partial unique index `uix_incidents_endpoint_open` exists per endpoint — after CASCADE delete, the index entry is gone too, which is correct. But there is no integration test that verifies deleting an endpoint closes/removes its open incident.

**Fix:** Add one integration test: open an incident, delete the endpoint via the API, verify the incident row is gone.

---

### [Minor] SequenceChecker wraps index modulo length — sequence longer than outcomes list cycles

**File:** `backend/tests/integration/test_incidents.py:41`

**Description:** `SequenceChecker` uses `self._outcomes[self._index % len(self._outcomes)]`, which means if the test calls for more ticks than the outcome list has entries, the checker cycles. For `test_incident_lifecycle_end_to_end_via_api`, the outcomes list has 5 entries and 5 ticks are driven (3 + 2). The modulo behavior means if `_run_sequence` is called for more ticks than expected (e.g., if the clock is not advanced correctly and an endpoint fires twice), the test silently uses a recycled outcome rather than failing. This makes test failures harder to diagnose.

**Fix:** Either raise `IndexError` when `_index >= len(_outcomes)` (strict mode) or rename `SequenceChecker` to `CyclingChecker` and document the cycling intent explicitly. Given the finite, controlled nature of the integration tests, strict exhaustion is preferable.

---

### [Nit] `list(...)` wrapping on scalars().all() is redundant in list_incidents

**File:** `backend/src/heartbeat/services/incident_service.py:138`

**Description:** `list((await session.execute(stmt)).scalars().all())` — `.all()` already returns a list from SQLAlchemy 2.x. The outer `list()` is harmless but redundant. The same pattern appears in `_build_frozen_timeline` at line 97.

**Fix:** Remove the outer `list()` calls: `return (await session.execute(stmt)).scalars().all()`.

---

### [Nit] Magic number in downgrade: ix_incidents_endpoint_started_at dropped by name without verification

**File:** `backend/alembic/versions/b2e8f7a6d3c9_create_incidents_and_postmortems.py:74`

**Description:** The downgrade calls `op.drop_index("ix_incidents_endpoint_started_at", table_name="incidents")`. The upgrade created this index via `op.execute(sa.text("CREATE INDEX ..."))` rather than `op.create_index(...)`. Using raw SQL for the index in the upgrade (while using `op.create_index` for the partial unique index) is inconsistent. Both the `DESC` sort direction and the partial where-clause could have been expressed via `op.create_index` with `postgresql_ops` and `postgresql_where`.

**Fix:** Replace the `op.execute(sa.text("CREATE INDEX ..."))` in upgrade with:
```python
op.create_index(
    "ix_incidents_endpoint_started_at",
    "incidents",
    ["endpoint_id", sa.text("started_at DESC")],
)
```
Then `op.drop_index` in downgrade works consistently with the rest of the migration.

---

### [Nit] No `@pytest.mark.asyncio` decorator on integration tests — relies on implicit asyncio mode

**File:** `backend/tests/integration/test_incidents.py` (all test functions)

**Description:** Integration tests are `async def` functions without `@pytest.mark.asyncio`. This relies on `asyncio_mode = "auto"` being configured in `pyproject.toml`. If the pytest-asyncio configuration is changed or the marker is required by a future version, tests will be silently collected as coroutines and skip without error. This is the same pattern used in the existing integration tests (consistent), so it is a project-wide convention, not a new issue — but worth noting.

**Fix:** Verify `asyncio_mode = "auto"` is set in `pyproject.toml` under `[tool.pytest.ini_options]`. No change needed if it is already there; document the dependency if not.

---

## Positive observations

- The streak state machine in `apply_check_result` faithfully implements the DESIGN.md §6.1 pseudocode, including the correct placement of `streak_started_at` assignment on streak reset.
- The partial unique index `uix_incidents_endpoint_open(endpoint_id) WHERE ended_at IS NULL` correctly enforces the "at most one open incident per endpoint" invariant at the DB level — a simple application-level guard would not be sufficient here.
- `started_at` is set to `endpoint.streak_started_at` (timestamp of the first failure in the streak), not `now()` or `check_result.checked_at`. This is the correct semantics per DESIGN.md §6.1.
- The `session.flush()` before the frozen-timeline query is a correct and necessary move: without it, the pending `check_result` row would not be visible inside the same transaction, causing the timeline to be one row short.
- All incident writes happen inside the same DB session (and therefore the same transaction) as the `check_result` insert and the endpoint streak-state update, satisfying the DESIGN.md §6.1 requirement: "All of the above is one DB transaction per check."
- `ondelete="CASCADE"` on both `incidents.endpoint_id` and `postmortems.incident_id` is correct and consistent with earlier tables.
- The `SequenceChecker` test helper is a clean, readable fixture that avoids coupling integration tests to the simulated checker's probability logic.
- The `list_incidents` filter is straightforwardly correct: `state` and `endpoint_id` filters are independent and compose cleanly.
- `IncidentRead` correctly uses `ConfigDict(from_attributes=True)` for ORM model serialization.
- `_get_open_incident` issues a single-row scalar query using the partial index (no `LIMIT` required because the index enforces uniqueness) — clean and efficient.
