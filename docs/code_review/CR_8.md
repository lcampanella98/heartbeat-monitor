# Code Review: Phase 8 — Rollups, Retention, History/Uptime Services, Storage API

**Reviewer:** Claude Code  
**Date:** 2026-05-16  
**Branch:** main (commit 8f2982d baseline)  
**Files reviewed:** `rollup.py`, `models/hourly_rollup.py`, `models/daily_rollup.py`, `alembic/versions/d4e6b8f0a2c5_create_rollups.py`, `services/history_service.py`, `services/uptime_service.py`, `schemas/history.py`, `schemas/storage.py`, `api/storage.py`, `api/endpoints.py` (history/uptime routes), `dependencies.py`, `main.py`, `tests/unit/test_rollup.py`, `tests/integration/test_rollup.py`

---

## 1. Correctness

### 1.1 Hourly rollup `bucket_start` truncation

The SQL `date_trunc('hour', checked_at)` in `_HOURLY_UPSERT` operates on a `TIMESTAMPTZ` column. PostgreSQL's `date_trunc` on `TIMESTAMPTZ` always truncates in UTC, which matches DESIGN.md §4.4. No issue.

### 1.2 Daily rollup `bucket_date` derivation

```sql
(bucket_start AT TIME ZONE 'UTC')::date AS bucket_date
```

`bucket_start` is a `TIMESTAMPTZ`. `AT TIME ZONE 'UTC'` converts it to a `TIMESTAMP` (no timezone) in UTC, then `::date` extracts the UTC date. A bucket at `2025-06-01 23:00:00+00` correctly becomes date `2025-06-01`, not `2025-06-02`. The cast is belt-and-suspenders but unambiguous. No issue.

### 1.3 `uptime_pct` division guard

Both SQL queries use `nullif(count(*), 0)` / `nullif(sum(total_checks), 0)` in the denominator. `NULLIF` returns `NULL` when the denominator is zero, which propagates through `round()` to produce `NULL`. Inserting `NULL` into a `NOT NULL` column would raise an `IntegrityError` from inside a background task.

In practice this path cannot be reached via the normal aggregation path — a `GROUP BY` group always has `count(*) >= 1`, and every `hourly_rollups` row already has `total_checks >= 1`. However, if a future migration or test helper inserts a rollup row with `total_checks=0`, the next `run_once()` will fail with a confusing error.

**[CONSIDER]** Add `COALESCE(..., 0)` around the division result, or a `HAVING count(*) > 0` guard, to make the invariant explicit.

### 1.4 Retention cutoff boundary

`DELETE FROM check_results WHERE checked_at < :cutoff` — a row exactly at `now - 30 days` is **not** deleted (`<`, not `<=`). DESIGN.md says "30 days" without specifying the boundary. The safe, conventional choice. No issue.

### 1.5 `history_service` daily query uses `since.date()`

```python
DailyRollup.bucket_date >= since.date()
```

`since` is derived from `clock.now()`, which is always UTC-aware per DESIGN.md §5.1. Python's `datetime.date()` on a UTC-aware datetime returns the UTC date, which matches how `bucket_date` is derived in the SQL. Consistent. No issue.

### 1.6 `HistoryBin.bucket_start` for daily bins

```python
bucket_start=datetime(
    r.bucket_date.year, r.bucket_date.month, r.bucket_date.day,
    tzinfo=now.tzinfo,
)
```

`now.tzinfo` is `timezone.utc`, so every daily bin's `bucket_start` is midnight UTC — a reasonable and internally consistent representation. The `source: "daily"` field signals to the frontend not to treat sub-day precision as meaningful. No issue for the MVP.

---

## 2. Design Conformance

### 2.1 Tier routing thresholds

All six named ranges map to the correct tier per DESIGN.md §7.1:

| Range | Expected | Actual |
|---|---|---|
| `1h` | raw | raw ✓ |
| `1d` | raw | raw ✓ |
| `7d` | hourly | hourly ✓ |
| `30d` | daily | daily ✓ |
| `90d` | daily | daily ✓ |
| `1y` | daily | daily ✓ |

No issue.

### 2.2 Route paths

All routes conform to DESIGN.md §8:
- `GET /endpoints/{id}/history?range=...` ✓
- `GET /endpoints/{id}/uptime` → `{h24, d7, d30}` ✓
- `GET /storage/stats` ✓
- `POST /storage/rollup-now` ✓

### 2.3 `daily_rollups` indefinite retention

DESIGN.md §4.5: indefinite retention. `run_once()` has no DELETE targeting `daily_rollups`. Correct.

### 2.4 Unique constraints as query indexes

The unique constraints `uq_hourly_rollups_endpoint_bucket` and `uq_daily_rollups_endpoint_date` are implemented as unique indexes in PostgreSQL. Both history and uptime queries use `WHERE endpoint_id = $1 AND bucket_start >= $2` — PostgreSQL will range-scan the unique index on the `(endpoint_id, bucket_start)` prefix. No additional indexes are needed. No issue.

### 2.5 `StorageStats` does not expose daily retention

`StorageStats` exposes `raw_retention_days` and `hourly_retention_days` but not a daily retention field. Since daily retention is indefinite there is no constant to expose.

**[CONSIDER]** Add `daily_retention_days: int | None = None` (with `None` meaning indefinite) to make the schema self-describing and allow the frontend to display "indefinite" without hardcoding it.

---

## 3. Idempotency

### 3.1 `run_once()` is idempotent

Both UPSERTs use `ON CONFLICT ... DO UPDATE SET ...`, fully replacing the existing row's columns with freshly computed values. Running `run_once()` twice at the same clock time produces identical output. The retention DELETEs are also idempotent. **Correct.**

### 3.2 In-progress hour bucket

At `12:45`, the lookback `now - 2h = 10:45` includes the open `12:00` bucket. Each subsequent `run_once()` call will UPSERT the `12:00` bucket with increasing `total_checks` as new checks arrive. Correct by design.

### 3.3 Concurrent `run_once()` calls

If `POST /storage/rollup-now` races with the periodic task, both execute the same SQL. Under PostgreSQL `READ COMMITTED`, both reads see the same committed `check_results` snapshot and UPSERT the same aggregate values. The last UPSERT wins, leaving state consistent. No issue for the single-process MVP.

---

## 4. Edge Cases

### 4.1 No data (empty database)

- Both UPSERTs: `INSERT ... SELECT` returns no rows → no-op. No error.
- Both DELETEs: match no rows → no-op.
- `/history` returns `[]`. Correct.
- `/uptime`: aggregate queries with no matching rows return one row with `count()=0` and `sum()=NULL`. The `or 0` guards convert `NULL` → `0`. Returns `{"h24": 0.0, "d7": 0.0, "d30": 0.0}`. Covered by `test_uptime_returns_zeros_when_no_data`. No issue.

### 4.2 Extended downtime — narrow lookback windows

**[SHOULD FIX]** The hourly UPSERT lookback is `now - 2 hours`. If the process is down for more than 2 hours, check results that arrived during the outage will exist in `check_results` but will not be covered by the next hourly UPSERT run. Those buckets will remain stale until they age out of the raw retention window — at which point they are deleted without ever having been rolled up. The same applies to the daily UPSERT with its 2-day lookback.

The fix is straightforward: extend the hourly lookback to `RAW_RETENTION_DAYS` days (30 days) and the daily lookback to the full `hourly_rollups` history (180 days). Both tables are small enough that scanning the full history adds negligible cost.

### 4.3 Endpoint deleted between rollup and history query

FK `CASCADE` on rollup tables deletes rollup rows when an endpoint is deleted. The `/history` and `/uptime` routes check for endpoint existence first and return 404 if absent. No race condition concern.

---

## 5. Test Coverage

### 5.1 PLAN.md Phase 8 acceptance criteria

| Criterion | Covered? |
|---|---|
| Seed data, run rollup, assert hourly rows correct | Partial — `test_hourly_rollup_aggregates_correctly` covers the math but uses 6 checks over 2 hours (not 48h/2-endpoint scenario) |
| Assert daily rows correct | `test_daily_rollup_aggregates_from_hourly` — adequate for logic, single endpoint |
| Advance clock past retention, run again, assert old raw rows deleted | `test_raw_retention_deletes_old_rows` ✓ |
| Hourly retention sweep | `test_hourly_retention_deletes_old_rows` ✓ |
| `/history` with 1h, 7d, 90d returns correct tier | `test_history_raw/hourly/daily_source` ✓ |
| `POST /storage/rollup-now` runs synchronously and returns updated stats | `test_rollup_now_updates_counts`, `test_rollup_now_after_retention_removes_raw` ✓ |
| Rollup is idempotent | `test_rollup_is_idempotent` ✓ |

**[SHOULD FIX]** No multi-endpoint test to confirm `GROUP BY endpoint_id` does not cross-contaminate (e.g. two endpoints with different uptime rates should produce independent rollup rows). This is the most obvious gap relative to the PLAN's "2 endpoints" framing.

**[SHOULD FIX]** No 404 test for `GET /endpoints/{id}/uptime` with an unknown endpoint. The route checks for the endpoint and returns 404, but this code path is untested.

**[SHOULD FIX]** `/history` HTTP tests cover only `1h`, `7d`, and `90d`. The `1d`, `30d`, and `1y` range keys are exercised by unit tests for the routing function, but not end-to-end via HTTP.

### 5.2 Unit test quality

`test_uptime_pct_math`, `test_uptime_pct_all_success`, and `test_uptime_pct_all_failure` test Python's `round()` builtin, not any service code. They provide no meaningful coverage.

**[CONSIDER]** Remove these tests or replace them with a unit test that exercises a real service function (e.g. calling `resolve_range` with all valid keys, or directly constructing a `HistoryBin` and asserting its fields).

### 5.3 `test_rollup_is_idempotent` scope

The idempotency test only verifies `HourlyRollup`. It does not check that `DailyRollup` is also idempotent after two `run_once()` calls.

**[CONSIDER]** Extend the test to also assert the daily rollup row count and totals after two runs.

---

## 6. Code Quality

### 6.1 `run_once()` return value is unused

`run_once()` returns `now: datetime`, but neither `_loop()` nor the `rollup_now` API handler uses the return value.

**[CONSIDER]** Remove the return value. If retained for testability, add a comment explaining the intent.

### 6.2 `HistoryBin` uses manual `__slots__` instead of `@dataclass`

The class is an internal data carrier with a hand-written `__init__` and `__slots__`. This is correct but more verbose than `@dataclass(slots=True)` (available since Python 3.10; the project targets 3.12).

**[CONSIDER]** Replace with `@dataclass(slots=True)` to reduce boilerplate and match modern Python idiom.

### 6.3 Redundant `list()` wraps in `history_service`

```python
rows = list(
    (await session.execute(...)).scalars().all()
)
```

`.scalars().all()` already returns a `list`. The outer `list()` is redundant and appears three times.

**[CONSIDER]** Remove the outer `list()` calls. Low priority — consistent with the established pattern in other services.

### 6.4 `get_rollup_job` dependency uses `TYPE_CHECKING` import

The `TYPE_CHECKING` guard avoids a circular import at runtime. FastAPI does not evaluate return type annotations for dependency injection, so this works correctly. Noted for future maintainers: removing the guard would create an import cycle.

No issue.

### 6.5 `rollup_now` handler uses two separate sessions

`run_once()` opens its own session internally; `_compute_stats` uses the session injected by `get_session`. These are separate DB connections. Counts returned reflect the state after `run_once()` committed and are consistent. No issue for the single-process MVP.

---

## Summary

| # | Severity | Location | Description |
|---|---|---|---|
| 1 | SHOULD FIX | `rollup.py` | Hourly (2h) and daily (2d) lookback windows do not survive extended downtime. Stale hourly buckets will be deleted unrolled after 30 days. Extend to `RAW_RETENTION_DAYS` / full hourly history. |
| 2 | SHOULD FIX | `test_rollup.py` | No multi-endpoint test to confirm `GROUP BY endpoint_id` does not cross-contaminate rollup rows. |
| 3 | SHOULD FIX | `test_rollup.py` | No 404 test for `GET /endpoints/{id}/uptime` with unknown endpoint. |
| 4 | SHOULD FIX | `test_rollup.py` | `/history` HTTP tests cover only `1h`, `7d`, `90d`. The `1d`, `30d`, `1y` keys are untested via HTTP. |
| 5 | CONSIDER | `rollup.py` SQL | `NULLIF` denominator produces `NULL` uptime_pct if `total_checks=0` — violates `NOT NULL` constraint. Unreachable in production but fragile. Add `COALESCE(..., 0)`. |
| 6 | CONSIDER | `rollup.py` | `run_once()` return value unused by all callers. Remove or document. |
| 7 | CONSIDER | `schemas/storage.py` | No `daily_retention_days` field; frontend cannot display "indefinite" from schema data. Add `daily_retention_days: int \| None = None`. |
| 8 | CONSIDER | `services/history_service.py` | `HistoryBin` uses manual `__slots__` + `__init__`; replace with `@dataclass(slots=True)`. |
| 9 | CONSIDER | `services/history_service.py` | Redundant `list()` wraps around `.scalars().all()` in three places. |
| 10 | CONSIDER | `tests/unit/test_rollup.py` | `test_uptime_pct_*` tests Python builtins, not service code. Remove or replace with meaningful assertions. |
| 11 | CONSIDER | `tests/integration/test_rollup.py` | `test_rollup_is_idempotent` only verifies `HourlyRollup`; extend to also assert `DailyRollup`. |

## Overall Assessment

The Phase 8 implementation is solid. The rollup SQL is correct and idempotent, the tier routing matches the spec exactly, and the models, schemas, and routes are clean and minimal. The integration test suite covers all four PLAN.md acceptance criteria scenarios.

The highest-priority item is the narrow rollup lookback windows (issue 1): any downtime longer than 2 hours will leave hourly buckets permanently unrolled, eventually causing data loss when those raw rows age out. The second-highest is the missing multi-endpoint coverage (issue 2). Everything else is polish.
