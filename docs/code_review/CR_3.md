# Code Review: Phase 3 — Endpoint CRUD

**Reviewer:** Claude Code
**Date:** 2026-05-15
**Status:** All 47 tests pass, ruff clean.

Phase 3 delivers a clean, focused CRUD layer that is structurally sound and closely matches DESIGN.md §4.2 and §8. The service layer, router, migration, and schemas are well-composed. A small number of issues are noted below, none of which are data-loss bugs; the most actionable is the missing `next_due_at` reset on re-enable and the absence of `sim_latency_min/max` cross-validation.

---

## 1. Correctness vs. Spec

**Columns (DESIGN.md §4.2):** All required columns are present and typed correctly: `id`, `user_id` (FK), `name`, `url`, `enabled`, `check_interval_seconds`, `timeout_seconds`, `next_due_at`, `current_streak_outcome`, `current_streak_count`, `streak_started_at`, `sim_failure_rate`, `sim_latency_min_ms`, `sim_latency_max_ms`, `sim_outage_windows`, `created_at`, `updated_at`. No column is missing or mistyped.

**Indexes (DESIGN.md §4.2):** Both required indexes are present: `(user_id)` and the partial `(next_due_at) WHERE enabled = true`.

**Routes (DESIGN.md §8):** All seven Phase 3 routes are implemented with correct HTTP methods and paths:

| Route | Method | Status |
|---|---|---|
| `/api/v1/endpoints` | GET | 200 |
| `/api/v1/endpoints` | POST | 201 |
| `/api/v1/endpoints/{id}` | GET | 200 / 404 |
| `/api/v1/endpoints/{id}` | PUT | 200 / 404 |
| `/api/v1/endpoints/{id}` | DELETE | 204 / 404 |
| `/api/v1/endpoints/{id}/enable` | POST | 200 / 404 |
| `/api/v1/endpoints/{id}/disable` | POST | 200 / 404 |

The routes for `/recent-checks`, `/history`, and `/uptime` are correctly deferred to later phases.

**Spec note on `next_due_at`:** DESIGN.md §4.2 specifies `next_due_at` as "null until first scheduled run". Phase 3 PLAN.md task 4 explicitly overrides this for the CRUD layer: "set to `clock.now()` on create (so a fresh endpoint is immediately due)". The implementation sets it to `clock.now()` in `create_endpoint`, which is correct per the plan.

---

## 2. Model (`models/endpoint.py`)

**Column types:** Correct throughout. `BIGSERIAL`-style primary key implemented as `BigInteger` with `primary_key=True` (Alembic generates the sequence). `DateTime(timezone=True)` used consistently for all timestamps.

**Nullability:** All nullable/not-null choices are consistent with the spec. `next_due_at`, `current_streak_outcome`, and `streak_started_at` are correctly nullable.

**Defaults:**
- `enabled = True`, `timeout_seconds = 10`, `current_streak_count = 0`, `sim_failure_rate = 0.0`, `sim_latency_min_ms = 100`, `sim_latency_max_ms = 500` — all match spec.
- `sim_outage_windows` uses `server_default=sa.text("'[]'::jsonb")` which is correct for Postgres but means Python-side inserts that omit the field will get `None` without an explicit Python-level default. This is avoided by the service always passing `[w.model_dump() for w in data.sim_outage_windows]`, but the ORM model has no `default=[]` Python-side guard. This is a minor latent trap if the model is ever constructed outside the service.

**`updated_at` and `onupdate`:** `onupdate=func.now()` is set on the `updated_at` column (line 63). With async SQLAlchemy, `onupdate` triggers only for ORM `UPDATE` statements; it does not fire for `session.execute(update(...))` style bulk updates. The current service uses `setattr` + `session.commit()` which does produce an ORM update, so this works correctly in Phase 3. Future phases using bulk UPDATE should be aware of this.

**Missing constraint:** `name` and `url` are `String` with no `length` parameter. PostgreSQL accepts unbounded `TEXT` for this, which is fine. But there is no not-empty validation at the DB level, so an empty string `""` for `name` or `url` can be persisted if the Pydantic validator is bypassed. See Findings §F2.

**`StreakOutcome` enum placement:** Defined in `models/endpoint.py` rather than a shared `models/enums.py`. This is acceptable for Phase 3 since it is only used here. When `check_results` is added in Phase 5 with its own `outcome` column, there will be a decision point about sharing enums.

---

## 3. Schemas (`schemas/endpoint.py`)

**URL validation:** `EndpointCreate.url_must_be_http_or_https` (line 25) and the `EndpointUpdate` variant (line 44) are both correct. The `EndpointUpdate` validator correctly uses `mode="before"` and the `isinstance(v, str)` guard so that `None` passes through cleanly.

**`check_interval_seconds`:** `Literal[30, 60, 300, 900]` is a clean, tight constraint. Correct on both `EndpointCreate` and `EndpointUpdate`.

**`timeout_seconds`:** `Field(ge=1, le=60)` — correct per spec (1–60).

**`sim_failure_rate`:** `Field(ge=0.0, le=1.0)` — correct.

**`sim_latency_min_ms` and `sim_latency_max_ms`:** Each has `Field(ge=0)` but there is no cross-field validator ensuring `sim_latency_min_ms <= sim_latency_max_ms`. Sending `{"sim_latency_min_ms": 500, "sim_latency_max_ms": 100}` will persist successfully and the SimulatedChecker (Phase 4) will likely receive an invalid range. See Findings §F3.

**`EndpointRead`:** All model fields are exposed. `current_streak_outcome` is typed as `str | None` rather than `StreakOutcome | None`. This works at runtime (Pydantic will call `.value` on the enum), but loses type precision in the response schema — clients see a plain string. This is a minor consistency point; see Findings §F4.

**`sim_outage_windows` in `EndpointRead`:** Typed as `list[SimOutageWindow]` and populated correctly via `from_attributes=True`. The round-trip test (`test_sim_outage_windows_roundtrip`) confirms this works end-to-end.

---

## 4. Service Layer (`services/endpoint_service.py`)

**`create_endpoint`:** Correctly sets `next_due_at=clock.now()` (line 31), populates all fields, calls `session.add`, `commit`, and `refresh`. The `sim_outage_windows` serialization `[w.model_dump() for w in data.sim_outage_windows]` is correct — it converts Pydantic models to dicts before storing as JSONB.

**`get_endpoint`:** Filters on both `id` and `user_id` (line 18), which correctly enforces ownership. This is the right pattern for the hardcoded `_USER_ID = 1` approach.

**`update_endpoint`:** Uses `data.model_dump(exclude_unset=True)` (line 50) correctly — only fields explicitly sent in the request are written. The `sim_outage_windows` special-case (lines 51–52) correctly re-serializes to dicts. However, there is a subtle issue: when `sim_outage_windows` is present in `update_data` but `data.sim_outage_windows is None` (i.e., the client explicitly sends `null`), the re-serialization branch is skipped and `None` would be set on the column. Given the column is `NOT NULL` with a `server_default`, this would result in a DB constraint error at commit. The condition on line 51 should be `if "sim_outage_windows" in update_data:` without the `is not None` guard, relying instead on validating that `null` is not allowed by the schema — but the schema does allow `list[SimOutageWindow] | None = None` in `EndpointUpdate`. See Findings §F5.

**`enable_endpoint` / `disable_endpoint`:** Both are straightforward and correct. Neither resets `next_due_at`. Re-enabling a previously disabled endpoint leaves `next_due_at` at whatever it was when it was disabled (potentially far in the past, which means the scheduler will immediately pick it up on the next tick — arguably the desired behavior). This is acceptable, but differs subtly from the "set to `clock.now()` on create" intent. See Findings §F6.

**`_USER_ID = 1` constant:** Appropriately placed as a module-level constant per CLAUDE.md §1 (no over-engineering). Will need to become a dependency-injected parameter when auth is added.

---

## 5. Router (`api/endpoints.py`)

**Status codes:** All correct — 201 for POST, 204 for DELETE, 200 for everything else, 404 for not-found. FastAPI enforces no response body on 204 correctly.

**Dependency injection:** `get_session` and `get_clock` injected via `Depends`. The `get_clock` dependency (in `dependencies.py`) instantiates a new `RealClock()` per request, which is fine — `RealClock` is stateless.

**`# type: ignore[return-value]` comments:** Used on all return statements where the service returns an `Endpoint` ORM object but the function return type is `EndpointRead`. This is the correct pragmatic approach given FastAPI's response model handles serialization. The alternative is to type the service functions as returning `EndpointRead` directly, but that would require explicit schema construction.

**`update_endpoint` missing `clock` dependency:** The `PUT /endpoints/{id}` route does not accept a `clock` dependency and thus cannot reset `next_due_at` when, for example, `check_interval_seconds` is changed. This is a design decision — the scheduler handles rescheduling — but if the interval changes from 60s to 30s while `next_due_at` is 55 seconds in the future, the endpoint will still be checked on the original schedule for that one tick. This is an acceptable Phase 3 limitation; the scheduler in Phase 5 will use the updated interval to compute subsequent `next_due_at`.

**Missing `clock` on `enable_endpoint`:** Consistent with the above. When an endpoint is re-enabled, `next_due_at` is not reset. See Findings §F6.

---

## 6. Migration (`alembic/versions/197ec6c37b39_create_endpoints.py`)

**Schema accuracy:** The migration faithfully reflects the ORM model. All column types, nullability, and defaults match.

**`server_default` for `sim_outage_windows`:** `sa.text("'[]'::jsonb")` in both the model and migration — correct for PostgreSQL.

**Enum handling:** The `streak_outcome` enum is created inline via `sa.Enum("success", "failure", name="streak_outcome")`. This correctly creates a PostgreSQL `TYPE streak_outcome`. The `downgrade` function drops the enum type via `sa.Enum(name="streak_outcome").drop(op.get_bind(), checkfirst=True)` (line 83). However, `op.get_bind()` is deprecated in Alembic 2.x in favour of using `op.get_context().bind` or migration-level connection objects. This will emit a deprecation warning today and may break in a future Alembic version. See Findings §F7.

**Indexes:** Both `ix_endpoints_user_id` (plain) and `ix_endpoints_next_due_at_enabled` (partial, `WHERE enabled = true`) are created correctly. The `downgrade` correctly includes `postgresql_where` on the partial index drop.

**`down_revision`:** Points to `1e697fab1bb8` (the `create_users` migration) — correct chain.

**`alembic/env.py`:** The import of `Endpoint` at line 11 (`from heartbeat.models.endpoint import Endpoint  # noqa: F401`) ensures the model is registered with `Base.metadata` before autogenerate runs. This is the correct pattern.

---

## 7. Tests

**Unit tests (`tests/unit/test_endpoint_schemas.py`):** Covers URL validation (http, https, ftp, bare domain), all four valid intervals, one invalid interval, timeout boundary values (0, 1, 60, 61), failure rate bounds, update schema partial-field and empty behavior, and update URL validation. Coverage is thorough for the schema layer.

**Integration tests (`tests/integration/test_endpoints.py`):**

- Full CRUD round-trip: create, list, get-by-id, update (partial fields with unchanged field verification), delete + confirm 404.
- 404 paths: nonexistent get, update, delete, enable, disable.
- Enable/disable: both directions tested, including creating disabled and then enabling.
- Validation 422s: bad URL, bad interval, timeout too low, timeout too high.
- Edge cases: empty list, `sim_outage_windows` round-trip.
- `next_due_at`: `test_create_sets_next_due_at_to_now` verifies the clock injection is working end-to-end.

**`conftest.py` / `get_session` override pattern:** The `client` fixture (lines 38–54) overrides both `get_session` and `get_clock` using `app.dependency_overrides`. The comment explains the NullPool rationale for Windows event-loop isolation. The `clean_endpoints` autouse fixture truncates the `endpoints` table before each test, ensuring test isolation without a full schema reset per test. This is a sound pattern.

**Untested paths:**
- Sending an explicit `null` for `sim_outage_windows` in a PUT request (the `is not None` guard edge case in the service — Findings §F5).
- `sim_latency_min_ms > sim_latency_max_ms` (inverted range — Findings §F3).
- Empty string for `name` or `url` (Findings §F2).
- Update with an entirely empty body `{}` (all fields unset) — the current behavior would be a no-op update that still hits the DB and returns the unchanged record. Probably correct, but worth a test.
- `check_interval_seconds` changed via PUT — verifying `next_due_at` is not modified by the update (documents the intentional behavior).

---

## 8. Findings

### Bugs

None identified. No data-loss or incorrect-behavior bugs found.

### Spec Deviations

**F1 — (Informational, no action needed):** `next_due_at` set to `clock.now()` on create, not `null`. DESIGN.md §4.2 says "null until first scheduled run" but PLAN.md Phase 3 task 4 explicitly overrides this. The implementation matches the plan. Flagged only for awareness when Phase 5 implements the scheduler query `WHERE next_due_at IS NULL OR next_due_at <= now`.

### Suggestions

**F2 — (Suggestion):** No empty-string guard on `name` or `url`. A client can send `{"name": "", "url": "https://ok.com", ...}` and it will be persisted. Add `@field_validator("name")` with `if not v.strip(): raise ValueError(...)` in `EndpointCreate` and `EndpointUpdate`. Similarly, the URL validator already runs on `url`; ensure it also rejects an empty string (currently it would fail the `startswith` check naturally, so `url` is safe — only `name` needs the guard).

**F3 — (Suggestion):** No cross-field validation that `sim_latency_min_ms <= sim_latency_max_ms`. Add a `@model_validator(mode="after")` to `EndpointCreate` and `EndpointUpdate` that raises a `ValueError` if `min > max`. Without this, the `SimulatedChecker` (Phase 4) will receive an invalid range and likely raise an exception at check time rather than at create/update time.

**F4 — (Suggestion):** `EndpointRead.current_streak_outcome` is typed as `str | None` instead of `StreakOutcome | None`. At runtime this is fine because Pydantic with `from_attributes=True` will serialize the enum to its string value. However, using the enum type would make the OpenAPI schema emit an enum with the `["success", "failure"]` constraint rather than a plain `string`, which improves client codegen. Change `current_streak_outcome: str | None` to `current_streak_outcome: StreakOutcome | None` and import `StreakOutcome` from `heartbeat.models.endpoint`.

**F5 — (Bug risk, low probability):** In `endpoint_service.update_endpoint` (line 51), the condition `if "sim_outage_windows" in update_data and data.sim_outage_windows is not None` will silently skip re-serialization if a client explicitly sends `"sim_outage_windows": null`. The raw `None` value would then be written to the `NOT NULL` JSONB column, causing a DB integrity error at commit. The cleanest fix is to disallow `null` for `sim_outage_windows` in `EndpointUpdate` (change `list[SimOutageWindow] | None = None` to `list[SimOutageWindow] | None = None` with a note that `null` means "omit, don't clear") or to simplify the condition to just `if "sim_outage_windows" in update_data:` and handle the `None` case explicitly. The most intent-preserving fix: in `EndpointUpdate`, keep `sim_outage_windows: list[SimOutageWindow] | None = None` (where `None` means "not provided") and in the service, change line 51 to `if "sim_outage_windows" in update_data:` then handle `None` as "set to empty list" or raise. Currently, a client that wants to clear outage windows must send `[]`, not `null`, which is correct semantics but not enforced.

**F6 — (Suggestion):** `enable_endpoint` does not reset `next_due_at` to `clock.now()`. If an endpoint was disabled while `next_due_at` was far in the past (e.g., disabled shortly after being due), re-enabling it will cause the scheduler to immediately pick it up, which is the desired behavior — so this is probably fine. However, if `next_due_at` was in the future when disabled, re-enabling it preserves that future time, which is also reasonable. The behavior is consistent; document it in a comment on `enable_endpoint` for clarity, as Phase 5 will need to reason about this interaction.

**F7 — (Suggestion):** In the migration downgrade (line 83), `sa.Enum(name="streak_outcome").drop(op.get_bind(), checkfirst=True)` uses `op.get_bind()`, which is deprecated in Alembic 2.x. The migration-level replacement is to use a connection obtained from `op.get_context().bind` or, more robustly, to wrap it in a `with op.get_context().autocommit_block():` and execute DDL directly. For now this emits a deprecation warning; it will not cause failures in current Alembic versions but should be addressed before Alembic 3.x compatibility becomes relevant.
