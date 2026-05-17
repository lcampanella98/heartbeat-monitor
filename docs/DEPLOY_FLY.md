# Heartbeat Monitor — Demo deployment on Fly.io

Status: Draft. A step-by-step plan to deploy the demo build (`CHECK_SOURCE=simulated`, `EMAIL_SINK=log`) to Fly.io with GitHub Actions doing the deploys. Same phased layout as `docs/PLAN.md` — each phase ends at a checkable state.

## 0. Decisions

Locked in before writing the plan:

- **App names**: `heartbeat-monitor-demo` (backend), `heartbeat-monitor-db` (Postgres).
- **Region**: `iad` (Ashburn) for both apps.
- **OpenRouter**: `OPENROUTER_API_KEY` is set as a Fly secret on the backend so Generate Postmortem works in the demo.
- **Migrations**: moved out of `Dockerfile.backend` CMD into Fly's `release_command`. `docker-compose.yml` gets a `command:` override that restores the old behavior for local dev.
- **CI gating**: a `ci.yml` workflow runs lint + tests on PRs and on `main`. `deploy.yml` calls `ci.yml` as a reusable workflow and only deploys if it passes.
- **Postgres password**: generated with `openssl rand` at deploy time, stored as a Fly secret, saved by hand. No rotation workflow in the MVP.

## 1. Architecture

Two Fly apps in the same Fly organization, talking over Fly's private IPv6 network (`<app>.internal` DNS):

- `heartbeat-monitor-demo` — the backend image (FastAPI + scheduler + rollup + static Next.js export). One always-on machine, no auto-stop.
- `heartbeat-monitor-db` — `postgres:16` with a persistent volume. One machine, no auto-stop.

Why not managed Fly Postgres: it is now ~$25/mo for the smallest configuration. Rolling our own `postgres:16` on a `shared-cpu-1x / 256MB` machine with a 3 GB volume is a few dollars and matches what we already run in `docker-compose.yml`.

Why one always-on machine and not scale-to-zero: the scheduler and rollup loops live inside the FastAPI `lifespan` (`DESIGN.md` §6, §7). A stopped machine means no checks run. We disable `auto_stop_machines` and set `min_machines_running = 1`.

The frontend is already baked into the backend image (`Dockerfile.backend` stage 1 builds Next.js, stage 2 copies `out/` into `./static`). One image, one deploy.

## Conventions

- Commands prefixed with `$` run on your workstation; commands prefixed with `#` run inside a Fly machine.
- Every Fly app gets `--org <org>` explicitly so we never deploy to the wrong org.
- Secrets are set with `flyctl secrets set` — never committed.
- App names are placeholders; the names must be globally unique on `fly.dev`, so substitute your own.

---

## Phase A — Account, CLI, and org - DONE

**Goal:** A working `flyctl` on your workstation, signed in, with a Fly org that can host two apps.

**Tasks**

1. Install `flyctl` (Windows: `iwr https://fly.io/install.ps1 -useb | iex`; macOS/Linux: `curl -L https://fly.io/install.sh | sh`).
2. `$ flyctl auth signup` (or `flyctl auth login` if you already have an account). Sign-up requires a payment method even though demo usage is in the low single-digit dollars per month.
3. `$ flyctl orgs list` — note the org slug you want to use (`personal` by default).
4. `$ flyctl platform regions` — pick a region close to you. For the US east coast, `iad` (Ashburn) or `ewr` (Newark) are the usual picks. Both apps go in the same region (private networking is org-wide, but co-locating cuts latency).

**Done when**

- `flyctl auth whoami` prints your email and `flyctl orgs list` shows the org you'll deploy into.

---

## Phase B — Repo changes - DONE

**Goal:** The repo carries the Fly configuration files and one small Dockerfile tweak. No runtime code changes.

**Tasks**

1. **Move Alembic out of CMD into a Fly release command.** This resolves the open question in `DESIGN.md` §15 and avoids two machines running `alembic upgrade head` concurrently if we ever scale out.

   Edit `Dockerfile.backend` so the final `CMD` is just uvicorn:

   ```
   CMD ["uv", "run", "uvicorn", "heartbeat.main:app", "--host", "0.0.0.0", "--port", "8000"]
   ```

   Restore the old behavior for local dev by adding `command:` to the `backend` service in `docker-compose.yml`:

   ```yaml
     backend:
       # ...existing keys...
       command: sh -c "uv run alembic upgrade head && uv run uvicorn heartbeat.main:app --host 0.0.0.0 --port 8000"
   ```

   This keeps `scripts/start.sh --demo` working unchanged. On Fly, the bare CMD runs at runtime and migrations are handled separately via `release_command` (step 2).

2. **Backend `fly.toml`** at repo root:

   ```toml
   app = "heartbeat-monitor-demo"
   primary_region = "iad"

   [build]
     dockerfile = "Dockerfile.backend"

   [deploy]
     release_command = "uv run alembic upgrade head"

   [env]
     CHECK_SOURCE = "simulated"
     EMAIL_SINK = "log"
     LOG_LEVEL = "INFO"
     SCHEDULER_CONCURRENCY = "50"

   [http_service]
     internal_port = 8000
     force_https = true
     auto_stop_machines = "off"
     auto_start_machines = false
     min_machines_running = 1

     [[http_service.checks]]
       grace_period = "30s"
       interval = "15s"
       method = "GET"
       timeout = "5s"
       path = "/api/v1/system/status"

   [[vm]]
     size = "shared-cpu-1x"
     memory = "512mb"
   ```

   Notes: 512 MB (not 256 MB) for the backend — uvicorn + SQLAlchemy + the seed run for 75 days of simulated history (`DESIGN.md` §13) is more comfortable with the extra headroom. `auto_stop_machines = "off"` is the critical line for the scheduler.

3. **Postgres `fly.postgres.toml`** at repo root (separate file so `flyctl deploy -c fly.postgres.toml` targets it explicitly):

   ```toml
   app = "heartbeat-monitor-db"
   primary_region = "iad"

   [build]
     image = "postgres:16"

   [env]
     POSTGRES_DB = "heartbeat"
     POSTGRES_USER = "heartbeat"
     PGDATA = "/var/lib/postgresql/data/pgdata"

   [mounts]
     source = "pg_data"
     destination = "/var/lib/postgresql/data"

   [[services]]
     internal_port = 5432
     protocol = "tcp"
     auto_stop_machines = "off"
     auto_start_machines = false
     min_machines_running = 1

     [[services.ports]]
       port = 5432

   [[vm]]
     size = "shared-cpu-1x"
     memory = "256mb"
   ```

   `POSTGRES_PASSWORD` is **not** in the file — it's a Fly secret set in Phase C. `PGDATA` points inside the mounted volume so the database survives machine replacement.

4. **`.dockerignore`** (if not present) at repo root so the build context stays small:

   ```
   .git
   .venv
   node_modules
   frontend/.next
   frontend/out
   backend/.pytest_cache
   backend/.ruff_cache
   __pycache__
   ```

5. **GitHub Actions workflow** at `.github/workflows/deploy.yml` — covered in detail in Phase E. Listed here so the file inventory for this phase is complete.

**Done when**

- `git status` shows: edited `Dockerfile.backend`, new `fly.toml`, new `fly.postgres.toml`, new/updated `.dockerignore`, new `.github/workflows/deploy.yml`.
- Local `scripts/start.sh --demo` still brings the stack up and `/api/v1/system/status` returns 200 (migrations still happen — either via the entrypoint wrapper or compose `command`).

---

## Phase C — Deploy the Postgres app - DONE

**Goal:** A reachable Postgres instance on `heartbeat-monitor-db.internal:5432` with a persistent volume.

**Tasks**

1. `$ flyctl apps create heartbeat-monitor-db --org <org>`.
2. `$ flyctl volumes create pg_data --app heartbeat-monitor-db --region iad --size 3 --yes`. (3 GB is comfortable headroom; `DESIGN.md` §13 estimates ~160k surviving raw rows after the 30-day retention sweep on the seeded 75 days.)
3. `$ flyctl secrets set POSTGRES_PASSWORD=$(openssl rand -hex 24) --app heartbeat-monitor-db`. Save the value somewhere — you need it for the backend's `DATABASE_URL` in Phase D.
4. `$ flyctl deploy -c fly.postgres.toml --remote-only`. `--remote-only` builds on Fly's builders so your local arch (ARM Mac, Windows) doesn't matter.
5. `$ flyctl status --app heartbeat-monitor-db` — confirm one machine in `started` state.
6. Verify connectivity from a throwaway machine:
   ```
   $ flyctl ssh console --app heartbeat-monitor-db
   # psql -U heartbeat -d heartbeat -c "select 1;"
   ```

**Done when**

- `flyctl status --app heartbeat-monitor-db` shows one running machine with the `pg_data` volume mounted.
- `psql` inside the machine returns `1`.

---

## Phase D — Deploy the backend app

**Goal:** `https://heartbeat-monitor-demo.fly.dev` serves the static frontend at `/` and the API at `/api/v1/...`, with scheduler and rollup loops running.

**Tasks**

1. `$ flyctl apps create heartbeat-monitor-demo --org <org>`.
2. Set secrets (substitute the password from Phase C step 3 and your OpenRouter key):
   ```
   $ flyctl secrets set --app heartbeat-monitor-demo \
       DATABASE_URL="postgresql+asyncpg://heartbeat:<password>@heartbeat-monitor-db.internal:5432/heartbeat" \
       OPENROUTER_API_KEY="<key>"
   ```
3. First deploy:
   ```
   $ flyctl deploy --remote-only
   ```
   Watch the output. The `release_command` will run `alembic upgrade head` on a one-shot machine; if that fails the deploy aborts before traffic shifts.
4. `$ flyctl status` and `$ flyctl logs` — check for:
   - Migrations applied (`alembic upgrade head` ran clean in release).
   - `seed.maybe_seed` reporting it inserted the 5 demo endpoints + bulk rows (only fires on first boot since DB is empty; condition per `DESIGN.md` §13).
   - Scheduler tick logs (whatever you log at INFO from `scheduler.py`).
5. Visit `https://heartbeat-monitor-demo.fly.dev/` — the dashboard should render with the 5 seeded endpoints and 75 days of synthesized history.
6. Hit `https://heartbeat-monitor-demo.fly.dev/api/v1/system/status` — should return `check_source=simulated, email_sink=log`.

**Done when**

- Both apps are `started` in `flyctl status`.
- The dashboard loads, shows seeded endpoints, and the recent-check strip is advancing (proves the scheduler is running in-process).
- The persistent top banner shows `Simulated / Log` mode (per `DESIGN.md` §9).

---

## Phase E — GitHub Actions CI + auto-deploy

**Goal:** PRs and pushes run lint + tests. Pushes to `main` redeploy the backend app, but only if CI passes. (Postgres is deployed once and rarely touched; we don't redeploy it from CI.)

The two workflows are split as the user requested:

- `ci.yml` — runs lint + tests. Also exposed as a **reusable workflow** (`on: workflow_call`) so `deploy.yml` can invoke it.
- `deploy.yml` — runs on push to `main`. First job calls `ci.yml`; the deploy job has `needs: ci` so it only runs if CI succeeded.

**Tasks**

1. **Fly deploy token.** Create one scoped to the backend app:
   ```
   $ flyctl tokens create deploy --app heartbeat-monitor-demo --name "github-actions" --expiry 8760h
   ```
   Copy the printed token. In the GitHub repo: Settings → Secrets and variables → Actions → New repository secret. Name: `FLY_API_TOKEN`, value: the token.

2. **`.github/workflows/ci.yml`** — the reusable CI workflow. Backend tests need Postgres (`backend/tests/integration/conftest.py` connects to `postgresql+asyncpg://heartbeat:heartbeat@localhost:5432/heartbeat_test`; the fixture creates the `heartbeat_test` database itself from the admin `postgres` DB, so the service just needs a `heartbeat` user with that password).

   ```yaml
   name: CI

   on:
     pull_request:
     push:
       branches: [main]
     workflow_call:

   jobs:
     backend:
       name: Backend lint + tests
       runs-on: ubuntu-latest
       services:
         postgres:
           image: postgres:16
           env:
             POSTGRES_USER: heartbeat
             POSTGRES_PASSWORD: heartbeat
             POSTGRES_DB: postgres
           ports:
             - 5432:5432
           options: >-
             --health-cmd="pg_isready -U heartbeat"
             --health-interval=5s
             --health-timeout=5s
             --health-retries=10
       defaults:
         run:
           working-directory: backend
       steps:
         - uses: actions/checkout@v4
         - uses: astral-sh/setup-uv@v3
           with:
             enable-cache: true
         - run: uv sync --frozen
         - run: uv run ruff check
         - run: uv run ruff format --check
         - run: uv run pytest
           env:
             TEST_DATABASE_URL: postgresql+asyncpg://heartbeat:heartbeat@localhost:5432/heartbeat_test

     frontend:
       name: Frontend lint + typecheck + build
       runs-on: ubuntu-latest
       defaults:
         run:
           working-directory: frontend
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-node@v4
           with:
             node-version: lts/*
             cache: npm
             cache-dependency-path: frontend/package-lock.json
         - run: npm ci
         - run: npm run lint
         - run: npx tsc --noEmit
         - run: npm run build
   ```

   Notes: `workflow_call` is what lets `deploy.yml` invoke this. `TEST_DATABASE_URL` is set explicitly even though it matches the default — keeps the dependency between the service container and the test config visible. The frontend `build` step exercises the Next.js static export so a broken export caught at build time fails CI rather than at Fly deploy time.

3. **`.github/workflows/deploy.yml`** — push-to-main deploy, gated on `ci.yml`.

   ```yaml
   name: Deploy to Fly

   on:
     push:
       branches: [main]
     workflow_dispatch:

   concurrency:
     group: fly-deploy
     cancel-in-progress: false

   jobs:
     ci:
       uses: ./.github/workflows/ci.yml

     deploy:
       name: Deploy backend
       needs: ci
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: superfly/flyctl-actions/setup-flyctl@master
         - run: flyctl deploy --remote-only
           env:
             FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
   ```

   `needs: ci` is the gate — if either CI job (backend or frontend) fails, the `deploy` job is skipped. `concurrency` prevents two deploys racing if you push twice quickly; `cancel-in-progress: false` lets an in-flight deploy finish, since canceling a `release_command` mid-migration is bad.

4. **Smoke the workflows.** Open a PR with a no-op change → `ci.yml` should run and finish green. Merge to `main` → `deploy.yml` runs `ci` then `deploy`; `flyctl releases --app heartbeat-monitor-demo` shows a new release.

**Done when**

- Opening a PR triggers `CI` and both jobs finish green.
- Pushing to `main` triggers `Deploy to Fly`, the `ci` job runs both backend and frontend, and `deploy` runs only after they succeed.
- Forcing a CI failure (e.g., a deliberate lint error) on a `main` push causes `deploy` to be skipped, not run.
- `flyctl releases --app heartbeat-monitor-demo` shows the release created by the Actions run.

---

## Phase F — Verification and operability

**Goal:** Confidence the demo is healthy and you know how to inspect it without re-reading this document.

**Tasks**

1. **End-to-end smoke**:
   - Open the dashboard, confirm endpoints, recent-check strip moves.
   - Open `/incidents` — at least one closed incident from the seed should be visible (`payments-webhook` with 8% failure rate normally produces a few over 75 days).
   - On a closed incident, click Generate Postmortem (only if `OPENROUTER_API_KEY` is set). Confirm it returns content; then Edit and Save.
   - Open `/notifications` — confirm the ring buffer has entries from live activity (the seeder doesn't write here per `DESIGN.md` §13, so this populates from post-deploy live runs only).
2. **Storage panel**: `/settings` → Storage. Click `Run rollup now`, confirm next-run timestamp updates.
3. **Logs and metrics**:
   - `flyctl logs --app heartbeat-monitor-demo` for live tail.
   - `flyctl status --app heartbeat-monitor-demo` for machine health.
   - `flyctl machines list --app heartbeat-monitor-demo` to confirm one machine, one region.
4. **Cost check**: `flyctl dashboard` → Billing. After 24 h you should see the per-machine and per-volume line items. If anything is surprising, that's the time to find out.

**Done when**

- All five Phase F tasks pass on a clean clone-and-deploy run-through.
- You can answer "is the demo up?" from a single `flyctl status` per app.

---

## Operational notes

- **DB backups**: not configured in this plan. For a demo it's acceptable to rely on `seed.maybe_seed` re-running against an empty DB (delete the volume and redeploy). If you want real backups, the cheapest approach is a nightly `pg_dump` in a Fly cron machine pushing to S3 / R2 — out of scope here.
- **Resetting the demo**: `flyctl volumes destroy pg_data --app heartbeat-monitor-db` then recreate the volume and redeploy. On next boot, `seed.maybe_seed` re-seeds because the table is empty.
- **Scaling up**: increase `[[vm]] memory` in `fly.toml` and `flyctl deploy`. Do **not** scale to >1 machine without first addressing the open scheduler scale-out work in `DESIGN.md` §15 — two machines today means duplicate checks.
- **Custom domain**: `flyctl certs add demo.yourdomain.com --app heartbeat-monitor-demo`, then point a CNAME at `heartbeat-monitor-demo.fly.dev`. Not required for the demo to work.
