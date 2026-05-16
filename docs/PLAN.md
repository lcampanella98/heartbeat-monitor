# Heartbeat Monitor — Implementation Plan

Status: In progress. Sequential, mechanical decomposition of the work described in `docs/REQUIREMENTS.md` and `docs/DESIGN.md`. Each phase ends at a demonstrable state and is small enough to review on its own. Tests are added alongside features within their phase, not deferred.

## Conventions

- All Python invoked via `uv` (`uv run pytest`, `uv add ...`, `uv sync`, `uvx <tool>`); never bare `python` / `pip`.
- Tests live under `backend/tests/{unit,integration}/`. New code in a phase ships with the tests called out in that phase's "tests" subsection.
- Each phase has a **Done when** line. Don't move on until it holds.
- Migrations created with `uv run alembic revision --autogenerate -m "..."` and committed alongside the model change.
- Code style enforced by `ruff` (lint + format); the frontend by ESLint + Prettier.

---

## Phase 1 — Repo bootstrap ✓ DONE

**Goal:** A clone of the repo can be brought up with `scripts/start.sh` (or `.ps1`) and exposes an empty health endpoint, with lint and tests wired.

**Tasks**

1. Initialize `.gitignore` with the entries listed in DESIGN.md §2.
2. Backend package: wrote `pyproject.toml` directly (skipped `uv init` to avoid name ambiguity) with all runtime deps and `[dependency-groups] dev` for pytest/ruff (note: `[tool.uv] dev-dependencies` was tried first but is deprecated in favour of the PEP 735 `[dependency-groups]` key). Configured `ruff` (line length 100, target py312) and `pytest` in the same file. Run `uv sync` to generate `uv.lock`.
3. Backend skeleton: `src/heartbeat/main.py` with `GET /api/v1/system/status` reading `CHECK_SOURCE`, `EMAIL_SINK`, and `SMTP_FROM` from `os.environ` (with sensible defaults) so the demo compose override is reflected immediately. `N=3` and `M=2` remain hardcoded constants. (The full pydantic-settings wiring is Phase 2 task 6.)
4. Frontend package: `npx create-next-app@latest frontend` with `--typescript --tailwind --app --src-dir --eslint --import-alias "@/*" --no-git`. Config file is `next.config.ts` (TypeScript variant, not `.mjs`). Set `output: "export"`. Initialized shadcn/ui with `npx shadcn@latest init -d`. Added `@tanstack/react-query`, `react-hook-form`, `zod`, `recharts` via `npm install`.
5. `Dockerfile.backend`: two-stage build. Stage 1: `node:lts` — `npm ci && npm run build` → `out/`. Stage 2: `python:3.12-slim` with uv from `ghcr.io/astral-sh/uv:latest`; copies `backend/` and runs `uv sync --no-dev --frozen`; copies `out/` to `./static`. CMD is plain `uvicorn` for Phase 1; the `alembic upgrade head` prefix is added in Phase 2 once alembic is configured.
6. `docker-compose.yml`: `db` (postgres:16, named volume, healthcheck `pg_isready`), `backend` (built from Dockerfile.backend, depends on db healthy, `OPENROUTER_API_KEY` forwarded from host env via `${OPENROUTER_API_KEY:-}`).
7. `docker-compose.demo.yml`: override sets `CHECK_SOURCE=simulated` and `EMAIL_SINK=log` on `backend`.
8. `scripts/start.{ps1,sh}` and `scripts/stop.{ps1,sh}` per DESIGN.md §14.
9. Stub `README.md` with one-paragraph summary, quick-start commands, and "see docs/" pointer.

**Tests**

- `backend/tests/unit/test_smoke.py` — `assert 1 + 1 == 2`.
- `uv run pytest` (1 passed), `uv run ruff check` (clean), `uv run ruff format --check` (clean), `npm run lint` (clean).

**Done when**

- `scripts/start.sh` (or `.ps1`) succeeds; `curl http://localhost:8000/api/v1/system/status` returns 200.
- Demo mode: `-Demo` / `--demo` flag causes status to reflect `check_source=simulated, email_sink=log`.
- `scripts/stop.sh` succeeds.
- `uv run pytest`, `uv run ruff check`, `npm run lint` (frontend) all pass.

---

## Phase 2 — Config, DB, Alembic, Clock, real system status ✓ DONE

**Goal:** Backend has a typed config, a working async DB session, the first migration creates `users` with the seeded `id=1` row, and the Clock abstraction is in place.

**Tasks**

1. `heartbeat/config.py`: `Settings(BaseSettings)` with every env var listed in DESIGN.md §10. `.env` loaded for local dev.
2. `heartbeat/db.py`: async engine via `create_async_engine`, `async_sessionmaker`, FastAPI dependency `get_session`.
3. `heartbeat/clock.py`: `Clock` Protocol, `RealClock`, `FakeClock` (with `set`/`advance`). DI provider returns `RealClock` in app; tests override.
4. `alembic init` inside `backend/`. Configure `env.py` to read URL from settings and use the async engine. Disable sqlite-only options.
5. First migration: create `users` (id, email, name, created_at). Data migration inserts `(id=1, email='user@local', name='User')`.
6. Make `/api/v1/system/status` return real values from `Settings` and the hardcoded `N=3, M=2`.
7. Lifespan: on startup, ping the DB to validate connectivity (no app start if DB is unreachable).

**Tests**

- Unit: `FakeClock` advance/set behavior.
- Integration: spin up a Postgres-backed test DB via a pytest fixture (`pytest_asyncio` + dropping/recreating the schema per session). Assert `users` has the seed row after migrations.
- Integration: `/api/v1/system/status` returns the configured modes.

**Done when**

- Stack comes up against a fresh volume; the `users` table has exactly one row; `/api/v1/system/status` returns settings values from env.

---

## Phase 3 — Endpoint CRUD ✓ DONE

**Goal:** Endpoints can be created, read, updated, deleted, enabled, and disabled via the API. The model carries every column DESIGN.md §4.2 specs, including streak state and simulator config (still unused).

**Tasks**

1. Model `models/endpoint.py` per DESIGN.md §4.2 (all columns).
2. Alembic migration (`197ec6c37b39_create_endpoints.py`). Downgrade drops the `streak_outcome` enum type via `DROP TYPE IF EXISTS`.
3. Pydantic schemas: `EndpointCreate`, `EndpointUpdate`, `EndpointRead`. Validate `url` (must be http/https), `check_interval_seconds` ∈ {30, 60, 300, 900}, `timeout_seconds` ∈ [1, 60], `sim_failure_rate` ∈ [0, 1], `sim_latency_min_ms ≤ sim_latency_max_ms` (cross-field), `name` non-empty. `EndpointRead.current_streak_outcome` typed as `StreakOutcome | None` so the OpenAPI schema emits the enum constraint.
4. `services/endpoint_service.py`: CRUD + enable/disable. `next_due_at` set to `clock.now()` on create (so a fresh endpoint is immediately due). `enable_endpoint` preserves `next_due_at` intentionally — if it is in the past the scheduler picks the endpoint up immediately; if in the future, the schedule is preserved. Sending `"sim_outage_windows": null` on update is treated as `[]` (clears all windows).
5. Router `api/endpoints.py`: routes per DESIGN.md §8 for endpoints. Mount under `/api/v1`.
6. `heartbeat/dependencies.py`: shared `get_clock()` FastAPI dependency returning `RealClock`. Integration tests override both `get_clock` and `get_session` (via `app.dependency_overrides`) to inject `FakeClock` and the NullPool test engine respectively. Overriding `get_session` is required on Windows to prevent asyncpg connections from being reused across test event loops.
7. Deleting an endpoint is hard delete; cascading FK behavior on related tables is deferred to phases that create those tables (set up `ondelete='CASCADE'` on FKs as they appear).

**Tests**

- Integration: full CRUD round-trip. Validation 422s for bad URL, bad interval, bad timeout, empty name, inverted latency range. Enable/disable flips the flag. Null outage windows on PUT clears to `[]`. `next_due_at` set to `clock.now()` on create verified via `FakeClock`.
- Unit: validator-level tests for all schema constraints including cross-field latency range and partial-update edge cases.

**Done when**

- `POST /api/v1/endpoints` creates one and it shows up in `GET /api/v1/endpoints`. All routes return correct status codes.

---

## Phase 4 — Checker interface and implementations ✓ DONE

**Goal:** `RealChecker` and `SimulatedChecker` both implement `Checker`, are wired into DI based on `CHECK_SOURCE`, and produce equivalent `CheckOutcome` shapes.

**Tasks**

1. `checker/__init__.py`: `Checker` Protocol, `CheckOutcome` dataclass, `ErrorCategory` enum.
2. `checker/real.py`: `RealChecker(http_client)` performing `await http_client.get(url, timeout=timeout)`. Latency measured with `time.monotonic()`. Exception mapping: `httpx.TimeoutException` → `timeout`; `httpx.ConnectError` categorised by `__cause__` type and message keywords (ssl/tls/certificate → `tls`; getaddrinfo/nodename → `dns`; else → `connection_refused`); all other `httpx.HTTPError` → `other`; non-2xx response → `non_2xx`.
3. `checker/simulated.py`: `SimulatedChecker(clock, rng)`. Logic per DESIGN.md §5.2: outage window check first, then failure-rate roll, then latency draw. Outage windows are repeating-daily UTC time-of-day intervals `{"start":"HH:MM","end":"HH:MM"}`. Midnight-spanning windows are not supported; enforced by a `SimOutageWindow` schema validator (see note below).
4. DI: `main.py` stores the checker on `app.state.checker` during lifespan; `get_checker(request)` in `dependencies.py` retrieves it. `httpx.AsyncClient` constructed only when `check_source == "real"`, closed on shutdown. Startup log line names the active checker.
5. `SimOutageWindow` schema validator added: rejects windows where `start >= end` (catches midnight-spanning and equal start/end) and validates `HH:MM` parse.

**Tests**

- Unit, `RealChecker`: stub `httpx.AsyncClient`; assert each response / exception maps to the correct `CheckOutcome`. Covers both message-based and `__cause__`-based TLS/DNS detection paths.
- Unit, `SimulatedChecker`: seeded `random.Random` + `FakeClock`; deterministic outcomes. Covers outage window hit/miss, inclusive start / exclusive end boundaries, failure-rate roll, success, latency bounds.
- Unit, `SimOutageWindow`: valid window, midnight-spanning rejected, equal start/end rejected, bad format rejected.

**Done when**

- Both checkers callable in isolation with deterministic tests. `CHECK_SOURCE` toggle changes which one is bound; verified via startup log line.

---

## Phase 5 — check_results + scheduler ✓ DONE

**Goal:** The scheduler picks due endpoints, runs the configured checker, persists results, advances `next_due_at`, and never spawns duplicate concurrent checks for the same endpoint.

**Tasks**

1. Model `models/check_result.py` per DESIGN.md §4.3 + migration. Index `(endpoint_id, checked_at DESC)`.
2. `scheduler.py`: `class Scheduler` with `in_flight: set[int]` and `start()/stop()` coroutines.
3. Loop body per DESIGN.md §6: select due endpoints excluding `in_flight`, claim, spawn task, sleep 1 s.
4. `check_endpoint(endpoint_id)`: open session, fetch endpoint, run `checker.check(endpoint)`, insert `CheckResult`, set `next_due_at = max(prev + interval, now)`, commit. `try/finally` removes ID from `in_flight`.
5. `asyncio.Semaphore(settings.scheduler_concurrency)` wraps the actual check call.
6. Lifespan: start scheduler on app boot; stop cleanly on shutdown (`scheduler.stop()` joins the loop, then awaits any in-flight tasks).
7. Add `GET /api/v1/endpoints/{id}/recent-checks?limit=N` returning the last N raw check results.

**Tests**

- Integration: insert 3 endpoints, inject `SimulatedChecker` with a fixed RNG seed and `FakeClock`. Advance the clock, drive a single loop tick manually (extract the loop body into a pure function `tick(now)` to make it test-driveable), assert `check_results` rows land with the right outcomes.
- Integration: an endpoint with a check that artificially takes >1 s (use a stub checker that awaits an `asyncio.Event`) does not get a second concurrent check tick; verify by inspecting `in_flight` and `check_results` row count.

**Done when**

- Bringing up the stack against a created endpoint produces rows in `check_results` on the schedule.

**Implementation notes**

- `ErrorCategory` defined in `models/check_result.py` (canonical); `checker/__init__.py` imports it from there.
- `CheckResult.outcome` reuses the existing `streak_outcome` PostgreSQL enum (`create_type=False`); `error_category` enum created by `op.create_table` via SQLAlchemy's `before_create` event — no explicit `CREATE TYPE` needed.
- `tick()` returns the set of spawned tasks so tests can `await asyncio.gather(*tasks)` and assert synchronously.
- Semaphore gates only `checker.check()`, not DB operations.
- `notin_()` condition on `in_flight` omitted entirely when the set is empty (avoids invalid `NOT IN ()` SQL).
- Recent-checks query lives in `services/check_result_service.py`, not inline in the router.
- Post-review fixes (see `docs/code_review/CR_5.md`): removed redundant `ErrorCategory` value round-trip in scheduler, fixed import order in `checker/__init__.py`, added `__table_args__` index to `CheckResult` model, extracted route query to service.

---

## Phase 6 — Streaks, incidents, postmortems ✓ DONE

**Goal:** Failure / success streaks open and close incidents at thresholds N=3 / M=2. Closed incidents have their `frozen_timeline` populated. The `postmortems` table exists.

**Tasks**

1. Migration: add the streak columns to `endpoints` per DESIGN.md §4.2 (denormalized state).
2. Models + migrations for `incidents` and `postmortems` per DESIGN.md §4.6 and §4.7. Partial unique index on `incidents(endpoint_id) WHERE ended_at IS NULL`.
3. `services/incident_service.py`:
   - `apply_check_result(endpoint, check)`: updates streak state, opens/closes incidents per DESIGN.md §6.1.
   - On close: query `check_results` for the bracketing window, serialize to `frozen_timeline` JSONB.
4. Call `apply_check_result` from `scheduler.check_endpoint` inside the same DB transaction as the result insert.
5. Routes: `GET /api/v1/incidents`, `GET /api/v1/incidents/{id}`.

**Tests**

- Unit, table-driven: sequences like `[S, S, F, F, F, S, S]`, `[F, F, F, F, S, S]`, `[F, F, S, F, F, F, S, S]` → expected (incident_open_count, frozen_timeline_size) tuples. Cover edge cases: incident already open shouldn't be opened again; success streak resetting in the middle of failures.
- Integration: synthesize a streak via `SimulatedChecker` with a config that guarantees failures, drive the scheduler ticks, assert the incident lifecycle is correct end-to-end and `frozen_timeline` JSONB is shaped right.

**Done when**

- A run of three consecutive failures opens an incident; two consecutive successes close it and populate the frozen timeline including bracketing successes.

**Implementation notes**

- Task 1 was a no-op: streak columns were already added in the Phase 3 migration.
- Integration tests use a `SequenceChecker` stub (deterministic predetermined outcomes) rather than `SimulatedChecker`, for reliable sequence control.
- `N` and `M` imported from `incident_service` in `main.py` rather than restated as literals.
- Post-review fixes documented in `docs/code_review/CR_6.md`.

---

## Phase 7 — Alert sinks, recipients, sent notifications

**Goal:** Opening or closing an incident dispatches an alert through whichever sink is configured. Recipients are managed via API. The log sink enforces the ring buffer.

**Tasks**

1. Models + migrations: `email_recipients` and `sent_notifications` per DESIGN.md §4.8 and §4.9.
2. `alerts/__init__.py`: `AlertSink` Protocol, `NotificationKind` enum.
3. `alerts/log_sink.py`: `LogSink`. Insert into `sent_notifications`, then in the same transaction enforce the 1,000-row cap (DELETE rows with id < the 1,000th-newest's id).
4. `alerts/smtp_sink.py`: `SmtpSink` using `aiosmtplib`. Reads SMTP env vars; constructs a `Message` per recipient list; sends.
5. `services/alert_dispatcher.py`: builds subject/body for `incident_opened` and `incident_closed`, fetches recipients from `email_recipients`, calls the bound sink. Body is plain text including endpoint name, URL, timestamps, duration (for close), and a link to the incident detail page (`/incidents/{id}`).
6. Wire the dispatcher into `incident_service.apply_check_result` after the open/close transaction commits — fire-and-forget via `asyncio.create_task`, with errors logged but not propagated.
7. DI: bind the right sink at startup based on `EMAIL_SINK`.
8. Routes: `GET/POST/DELETE /api/v1/recipients`; `GET /api/v1/notifications` (paginated, newest first, cursor-style with `before_id`).

**Tests**

- Unit, `LogSink`: after 1,001 inserts the table holds 1,000 rows and the oldest is gone.
- Integration: incident open → `sent_notifications` row exists with the right `kind`, `incident_id`, snapshotted `recipients`.
- Integration, no real SMTP needed: tests run with `EMAIL_SINK=log`. A separate test stubs `aiosmtplib.send` and asserts it is called with the right Message under `EMAIL_SINK=smtp`.

**Done when**

- Driving an incident through open and close produces exactly two `sent_notifications` rows under log sink, with correct content.

---

## Phase 8 — Rollups, retention, storage panel API

**Goal:** Hourly and daily rollups exist, retention deletions happen on schedule, history reads route to the right tier, and the storage panel API surfaces it.

**Tasks**

1. Models + migrations: `hourly_rollups` (§4.4) and `daily_rollups` (§4.5).
2. `rollup.py`:
   - `run_once(now)`: idempotent. Hourly UPSERT for `(endpoint_id, hour)` over the lookback window (last 2 hours). Daily UPSERT for `(endpoint_id, date)` over the last 2 days, computed from hourly. DELETE raw < 30 days. DELETE hourly < 180 days.
   - `start()/stop()` for the periodic task (5-minute cadence), structured like the scheduler.
3. `services/history_service.py`: tier read-routing per DESIGN.md §7.1. Returns bins tagged with `source: "raw"|"hourly"|"daily"`.
4. `services/uptime_service.py`: 24h from raw, 7d from hourly, 30d from daily.
5. Routes:
   - `GET /api/v1/endpoints/{id}/history?range=...`
   - `GET /api/v1/endpoints/{id}/uptime`
   - `GET /api/v1/storage/stats` (row counts per tier, retention, last/next rollup time)
   - `POST /api/v1/storage/rollup-now`

**Tests**

- Unit: aggregation math (rollup totals + uptime pct) over fixture rows.
- Integration: seed 48 hours of check_results across 2 endpoints; run rollup; assert hourly rows are correct; assert daily rows are correct; advance clock past retention and run again; assert old raw rows deleted.
- Integration: `/history` with ranges of 1h, 7d, 90d returns bins from the correct tier (check `source` field).
- Integration: `POST /storage/rollup-now` runs synchronously and returns updated `storage/stats`.

**Done when**

- A populated DB shows non-zero counts in all three tiers; `/history?range=90d` returns daily bins; raw retention sweeps correctly.

---

## Phase 9 — AI postmortem generation

**Goal:** A user can generate, edit, and regenerate a postmortem draft for an incident via the API.

**Tasks**

1. `ai/client.py`: `AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=settings.openrouter_api_key)`.
2. `ai/prompts.py`: `SYSTEM_PROMPT` and `render_incident_prompt(incident)` per DESIGN.md §11. Deterministic rendering of the frozen timeline as a compact table.
3. `services/postmortem_service.py`:
   - `generate(incident_id)`: build prompt, call client, upsert `postmortems.content`, set `generated_at`.
   - `update(incident_id, content)`: set `content`, `edited_at`.
4. Routes:
   - `POST /api/v1/incidents/{id}/postmortem/generate` (returns the generated content; idempotent in the sense that calling twice replaces).
   - `PUT /api/v1/incidents/{id}/postmortem` (manual edit).
5. Error handling: if `OPENROUTER_API_KEY` is unset, return 503 with a clear message. Upstream errors return 502 with the underlying detail trimmed.

**Tests**

- Unit: prompt rendering snapshot test (deterministic input → exact string).
- Integration: monkey-patch the `AsyncOpenAI` client to return a canned response; generate → assert `postmortems.content` is set, `generated_at` populated. Edit → `content` updated, `edited_at` populated. Regenerate → overwrites and resets `edited_at` to null.

**Done when**

- Against a real OpenRouter key (manual smoke), `POST .../postmortem/generate` returns a coherent draft for a real seeded incident.

---

## Phase 10 — Demo pre-seed

**Goal:** Starting the stack with `scripts/start.sh --demo` against an empty DB produces a fully-realized demo: ~75 days of history across all three storage tiers, multiple incidents, and a banner indicating demo modes.

**Tasks**

1. `seed.py`:
   - Trigger condition: `settings.check_source == "simulated" and settings.email_sink == "log" and endpoint_count == 0`.
   - Insert the 5 example endpoints per DESIGN.md §13 with their simulator configs.
   - Generate synthetic history by stepping a `FakeClock` from `now - 75 days` to `now` in 30-second increments and invoking the same scheduler tick logic used in production (extracted in phase 5). This produces organic incidents via the normal incident_service path. Bulk-insert check_results to keep this fast.
   - Use a `NoopSink` during seeding so the seeder doesn't fill the ring buffer with 75 days of synthetic alerts.
   - After history is generated, run the rollup job once to produce hourly + daily rollups and delete raw older than 30 days.
2. Call `seed.maybe_seed()` from FastAPI lifespan startup, after migrations.

**Tests**

- Integration: with a sim+log fixture and an empty DB, run seeding; assert: 5 endpoints exist; raw count covers ~30 days; hourly and daily tiers populated; at least 1 incident exists with a non-empty `frozen_timeline`.
- Integration: seeding is a no-op if endpoints already exist.

**Done when**

- A fresh `scripts/start.sh --demo` against a wiped volume produces a populated demo on first request.

---

## Phase 11 — Frontend foundation

**Goal:** Frontend is structured for feature work: app router shell with nav, TanStack Query provider, typed API client, demo-mode banner, shadcn primitives in place.

**Tasks**

1. `src/lib/api.ts`: thin typed fetch wrapper. Hits same-origin `/api/v1/...`. Throws on non-2xx with parsed FastAPI detail.
2. `src/lib/queries.ts`: TanStack Query hooks per resource (`useEndpoints`, `useEndpoint`, `useIncidents`, etc.). Reasonable `staleTime` defaults; `refetchInterval` configured per page in phase 12.
3. `src/types/`: generate or hand-author TS types matching the pydantic schemas. (For MVP, hand-author; revisit codegen later.)
4. `src/app/layout.tsx`: app shell with sidebar nav (Dashboard, Endpoints, Incidents, Notifications, Settings). Wraps children in `<QueryClientProvider>`.
5. `src/components/DemoBanner.tsx`: fetches `/api/v1/system/status`; if `check_source === "simulated"` or `email_sink === "log"`, renders a sticky top banner with explanatory copy. Always rendered in layout, conditional on data.
6. Install the shadcn primitives the app needs: `button`, `dialog`, `input`, `form`, `table`, `badge`, `card`, `tooltip`, `dropdown-menu`, `toast`, `select`.
7. Wire `next.config.mjs` and FastAPI's static mount so `npm run build` → `out/` → served at `/` by the backend. Local dev runs `next dev` on 3000 proxying API calls to `:8000`.

**Tests**

- `tsc --noEmit` clean.
- Lint clean.
- Manual: `npm run dev` against a running backend renders the layout with the banner correctly toggling.

**Done when**

- Visiting `http://localhost:8000` shows the app shell with nav; visiting in demo mode shows the banner.

---

## Phase 12 — Frontend feature pages

**Goal:** Every page described in DESIGN.md §9 is implemented and works against the live backend.

**Tasks** (each is a sub-deliverable, in this order)

1. **Dashboard (`/`)**: card per endpoint with state badge (Up / Down / Unknown), 60-tick recent-check strip (hand-rolled SVG over `useRecentChecks`), 24h/7d/30d uptime % chips. Active incidents banner at the top. 5 s `refetchInterval`.
2. **Endpoints list (`/endpoints`)**: shadcn `Table`; row actions: Edit (dialog with form), Delete (confirm dialog), Enable/Disable toggle. New Endpoint button → create dialog. Form fields per DESIGN.md §4.2 including simulator config (under a collapsible "Simulator (used in simulated mode)" section).
3. **Endpoint detail (`/endpoints/[id]`)**: range selector (1h / 1d / 7d / 30d / 90d / 1y) → granularity-aware history chart via Recharts `BarChart`. Tooltip labels tier source. Recent check log table beneath.
4. **Incidents list (`/incidents`)**: filter by state (active / closed / all), endpoint filter. shadcn `Table`.
5. **Incident detail (`/incidents/[id]`)**: header (endpoint, started/ended, duration). Timeline rendered as a checklist of timestamped check rows (from `frozen_timeline` when closed, from `check_results` when still open — 2 s `refetchInterval` while open). Postmortem panel: Generate button when content is null, editable `<Textarea>` when content present, Regenerate button (with confirm dialog).
6. **Notifications (`/notifications`)**: paginated list with cursor pagination (`before_id`). Each row expandable to show subject + body.
7. **Settings (`/settings`)**: recipients editor (list + add/delete), Storage panel (counts, retention, last/next rollup, Run rollup now button), read-only mode badges (`CHECK_SOURCE`, `EMAIL_SINK`, `SMTP_FROM`, `N`, `M`).

**Tests**

- React Testing Library tests for the non-trivial widgets: recent-check strip (renders N ticks with correct colors), granularity-aware chart wrapper (selects the right `source` and bin shape from API payload).
- Manual click-through against a real demo-seeded backend (use `scripts/start.sh --demo`).

**Done when**

- Every page renders without errors, mutations work end-to-end, and a manual run against a demo-seeded backend feels coherent.

---

## Phase 13 — README, scale-out section, manual smoke

**Goal:** A first-time visitor to the repo can read README.md and understand the project, run the demo, find the design docs, and read the "how would we scale this?" narrative required by REQUIREMENTS.md §7.

**Tasks**

1. README:
   - One-paragraph overview.
   - Screenshot(s) of dashboard, incident detail with postmortem, storage panel.
   - "Run the demo" — one block of commands using `scripts/start.sh --demo` (or `.ps1`).
   - "Modes" — explanation of `CHECK_SOURCE` × `EMAIL_SINK` matrix.
   - "Configuration" — env var table.
   - "How would we scale this?" — short section covering: separate scheduler service, queue/broker (Redis Streams or Postgres-as-queue with `SELECT ... FOR UPDATE SKIP LOCKED`), stateless check workers, separate alert worker, storage tier scaling (partitioning raw by day, TimescaleDB hypertables, cold object-storage archive), push-based UI updates (SSE / WebSockets). One sentence each, no diagrams required.
   - Pointer to `docs/REQUIREMENTS.md`, `docs/DESIGN.md`, `docs/PLAN.md`.
2. Full manual smoke pass against `scripts/start.sh --demo`:
   - Banner present.
   - Storage panel non-trivial.
   - Generate postmortem on a seeded incident succeeds.
   - Create a new endpoint with deliberately high failure rate → see an incident open within a few minutes → close it by editing the failure rate to 0 → confirm postmortem can be generated.
   - `scripts/stop.sh --wipe` followed by `scripts/start.sh --demo` re-seeds cleanly.
3. Tighten any rough edges surfaced by the smoke pass.

**Done when**

- README renders correctly on GitHub.
- Smoke checklist passes.
- All prior phases' tests still green; `uv run pytest` and `npm run lint && tsc --noEmit` clean.

---

## Cross-cutting deferrals

These are explicitly **not** done in any phase above, by design:

- CI / GitHub Actions.
- E2E browser tests (Playwright/Cypress).
- Multi-process workers, queue/broker, leader election — covered only in the README scale-out write-up.
- TimescaleDB / partitioning — same.
- SSE / WebSockets push — same.
- Auth / login screen — out of scope per requirements.

## What to do when a phase reveals a problem

Per CLAUDE.md standard #3: identify root cause with evidence, fix, then continue. Don't tack on patches across phases. If a problem implies a design change, update `docs/DESIGN.md` first, then return to the phase.
