# Heartbeat Monitor

Heartbeat Monitor is a self-hosted uptime monitor and status page. It polls user-registered HTTP(S) endpoints on a schedule, records every check result, raises incidents when an endpoint fails repeatedly, and generates AI-powered plain-English postmortem drafts on demand. A simulated mode replaces real HTTP checks with synthetic results so the full product can be explored without any live endpoints or outbound email.

**[Live demo](https://heartbeat-monitor-demo.fly.dev/)** — simulated mode, five pre-seeded endpoints, 75 days of synthetic history. No sign-in.

![CI](https://github.com/lcampanella98/heartbeat-monitor/actions/workflows/ci.yml/badge.svg) — every push to `main` runs lint, type checks, and the full test suite before deploying.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL 16 · Next.js (static export) · TypeScript · Tailwind · TanStack Query · Recharts · Docker · Fly.io

---

## Screenshots

_Dashboard with endpoint state badges, recent-check strips, and uptime percentages:_

![Dashboard](screenshots/dashboard.png)

_Incident detail with AI-generated postmortem draft:_

![Incident detail](screenshots/incident-detail.png)

_Settings — storage panel and recipients editor:_

![Settings](screenshots/settings.png)

## Highlights

- **Async scheduler with bounded concurrency.** ~200 endpoints comfortably on one process; a 50-wide `asyncio.Semaphore` prevents a slow endpoint from starving the rest.
- **Three-tier storage with granularity-aware reads.** Raw checks (30 d) → hourly rollups (180 d) → daily rollups (indefinite). The history endpoint auto-routes to the right tier based on requested range.
- **Swappable subsystems via dependency injection.** `Checker` (real / simulated) and `AlertSink` (SMTP / log) are bound at startup from env vars — same code path, different bindings, fully testable without network or mail.
- **Frozen incident timelines + AI postmortems.** When an incident closes, its check timeline is snapshotted onto the incident row so postmortem generation remains usable even after raw checks age out. Postmortems are generated via OpenRouter on demand and are user-editable.
- **Production packaging.** Dockerized, Alembic migrations run on container start, GitHub Actions CI, deployed to Fly.io.

## How would we scale this?

Today the application is a single FastAPI process: an async scheduler loop selects due endpoints from Postgres, tracks in-flight checks in a process-local set, runs HTTP checks with a 50-wide semaphore, and writes results, rollups, and alerts inline. This is the right shape for one user and ~200 endpoints. Here is the path it would walk as load grows, one step at a time — each step solves a problem the previous shape would hit, and Postgres remains the source of truth throughout.

**Separate scheduler service.** _When API and scheduler load compete for the same event loop, or backend deploys cannot pause checks._ Extract the scheduler loop into its own process so it deploys and scales independently of the API.

**Claim-based dispatch with `SELECT ... FOR UPDATE SKIP LOCKED`.** _Once you want more than one scheduler/worker — for horizontal scale or HA — the in-memory in-flight set no longer deduplicates across processes._ Replace it with row-locked claims on the endpoints table: each worker grabs a batch of due rows, `FOR UPDATE` locks them exclusively, `SKIP LOCKED` lets peer workers route around already-claimed rows instead of blocking. The endpoints table becomes a safe job queue with zero new infrastructure. Redis Streams is the higher-throughput alternative once Postgres can't keep up.

**Stateless check workers.** _When a single worker's CPU or socket budget bottlenecks, or capacity needs to scale quickly during incidents._ Run N worker replicas that pull from the queue, perform HTTP checks, and emit results to a results queue — keeping the check hot path I/O-free and horizontally scalable. A single result writer consumes the results queue and owns DB writes.

**Separate alert worker.** _When a slow or flaky mail server back-pressures the result pipeline._ Move alert dispatch (SMTP sends, notification writes) into its own consumer process so SMTP latency cannot stall check processing.

**Partition raw `check_results` by day.** _When `DELETE FROM check_results WHERE checked_at < now() - INTERVAL '30 days'` becomes slow and bloats the table with dead tuples._ PostgreSQL declarative partitioning makes retention instant (`DROP TABLE` of yesterday's partition) and keeps per-day scans small. TimescaleDB is the natural next step — it automates partition management and adds continuous aggregates that maintain rollups for free.

**Cold object-storage archive.** _When long-range history is rare but the cost of keeping years of data hot in Postgres dominates the bill._ Export daily rollups and aged-out raw partitions to S3 or GCS as Parquet (10-20x smaller than rows; object storage ~$0.02/GB/month vs $0.10-0.20 for managed Postgres). Serve long-range queries via DuckDB in-process; Athena is the managed alternative.

**Push-based UI updates.** _When polling overhead becomes visible — many clients each polling every 2-5 seconds even when nothing has changed._ Replace TanStack Query polling with Server-Sent Events so the dashboard reflects new check results and incident state changes in real time. SSE is the right fit here: one-way, plain HTTP, auto-reconnecting, no protocol handshake.

## Modes

Two independent runtime switches govern check and alert behavior:

| Switch | Env var | Values | Default |
|---|---|---|---|
| Check source | `CHECK_SOURCE` | `real` / `simulated` | `real` |
| Email sink | `EMAIL_SINK` | `smtp` / `log` | `smtp` |

**`CHECK_SOURCE=real`** — the scheduler makes actual HTTP GET requests to each endpoint's URL.

**`CHECK_SOURCE=simulated`** — no outbound HTTP. The scheduler generates synthetic results from each endpoint's simulator config (failure rate, latency range, optional outage windows).

**`EMAIL_SINK=smtp`** — alert emails are sent through your configured SMTP server when incidents open or close.

**`EMAIL_SINK=log`** — alert emails are captured to the database and shown in the in-app Sent Notifications panel; nothing is sent outbound.

The switches are independent: you can run real checks with a log sink in development, or simulated checks with SMTP for staging. A visible banner appears in the UI whenever either switch is in its non-default state.

## Run the demo locally

Requires Docker and Docker Compose.

```sh
./scripts/start.sh --demo   # start in simulated mode with log email sink
# visit http://localhost:8000
./scripts/stop.sh --wipe    # stop and wipe the database volume (re-seed on next start)
```

On Windows (PowerShell):

```powershell
.\scripts\start.ps1 -Demo
# visit http://localhost:8000
.\scripts\stop.ps1 -Wipe
```

The `--demo` flag sets `CHECK_SOURCE=simulated` and `EMAIL_SINK=log`. On first startup against an empty database, the backend pre-seeds ~75 days of synthetic history across five example endpoints, including several past incidents and rollup data in all three storage tiers.

To start in real mode (live HTTP checks, SMTP alerts), copy `.env.example` to `.env`, fill in `DATABASE_URL` and your SMTP credentials, then run `./scripts/start.sh` without `--demo`.

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` for local development.

| Variable | Default | Required | Description |
|---|---|---|---|
| `DATABASE_URL` | — | Yes | Postgres connection string, e.g. `postgresql+asyncpg://user:pass@db:5432/heartbeat` |
| `CHECK_SOURCE` | `real` | No | `real` or `simulated` |
| `EMAIL_SINK` | `smtp` | No | `smtp` or `log` |
| `SMTP_HOST` | — | If `EMAIL_SINK=smtp` | SMTP server hostname |
| `SMTP_PORT` | `587` | No | SMTP server port |
| `SMTP_USERNAME` | — | If `EMAIL_SINK=smtp` | SMTP username |
| `SMTP_PASSWORD` | — | If `EMAIL_SINK=smtp` | SMTP password |
| `SMTP_FROM` | — | If `EMAIL_SINK=smtp` | From address for alert emails |
| `SMTP_STARTTLS` | `true` | No | Whether to use STARTTLS |
| `OPENROUTER_API_KEY` | — | For AI postmortems | API key for OpenRouter (used by the postmortem generator) |
| `OPENROUTER_MODEL` | `openai/gpt-oss-120b` | No | LLM model to use via OpenRouter |
| `SCHEDULER_CONCURRENCY` | `50` | No | Max concurrent in-flight checks |
| `LOG_LEVEL` | `INFO` | No | Backend log level |

For a public demo deployment, set a spend cap on your OpenRouter key to bound exposure from repeated postmortem generation.

## Design and implementation docs

- [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) — product scope, behaviors, and non-goals.
- [`docs/DESIGN.md`](docs/DESIGN.md) — technical decisions: data model, key interfaces, scheduler, storage tiers, AI integration.
- [`docs/PLAN.md`](docs/PLAN.md) — phased implementation order with per-phase acceptance criteria.
