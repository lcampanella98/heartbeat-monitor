# Heartbeat Monitor — Tech Design

Status: Draft. Follows from `docs/REQUIREMENTS.md`. Captures the technical decisions needed before writing a stepwise implementation plan. Focused on shapes, seams, and library choices — not exhaustive code.

## 1. Goals of this document

- Decide the data model, key interfaces, scheduler shape, and storage-tier behavior so the implementation plan can be a mechanical decomposition rather than a series of in-flight architecture choices.
- Make the swap points called out in the requirements (real vs. simulated checker, smtp vs. log email sink, frozen-timeline incident persistence) concrete and testable.
- Pick libraries explicitly so the build phase doesn't relitigate them.

Anything past the MVP (separate scheduler/worker processes, queue/broker, push-based UI, deeper storage tiering) is described only in the README "How would we scale this?" section.

## 2. Repository layout

```
heartbeat-monitor/
  backend/
    pyproject.toml
    alembic.ini
    alembic/versions/
    src/heartbeat/
      __init__.py
      main.py              FastAPI app, lifespan, DI wiring
      config.py            pydantic-settings env loading
      db.py                async engine, session factory
      clock.py             Clock interface, RealClock, FakeClock
      models/              SQLAlchemy ORM models
      schemas/             pydantic request/response schemas
      api/                 routers (endpoints, incidents, notifications, settings, system)
      services/            business logic (endpoint_service, incident_service, ...)
      checker/             Checker interface, RealChecker, SimulatedChecker
      alerts/              AlertSink interface, SmtpSink, LogSink
      scheduler.py         async scheduler loop
      rollup.py            rollup job
      ai/                  OpenRouter client + prompt assembly
      seed.py              demo pre-seeding
    tests/
      unit/
      integration/
  frontend/
    package.json
    next.config.mjs         output: 'export'
    tailwind.config.ts
    src/
      app/                  app router pages
        layout.tsx
        page.tsx            dashboard
        endpoints/
        incidents/
        notifications/
        settings/
      components/
      lib/
        api.ts              fetch wrapper + typed endpoints
        queries.ts          TanStack Query hooks
      types/
  docker-compose.yml         base: CHECK_SOURCE=real, EMAIL_SINK=log
  docker-compose.demo.yml    override applied with --demo: CHECK_SOURCE=simulated
  docker-compose.smtp.yml    override applied with --smtp: EMAIL_SINK=smtp, passes SMTP_* from .env
  Dockerfile.backend
  Dockerfile.frontend       (build stage only; static output copied into backend image)
  scripts/
    start.ps1               Windows: bring stack up, wait for health, print URL
    start.sh                POSIX:   same
    stop.ps1                Windows: bring stack down (optionally wipe volume)
    stop.sh                 POSIX:   same
  docs/
    REQUIREMENTS.md
    DESIGN.md
  README.md
  CLAUDE.md
```

The backend container serves both the FastAPI API and the statically exported Next.js bundle (mounted at `/`). One container, same origin, relative URLs from the frontend.

A `.gitignore` at the repo root covers the full stack: Python (`__pycache__/`, `.venv/`, `*.egg-info/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`), Node / Next.js (`node_modules/`, `.next/`, `out/`), env files (`.env`, `.env.local`, `.env.*.local`), OS (`.DS_Store`, `Thumbs.db`), and IDE (`.vscode/`, `.idea/`). The exact file is produced during implementation.

## 3. Tech stack

| Concern | Choice | Notes |
| --- | --- | --- |
| Backend language | Python 3.12 | Latest stable. |
| Package manager / runner | `uv` | All Python is invoked through `uv` (`uv run pytest`, `uv add ...`, `uv sync`). Never call `python` or `pip` directly. Dependency lockfile is `uv.lock`. |
| Web framework | FastAPI | Locked by requirements. |
| Validation | pydantic v2 (+ pydantic-settings) | Idiomatic with FastAPI. |
| ORM | SQLAlchemy 2.0 (async) + asyncpg | Modern async API (`select(...)`), Mapped[] typing. |
| Migrations | Alembic | Auto-run on backend container startup before app boot. |
| HTTP client | httpx (AsyncClient) | For real-mode endpoint checks. |
| SMTP client | aiosmtplib | Async, fits the rest of the loop. |
| LLM client | `openai` Python SDK pointed at OpenRouter (`base_url="https://openrouter.ai/api/v1"`) | Documented integration path; gives us types and retry. |
| ASGI server | uvicorn | Standard. |
| Test framework | pytest + pytest-asyncio | Async fixtures. |
| Lint/format | ruff (lint + format) | Single tool. |
| Database | PostgreSQL 16 | Separate container. |
| Frontend framework | Next.js (latest, app router), static export | Locked by requirements. |
| Frontend language | TypeScript (strict) | |
| UI styling | Tailwind CSS | |
| Components | shadcn/ui (Radix under the hood) | Copy-in components, no heavy runtime. |
| Data fetching | TanStack Query | Cache, polling, mutations. |
| Forms | react-hook-form + zod | Shared schemas with backend not required for MVP. |
| Charts | Recharts | Sparkline strip + binned history view. |

## 4. Data model

Postgres tables, all `id` columns are `BIGSERIAL PRIMARY KEY` unless noted. Timestamps are `TIMESTAMPTZ`.

### 4.1 `users`
Seeded with a single row (`id=1`) by the initial Alembic migration. The application treats `user_id=1` as the implicit current user everywhere; the column exists on user-owned tables so a future release can introduce real auth without a migration.

- `id`, `email`, `name`, `created_at`.

### 4.2 `endpoints`
- `id`, `user_id` (FK users), `name`, `url`, `enabled` (bool, default true).
- `check_interval_seconds` (int, constrained to {30, 60, 300, 900}).
- `timeout_seconds` (int, 1–60, default 10).
- `next_due_at` (timestamptz, null until first scheduled run).
- **Streak state** (denormalized, updated on each check): `current_streak_outcome` (enum: `success`/`failure`/null), `current_streak_count` (int, default 0), `streak_started_at` (timestamptz, null).
- **Simulator config** (used only in simulated mode, always editable): `sim_failure_rate` (numeric 0–1), `sim_latency_min_ms` (int), `sim_latency_max_ms` (int), `sim_outage_windows` (JSONB array of `{start, end}` objects; semantics defined in §5.2).
- `created_at`, `updated_at`.

Indexes: `(user_id)`, partial `(next_due_at) WHERE enabled = true`.

### 4.3 `check_results`
- `id`, `endpoint_id` (FK), `checked_at`, `outcome` (enum: `success`/`failure`).
- `latency_ms` (int), `status_code` (int, nullable).
- `error_category` (enum: `timeout`/`connection_refused`/`dns`/`tls`/`non_2xx`/`other`, nullable), `error_message` (text, nullable).

Indexes: `(endpoint_id, checked_at DESC)`.

Retention: 30 days, enforced by the rollup job. Table partitioning by day is **not** done in the MVP; called out as future work in the README scale-out section.

### 4.4 `hourly_rollups`
- `id`, `endpoint_id`, `bucket_start` (timestamptz, truncated to hour, UTC).
- `total_checks`, `successful_checks`, `failed_checks` (ints), `uptime_pct` (numeric).

Unique `(endpoint_id, bucket_start)`. Retention: 180 days.

### 4.5 `daily_rollups`
- `id`, `endpoint_id`, `bucket_date` (date).
- `total_checks`, `successful_checks`, `failed_checks` (ints), `uptime_pct` (numeric).

Unique `(endpoint_id, bucket_date)`. Indefinite retention.

### 4.6 `incidents`
- `id`, `endpoint_id`, `started_at`, `ended_at` (nullable while open), `duration_seconds` (nullable while open).
- `frozen_timeline` (JSONB, **null while open, populated on close**): an array of check snapshots (`{checked_at, outcome, latency_ms, status_code, error_category, error_message}`), including the bracketing successes immediately before `started_at` and after `ended_at`.
- `created_at`.

Indexes: `(endpoint_id, started_at DESC)`; partial `(endpoint_id) WHERE ended_at IS NULL` for fast "is there an open incident?" lookup (and to enforce "at most one open incident per endpoint" via a partial unique index).

### 4.7 `postmortems`
- `id`, `incident_id` (FK, unique — one postmortem per incident).
- `content` (text, nullable; null means "never generated").
- `generated_at` (nullable), `edited_at` (nullable).

The unique FK means one row per incident; we upsert on generate and update on edit.

### 4.8 `email_recipients`
- `id`, `user_id` (FK), `address` (citext or text, validated at API), `created_at`.
- Unique `(user_id, address)`.

### 4.9 `sent_notifications`
- `id`, `kind` (enum: `incident_opened`/`incident_closed`), `incident_id` (FK), `subject` (text), `body` (text), `recipients` (JSONB array of email addresses, snapshotted at send time), `sent_at`.

**Ring buffer behavior**: enforced in application code in `LogSink.send_email()` — after INSERT, if `COUNT(*) > 1000`, DELETE rows with `id < (SELECT id FROM sent_notifications ORDER BY id DESC OFFSET 999 LIMIT 1)`. Single transaction with the insert.

## 5. Key interfaces (swap points)

These are the seams that let real/simulated and smtp/log modes plug in cleanly, and that make the system testable without network or wall-clock dependencies.

### 5.1 `Clock`
```python
class Clock(Protocol):
    def now(self) -> datetime: ...   # always tz-aware UTC

class RealClock: ...
class FakeClock:                       # for unit tests
    def set(self, t: datetime) -> None: ...
    def advance(self, delta: timedelta) -> None: ...
```
Injected via FastAPI `Depends`. Used by scheduler, simulator, rollup, and any service that needs "now". This is the single source of "what time is it" — nothing else calls `datetime.now()`.

### 5.2 `Checker`
```python
class Checker(Protocol):
    async def check(self, endpoint: Endpoint) -> CheckOutcome: ...

@dataclass
class CheckOutcome:
    outcome: Literal["success", "failure"]
    latency_ms: int
    status_code: int | None
    error_category: ErrorCategory | None
    error_message: str | None
```

- `RealChecker(http_client: httpx.AsyncClient, clock: Clock)`: performs HTTP GET against `endpoint.url` with `endpoint.timeout_seconds`. 2xx → success; anything else → failure with appropriate `error_category`.
- `SimulatedChecker(clock: Clock, rng: random.Random)`: produces a synthetic outcome from `endpoint.sim_*` fields. Semantics:
  - If `clock.now()` falls inside any window in `sim_outage_windows` → failure, error_category=`other`, message=`scheduled outage`.
  - Else draw `r = rng.random()`; if `r < sim_failure_rate` → failure (error_category chosen by a small weighted set: timeout / connection_refused / non_2xx); else success.
  - `latency_ms` uniformly drawn from `[sim_latency_min_ms, sim_latency_max_ms]` regardless of outcome.

`sim_outage_windows` entries are interpreted as **wall-clock time-of-day windows that repeat daily** (e.g., `{"start": "14:00", "end": "14:30"}` means down between 14:00 and 14:30 UTC every day). This keeps demos predictable without a date-aware scheduling system.

The choice between `RealChecker` and `SimulatedChecker` is made once at app startup based on `CHECK_SOURCE` and bound into the FastAPI dependency tree.

### 5.3 `AlertSink`
```python
class AlertSink(Protocol):
    async def send_email(self, kind: NotificationKind, incident: Incident,
                          recipients: list[str], subject: str, body: str) -> None: ...
```

- `SmtpSink(settings, clock)`: sends via aiosmtplib using env-configured SMTP credentials.
- `LogSink(session_factory, clock)`: inserts into `sent_notifications` and enforces the 1,000-row cap in the same transaction. Does not send anything outbound.

Bound at startup based on `EMAIL_SINK`.

## 6. Scheduler

A single asyncio task started inside the FastAPI app's `lifespan` context. The scheduler keeps an in-process `in_flight: set[int]` of endpoint IDs whose check is currently running, so it never spawns a duplicate check for the same endpoint. Loop body:

1. `now = clock.now()`.
2. Query: enabled endpoints where `(next_due_at IS NULL OR next_due_at <= now) AND id NOT IN in_flight`, ordered by `next_due_at NULLS FIRST`.
3. For each row, add `endpoint.id` to `in_flight` and spawn a `check_endpoint(endpoint_id)` task. The actual check is wrapped by an `asyncio.Semaphore` (default cap **50**) so a burst of due endpoints can't open hundreds of sockets at once.
4. `await asyncio.sleep(1.0)` then loop.

`check_endpoint(endpoint_id)`:
1. Re-fetch the endpoint row (one row, current state).
2. `outcome = await checker.check(endpoint)` (real or simulated checker — injected, not branched here).
3. `INSERT INTO check_results (...)`.
4. Update streak state on the endpoint row (next subsection).
5. Advance the schedule: `new_next_due_at = max(endpoint.next_due_at + interval, now)`. This anchors cadence to the original schedule rather than completion time, but never schedules in the past (so a scheduler that fell behind catches up to "now + interval" rather than firing repeatedly).
6. In a `try/finally`, remove `endpoint_id` from `in_flight` so the next loop tick can re-pick it once it's due again.

#### Why an in-memory `in_flight` set

Without it, a check that takes longer than the loop sleep (1 s) — which is normal for the default 10 s timeout — would still match the "due" query on the next tick, and the scheduler would spawn a second concurrent check for the same endpoint. With a dead endpoint hitting timeout, this would cascade.

The set is single-process state, which is correct for the single-process MVP. On crash, the set is lost; on restart the endpoint shows as due and is re-checked immediately, which is the desired behavior anyway.

The multi-process equivalent (proper claim-based dispatch using `SELECT ... FOR UPDATE SKIP LOCKED` against the endpoints table, or moving claim state to a separate queue) is covered in the README scale-out section. The MVP does not need it.

#### Why store `next_due_at` on the endpoint vs. recompute from history

Makes the "what's due?" query trivially indexable (partial index on `next_due_at WHERE enabled = true`), and survives restarts cleanly: a check that was due during downtime fires on the next loop tick.

### 6.1 Streak and incident transitions

On each check result:

```
if outcome.outcome == endpoint.current_streak_outcome:
    endpoint.current_streak_count += 1
else:
    endpoint.current_streak_outcome = outcome.outcome
    endpoint.current_streak_count = 1
    endpoint.streak_started_at = check.checked_at
```

Then:

- **If streak is failure and count just reached N (=3) and no open incident exists for this endpoint**: insert a new `incidents` row with `started_at = endpoint.streak_started_at`, `ended_at = null`. Enqueue an `incident_opened` alert.
- **If streak is success and count just reached M (=2) and an open incident exists**: set `ended_at = endpoint.streak_started_at`, `duration_seconds`, build `frozen_timeline` by querying `check_results` for `[ended_at_of_previous_success_before_started_at, current_check.checked_at]` and serializing to JSONB. Enqueue an `incident_closed` alert.

All of the above is one DB transaction per check.

Alerts are dispatched by calling `alert_sink.send_email(...)` directly inside that transaction's `after_commit` hook, or fire-and-forget after commit. We **do not** introduce a queue for the MVP.

### 6.2 Bounded concurrency

`asyncio.Semaphore(50)` wraps the actual HTTP/simulator call so a slow endpoint cannot starve scheduling. DB writes are not gated (they're fast and per-connection).

## 7. Rollup job

A second asyncio task, also lifespan-managed. Runs every 5 minutes (and on demand via API). Per run:

1. **Hourly rollups**: re-aggregate hour buckets across the full raw window (`checked_at >= now - 30 days`). For each `(endpoint_id, hour)`: `INSERT ... ON CONFLICT (endpoint_id, bucket_start) DO UPDATE SET ...` with aggregated counts and `uptime_pct`.
2. **Daily rollups**: same pattern across the full hourly window (`bucket_start >= now - 180 days`), computed **from `hourly_rollups`** (cheaper than scanning raw and consistent with the read-routing). UPSERT into `daily_rollups`.
3. **Raw retention**: `DELETE FROM check_results WHERE checked_at < now - INTERVAL '30 days'`.
4. **Hourly retention**: `DELETE FROM hourly_rollups WHERE bucket_start < now - INTERVAL '180 days'`.

The lookback for each rollup tier equals that tier's retention window rather than a narrow recent slice. Idempotent UPSERT makes this safe to repeat, and the wide window means a rollup job that missed runs — or a `Run rollup now` click after extended downtime — recovers without any catch-up logic. At MVP scale (≤ 200 endpoints × 30 days × hourly buckets ≈ 144k rows) the cost is negligible; if it ever isn't, narrowing to `now - 2 h` / `now - 2 d` is a one-line change. The §13 seed extension (`run_once(full=True)`) widens the lookback further still, to cover the bulk-inserted 75-day backfill before retention sweeps it.

### 7.1 Storage tier read-routing

`history_service.fetch_history(endpoint_id, range)`:

| Range | Source |
| --- | --- |
| ≤ 24 hours | `check_results` (raw) |
| > 24 hours and ≤ 14 days | `hourly_rollups` |
| > 14 days | `daily_rollups` |

`uptime_service.uptime_percentages(endpoint_id)` returns `{24h, 7d, 30d}` computed from raw, hourly, and daily respectively (raw covers 30 days but hourly is cheaper for 7d; daily is correct for 30d).

The frontend tooltip labels which tier a bin came from based on the response payload (each bin includes a `source: "raw" | "hourly" | "daily"` field).

## 8. REST API surface

Mounted at `/api/v1`. JSON in/out. All endpoints assume implicit `user_id=1`. No auth.

```
GET    /endpoints
POST   /endpoints
GET    /endpoints/{id}
PUT    /endpoints/{id}
DELETE /endpoints/{id}
POST   /endpoints/{id}/enable
POST   /endpoints/{id}/disable
GET    /endpoints/{id}/recent-checks?limit=60
GET    /endpoints/{id}/history?range=1h|1d|7d|30d|90d|1y
GET    /endpoints/{id}/uptime                          → {h24, d7, d30}

GET    /incidents?state=active|closed|all&endpoint_id=...
GET    /incidents/{id}
POST   /incidents/{id}/postmortem/generate
PUT    /incidents/{id}/postmortem                      body: {content}

GET    /recipients
POST   /recipients
DELETE /recipients/{id}

GET    /notifications?limit=100&before_id=...          (ring-buffer view, newest first)

GET    /storage/stats                                  raw/hourly/daily counts, retention, next run
POST   /storage/rollup-now

GET    /system/status                                  {check_source, email_sink, smtp_from, n, m}
```

Errors follow FastAPI defaults (`{detail: ...}`); validation errors are 422 with pydantic detail.

Live updates: the frontend polls (`refetchInterval` on TanStack Query) at 5s for the dashboard and 2s for an active incident view. **No SSE/WebSockets in the MVP**; flagged as a future improvement.

## 9. Frontend structure

Static export (`output: 'export'`), served by FastAPI at `/`. Same-origin → relative API URLs.

Pages (app router):

- `/` Dashboard: list of endpoints with state badge, recent-check strip (60 ticks), uptime %; active incidents banner at top.
- `/endpoints` Manage: table view with create/edit/delete dialogs (shadcn).
- `/endpoints/[id]` Detail: granularity-aware history chart (Recharts), recent check log table.
- `/incidents` List: filterable by state.
- `/incidents/[id]` Detail: incident timeline rendered from `frozen_timeline` (or live from `check_results` while open), postmortem panel with Generate / Edit / Regenerate.
- `/notifications` Sent notifications panel (ring buffer view).
- `/settings` Recipients editor, Storage panel with `Run rollup now`, mode badges (read-only display of `check_source`, `email_sink`, SMTP from, N, M).

Persistent top banner appears whenever `check_source == "simulated"` or `email_sink == "log"`.

Data fetching: TanStack Query with typed fetch wrapper in `lib/api.ts`. No global state library; all server state lives in React Query cache, all UI state in `useState`/`useReducer`.

## 10. Configuration

All config via env vars, validated by `pydantic-settings`:

| Var | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | — | Postgres connection string (e.g., `postgresql+asyncpg://...`). |
| `CHECK_SOURCE` | `real` | `real` or `simulated`. |
| `EMAIL_SINK` | `smtp` | `smtp` or `log`. Application default is `smtp`, but `docker-compose.yml` overrides to `log` so the default stack runs without SMTP credentials; opt in to `smtp` via `docker-compose.smtp.yml` (`--smtp`). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS` | — | Only required if `EMAIL_SINK=smtp`. Passed through from `.env` by `docker-compose.smtp.yml`. |
| `OPENROUTER_API_KEY` | — | Required for AI postmortem. If unset, the Generate button returns a clear error. |
| `OPENROUTER_MODEL` | `openai/gpt-oss-120b` | Overridable for experimentation. |
| `SCHEDULER_CONCURRENCY` | `50` | Semaphore cap; tunable without code change. |
| `LOG_LEVEL` | `INFO` | |

Secrets are read from `.env` in local dev, from the container environment in deployed mode. `.env` is gitignored.

## 11. AI integration

```python
client = openai.AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key,
)

response = await client.chat.completions.create(
    model=settings.openrouter_model,
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": render_incident_prompt(incident)},
    ],
    temperature=0.3,
    max_tokens=800,
)
```

Prompt assembly in `ai/prompts.py`:

- System prompt fixes voice (plain English, neutral, no speculation beyond evidence), structure (short narrative, suggested cause, suggested next steps), and length.
- User prompt is a deterministic rendering of the incident: endpoint name + URL, start/end/duration, then a compact table of the frozen timeline rows.

The API endpoint that backs Generate is a thin wrapper: build prompt → call client → store result in `postmortems.content`, set `generated_at`. Failures surface as 502 with a human-readable detail.

## 12. Testing approach

Three layers, all driven by pytest.

### Unit (no DB, no network)
- Streak/incident transition logic (table-driven: sequences of outcomes → expected state, expected open/close events).
- Rollup math.
- `SimulatedChecker` with `FakeClock` and seeded RNG: deterministic outcomes for known inputs.
- Storage tier read-routing decision.
- Prompt assembly (snapshot tests).

### Integration (real Postgres, fake clock + simulated checker + log sink)
- API endpoints end-to-end.
- Scheduler tick: insert a few endpoints, advance the fake clock, assert the right checks landed and the right rollups exist.
- Incident lifecycle: synthesize a failure streak, assert incident opens, postmortem can be generated (with a mocked AI client), incident closes, `frozen_timeline` populated, alert hits the log sink.

Test DB is a separate Postgres database created/dropped per test session (`pytest` fixture); Alembic migrations run once.

### Smoke (manual or one-shot CI)
- `docker compose up`, hit `/api/v1/system/status`, create an endpoint, assert it gets checked.

### Frontend
- TypeScript `tsc --noEmit` in CI.
- A small number of component tests via React Testing Library for non-trivial widgets (recent-check strip, granularity-aware chart) — no full E2E browser tests in the MVP.

## 13. Demo pre-seeding

`seed.py`, called from app startup, runs only when **all** of:

- `CHECK_SOURCE == "simulated"`,
- `EMAIL_SINK == "log"`,
- `SELECT COUNT(*) FROM endpoints == 0`.

Entrypoint: `maybe_seed(session_factory, clock, days: int = 75, rng_seed: int = 0)`. The `days` parameter exists so integration tests can run with 1-2 days (sub-second) while production startup uses 75. The seeder produces the DB state that 75 days of live operation would have produced, without per-check DB I/O, by simulating outcomes in memory and persisting only what survives retention plus what aggregation would have produced.

Phases:

1. **Endpoints.** Insert 5 example endpoints with simulator configs spanning all four interval choices:
   - `api-prod` — 0.5% failure, 80-200 ms, 60s.
   - `marketing-site` — 0.5% failure, 80-200 ms, 300s.
   - `metrics-collector` — 3% failure, 100-400 ms, 30s.
   - `payments-webhook` — 8% failure, 150-600 ms, 60s.
   - `nightly-batch` — 1% failure, 80-200 ms, 900s, one daily outage window (e.g. 03:00-03:15 UTC).

   This mix yields roughly 400k synthetic raw rows over 75 days, of which ~160k survive the 30-day retention sweep — comfortably bulk-insertable in seconds.

2. **Simulate in memory.** For each endpoint, walk `t` forward from `now - days` to `now` in steps of `check_interval_seconds`. At each step: call `SimulatedChecker.check()` against the endpoint's sim config and `t`, append a `CheckResult` row dict to a buffer, and feed the outcome through `streak_step()` (the extracted state machine, §13.1). When `streak_step` signals an incident close, build the incident's `frozen_timeline` from the in-memory buffer (slice from the preceding success before `started_at` through the current step) and append an `Incident` row dict with timeline already populated. No DB I/O during this phase.

3. **Bulk persist.** In one (or a few batched) transactions: `session.execute(insert(CheckResult), [...])` in batches of ~5,000 over the accumulated check rows, then bulk insert all accumulated incidents.

4. **Backfill rollups + retention sweep.** Call `RollupJob.run_once(full=True)`: this widens the hourly UPSERT lookback to cover the entire seeded period rather than the steady-state 30-day window, then applies the normal retention deletes (raw > 30 d, hourly > 180 d). After this, the DB shape is identical to what 75 days of live operation would have produced.

Alerts are **not** dispatched during seeding — the dispatcher and alert sinks are bypassed entirely. `sent_notifications` is reserved for live activity. A fixed `rng_seed` makes the seeded history reproducible, useful when iterating on UI against a stable incident set.

### 13.1 Streak state machine extraction

To keep the scheduler path and the seeder path on identical incident logic without dragging DB I/O into the seeder, the streak update + open/close decision is extracted from `incident_service.apply_check_result` into a pure function:

```python
@dataclass(frozen=True)
class StreakState:
    outcome: StreakOutcome | None
    count: int
    started_at: datetime | None

@dataclass(frozen=True)
class StreakDecision:
    next_state: StreakState
    open_at: datetime | None    # set on the check that hits N consecutive failures
    close_at: datetime | None   # set on the check that hits M consecutive successes

def streak_step(state: StreakState, outcome: StreakOutcome, checked_at: datetime) -> StreakDecision: ...
```

`apply_check_result` keeps its DB responsibilities (open-incident SELECT, frozen-timeline read from `check_results`, incident INSERT/UPDATE) but delegates the decision to `streak_step`. The seeder calls `streak_step` directly against its in-memory buffer. Existing incident unit tests are simplified to drive `streak_step` synchronously.

## 14. Local operations: start / stop scripts

Thin wrappers around `docker compose` so a fresh clone can be brought up with one command on either Windows or POSIX. The scripts contain no business logic — all mode wiring is in compose files — so they stay tiny and don't drift from `docker compose` semantics.

### Files

- `docker-compose.yml` — base stack (backend + Postgres). Defaults: `CHECK_SOURCE=real`, `EMAIL_SINK=log`. The `log` default keeps the OOTB experience runnable without SMTP credentials; real SMTP is opt-in.
- `docker-compose.demo.yml` — override that sets `CHECK_SOURCE=simulated` on the backend service. Applied with `-f docker-compose.yml -f docker-compose.demo.yml`.
- `docker-compose.smtp.yml` — override that sets `EMAIL_SINK=smtp` and passes `SMTP_HOST`/`SMTP_PORT`/`SMTP_USERNAME`/`SMTP_PASSWORD`/`SMTP_FROM`/`SMTP_STARTTLS` through from `.env`. Applied with `-f docker-compose.yml -f docker-compose.smtp.yml`.
- `scripts/start.ps1`, `scripts/start.sh` — start the stack.
- `scripts/stop.ps1`, `scripts/stop.sh` — stop the stack.

### `start` behavior

1. Parse flags: `--demo` / `-Demo` (include `-f docker-compose.demo.yml`); `--smtp` / `-Smtp` (include `-f docker-compose.smtp.yml`). Flags can be combined.
2. `docker compose [files] up -d --build`.
3. Poll `http://localhost:8000/api/v1/system/status` every 1 s for up to 60 s; fail with a clear error if it never returns 200.
4. Print the local URL and the active mode badges (e.g., `check_source=simulated, email_sink=log`).

### `stop` behavior

1. Parse flag: `--wipe` (POSIX) / `-Wipe` (PowerShell).
2. `docker compose down`. With `--wipe`/`-Wipe`, also pass `-v` to drop the Postgres volume (full reset, including pre-seeded demo data so the next `start --demo` re-seeds from scratch).
3. Print a one-line confirmation.

### Exit codes

Both scripts: `0` on success, non-zero on any failure (compose error, health-check timeout, etc.). PowerShell scripts use `$LASTEXITCODE` propagation; bash scripts use `set -euo pipefail`.

## 15. Open design questions

These don't block the implementation plan but should be resolved during build:

- **Static export served by FastAPI**: pick the exact strategy (StaticFiles mount at `/` plus a catch-all that serves `index.html` for client-side-routed paths). Straightforward; just needs to be set up correctly.
- **Alembic on startup**: run `alembic upgrade head` as the container entrypoint, before launching uvicorn. Confirm this plays well with multiple replicas in the README scale-out section (it won't — would need a separate migrations job).
- **Frontend dev experience**: during local development, run `next dev` on port 3000 with API calls proxied to `:8000`. In docker compose, only the static-export build runs. Document both in the README.
- **AI cost ceiling for public demo**: spend-cap on the OpenRouter key is the chosen mitigation (per requirements §8). No app-level rate limiting in the MVP; revisit if needed.
- **Time zone of `sim_outage_windows`**: spec'd above as UTC time-of-day. UI must label this clearly when editing.
