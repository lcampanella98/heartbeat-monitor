# Code Review — Phase 5: check_results + scheduler

**Files reviewed:**
- `backend/src/heartbeat/models/check_result.py`
- `backend/src/heartbeat/checker/__init__.py`
- `backend/src/heartbeat/scheduler.py`
- `backend/src/heartbeat/schemas/check_result.py`
- `backend/src/heartbeat/api/endpoints.py` (recent-checks addition)
- `backend/src/heartbeat/main.py` (lifespan changes)
- `backend/alembic/versions/3e8a5f2b9c01_create_check_results.py`
- `backend/tests/integration/test_scheduler.py`

---

## Overview

Phase 5 adds the `check_results` persistence layer, the async scheduler loop, and a
`GET /api/v1/endpoints/{id}/recent-checks` route. The core design — `in_flight` set,
semaphore-gated HTTP/sim calls, `tick()` returning spawned tasks for test-drivability —
is sound and follows the DESIGN.md spec. All 99 tests pass.

---

## Issues

### 1. Redundant `ErrorCategory` value conversion (bug)

**File:** `scheduler.py:92-94`

```python
error_cat: ErrorCategory | None = None
if outcome.error_category is not None:
    error_cat = ErrorCategory(outcome.error_category.value)
```

`checker/__init__.py` now imports `ErrorCategory` directly from
`models.check_result`, so `outcome.error_category` is already an instance of the
same `ErrorCategory` class used in the model. The `.value` round-trip is dead code
and misleads the reader into thinking the two types are different.

**Fix:**
```python
error_cat = outcome.error_category
```

---

### 2. Import order suppression in `checker/__init__.py`

**File:** `checker/__init__.py:7`

```python
if TYPE_CHECKING:
    from heartbeat.models.endpoint import Endpoint

from heartbeat.models.check_result import ErrorCategory  # noqa: E402
```

The `# noqa: E402` suppresses a valid import-order warning rather than fixing the
root cause. The runtime import of `ErrorCategory` should come before the
`TYPE_CHECKING` guard, not after it.

**Fix:**
```python
from heartbeat.models.check_result import ErrorCategory

if TYPE_CHECKING:
    from heartbeat.models.endpoint import Endpoint
```

No `noqa` needed; this is the idiomatic ordering.

---

### 3. `CheckResult` model missing `__table_args__` index

**File:** `models/check_result.py`

The `(endpoint_id, checked_at DESC)` index is created in the migration via raw SQL
(`op.execute("CREATE INDEX ...")`) but is not declared in the model's
`__table_args__`. Every other indexed model in this codebase (`Endpoint`) declares
its indexes there.

The mismatch means:
- Future `alembic revision --autogenerate` runs may detect the index as "missing"
  from the metadata and emit a spurious migration.
- The model does not document its own index structure.

**Fix:** Declare the index in `__table_args__` using SQLAlchemy's descending support
and keep the raw-SQL approach in the migration only as the creation mechanism:

```python
__table_args__ = (
    Index(
        "ix_check_results_endpoint_checked_at",
        "endpoint_id",
        sa.text("checked_at DESC"),
    ),
)
```

---

### 4. DB query inline in route handler

**File:** `api/endpoints.py:88-93`

```python
result = await session.execute(
    select(CheckResult)
    .where(CheckResult.endpoint_id == endpoint_id)
    .order_by(desc(CheckResult.checked_at))
    .limit(limit)
)
```

All other query logic in this project goes through `services/`. Inlining the query
in the router creates an inconsistency that will grow more awkward as Phase 6 adds
streak/incident logic that needs `check_results`.

**Fix:** Extract to `services/check_result_service.py`:
```python
async def get_recent_checks(
    session: AsyncSession, endpoint_id: int, limit: int
) -> list[CheckResult]: ...
```

---

### 5. `tick()` return type uses unnecessary string forward-reference

**File:** `scheduler.py:52`

```python
async def tick(self) -> set["asyncio.Task[None]"]:
```

`asyncio` is imported at the top of the module, so `asyncio.Task[None]` is
available without quoting.

**Fix:**
```python
async def tick(self) -> set[asyncio.Task[None]]:
```

---

### 6. Redundant `max()` in test assertion

**File:** `tests/integration/test_scheduler.py:133`

```python
expected = max(_FIXED_NOW + timedelta(seconds=interval), _FIXED_NOW)
```

`_FIXED_NOW + timedelta(seconds=60) > _FIXED_NOW` is always true, so the `max()`
always returns the first operand. The expression tests the scheduler's formula
correctly but obscures intent — a reader must evaluate the inequality mentally to
understand which branch fires.

**Fix:**
```python
expected = _FIXED_NOW + timedelta(seconds=interval)
```

---

### 7. Two sessions opened where one suffices

**File:** `tests/integration/test_scheduler.py:97-108`

```python
async with session_factory() as session:
    count = await session.scalar(...)
assert count == 3

async with session_factory() as session:
    rows = (await session.execute(...)).scalars().all()
```

Both reads happen in `test_tick_inserts_check_results_for_due_endpoints`. A single
session can serve both, reducing connection overhead.

---

## Design observations (not issues)

**Session held open across checker execution.** `_check_endpoint` opens a single
session, fetches the endpoint, acquires the semaphore, runs the check (up to
`timeout_seconds`), then writes results — all within the same session context. For
real checks at a 10 s timeout and 50 concurrent slots, this can hold 50 idle
asyncpg connections for up to 10 s. Acceptable for the MVP's single-process scope;
worth revisiting if connection pool pressure appears in Phase 10 stress testing.

**`ErrorCategory` lives in `models.check_result`.** Moving it there (with the
checker importing it back) creates a `checker → models` runtime dependency. The
alternative — keeping it in `checker/__init__.py` and importing into the model —
would invert to `models → checker`, which is arguably worse. A neutral third option
(`heartbeat/enums.py`) would eliminate the coupling entirely and is worth considering
when more cross-layer shared types accumulate.

**`app.state.checker` set but no route reads it yet.** Stored for Phase 6+ use.
No action needed.

---

## Summary

| # | Severity | File | Finding |
|---|----------|------|---------|
| 1 | Bug | `scheduler.py` | Redundant `ErrorCategory` value round-trip |
| 2 | Medium | `checker/__init__.py` | Import order / noqa suppression |
| 3 | Medium | `models/check_result.py` | Index absent from `__table_args__` |
| 4 | Medium | `api/endpoints.py` | DB query bypasses service layer |
| 5 | Minor | `scheduler.py` | Unnecessary string in return type annotation |
| 6 | Minor | `test_scheduler.py` | Redundant `max()` in test assertion |
| 7 | Minor | `test_scheduler.py` | Two sessions where one would do |
