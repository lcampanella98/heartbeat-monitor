# Heartbeat Monitor — MVP Requirements

Status: Draft. Captures product scope and behavior. Tech design (data model, APIs, scheduler internals, deployment topology) lives in a separate document, to be written next.

## 1. Overview

Heartbeat Monitor is a self-hosted uptime monitor and status page. It polls a set of user-registered HTTP(S) endpoints on a schedule, records the result of every check, and raises incidents when an endpoint fails repeatedly. It displays current state and uptime trends on an internal status page, and provides an AI-generated plain-English postmortem draft for any incident.

The MVP runs locally via Docker on a single user's machine. A "simulated mode" replaces real HTTP checks with synthetic results so the product can be demoed (locally or as a public demo deployment) without depending on real internet endpoints.

## 2. Goals

- Polls user-registered endpoints on independent schedules and persists every check result.
- Detects sustained failures, opens and closes incidents, and notifies the user.
- Surfaces current state and historical uptime on an internal status page.
- Generates an AI postmortem draft for any incident on demand.
- Runs end-to-end in simulated mode for public demo without sending real emails or making real outbound HTTP requests.
- Demonstrates non-trivial backend design (async scheduling, time-tiered storage with aggregation, clean swap points for real vs. simulated subsystems) within a single-instance MVP.

## 3. Non-goals (out of scope for MVP)

- Non-HTTP checks (TCP port, DNS, ICMP).
- HTTP check assertions beyond "any 2xx is success" (no custom status codes, response body matching, request headers, request bodies, or non-GET methods).
- Authentication on monitored endpoints (basic auth, bearer tokens, custom headers).
- Alert channels other than in-app and email (no webhooks, Slack, Discord, PagerDuty, SMS, push).
- Multi-user accounts, login screen, RBAC, sharing, invitations. The database schema supports multiple users for future use; the application always operates as a single, implicit user.
- Publicly shareable status page or per-endpoint public visibility.
- Endpoint tags, groups, dependencies, or maintenance windows.
- Mobile apps, native notifications.
- Multi-instance / HA deployment, horizontal scaling. (A "how we would scale this" section in README.md describes the scale-out path; the MVP does not implement it.)

## 4. Users

The MVP has one implicit user. They are considered logged in by default; there is no login screen, signup, password reset, or session management. All endpoints, settings, history, and incidents in the system belong to that user.

The data model includes a `user_id` foreign key on user-owned entities so a future release can introduce real authentication without a migration.

## 5. Operating modes

The application has two independent runtime switches, each governed by an environment variable:

| Switch | Values | Meaning |
| --- | --- | --- |
| Check source | `real` (default) / `simulated` | `real`: the checker performs actual HTTP requests against each endpoint's URL. `simulated`: the checker generates synthetic check results from each endpoint's simulator configuration; no outbound HTTP is performed. |
| Email sink | `smtp` (default) / `log` | `smtp`: alert emails are delivered through a configured SMTP server. `log`: alert emails are captured in the database and displayed in an in-app "Sent notifications" panel; no outbound mail is sent. |

The two switches are independent so a developer can run real checks with a log sink during local development, and a public demo deployment can run simulated checks with a log sink to avoid both outbound traffic and free-tier SMTP limits.

A visible banner appears in the UI when either switch is in its non-default state, so a visitor to a deployed demo immediately understands what they are looking at.

## 6. Functional requirements

### 6.1 Endpoint management

The user can create, edit, delete, enable, and disable endpoints. An endpoint has the following fields:

- **Name** (required, unique per user).
- **URL** (required, must be `http://` or `https://`).
- **Check interval** (required, chosen from a fixed set: 30 s, 1 min, 5 min, 15 min).
- **Timeout** (required, in seconds; default 10 s; bounded sensibly, e.g. 1–60 s).
- **Enabled** (boolean, default true). A disabled endpoint stops being scheduled but its history is retained.
- **Simulator config** (only relevant in simulated mode, but always editable):
  - Failure rate, 0–100 %.
  - Latency range (min and max milliseconds for synthetic response time).
  - Optional scheduled outage windows (zero or more time-of-day or relative-time windows during which the endpoint always fails).

Deleting an endpoint also deletes its check history, incidents, and any postmortem drafts (hard delete). This is destructive and the UI must confirm.

### 6.2 Check execution

The system runs each enabled endpoint on its configured interval. Each check produces a check result row with at minimum:

- Endpoint reference.
- Timestamp (UTC).
- Outcome: `success` or `failure`.
- Latency in milliseconds.
- HTTP status code (when applicable).
- Error category and message (when applicable: timeout, DNS failure, connection refused, TLS error, non-2xx response, etc.).

In real mode, the result reflects the actual HTTP request. In simulated mode, the result is derived from the endpoint's simulator config and the current time.

A check that takes longer than the endpoint's timeout is recorded as a `failure` with error category `timeout`.

### 6.3 Incidents

An incident represents a sustained failure. The system maintains, per endpoint, a running streak count of consecutive identical outcomes.

- An incident **opens** when the failure streak reaches **N** (default `N = 3`).
- The incident **closes** when the success streak reaches **M** (default `M = 2`).
- `N` and `M` are fixed constants in code, not user-configurable. (Reasons: as a single global setting they have little real product value; per-endpoint tuning is out of scope; and a shared public demo with a mutable global threshold would let one visitor change incident behavior for the next.)

When an incident opens, its `started_at` is the timestamp of the first failure in the streak that opened it (not the Nth). When it closes, its `ended_at` is the timestamp of the first success in the streak that closed it. Duration is `ended_at - started_at`.

The system stores an incident's full check timeline (every check between `started_at` and `ended_at`, inclusive of the immediately preceding success and following success that bracket it) for use by the AI postmortem feature.

#### Persistence

Incidents are persisted **indefinitely** (no automatic deletion in the MVP). When an incident closes, its full check timeline is **frozen** onto the incident record itself — denormalized as a stored snapshot — so the incident remains fully inspectable and the AI postmortem feature remains usable even after the raw check rows it referenced have aged out at 30 days. Postmortem drafts are tied to incidents and share the same indefinite lifetime.

Storage cost is negligible: incidents are infrequent and each carries only a few dozen rows of check data.

### 6.4 Alerting

When an incident opens or closes, the system sends:

- An **in-app notification** (visible in the UI as a banner and in a notifications list). Active incidents are always visible at the top of the dashboard.
- An **email** to the global recipient list, through whichever email sink is configured (`smtp` or `log`).

#### Email configuration

- **SMTP credentials** (host, port, username, password, from-address, TLS toggle) are read from environment variables. They are not editable in the UI.
- **Recipient list** is a single, global list of email addresses, editable in the UI settings page. Every alert goes to every recipient on the list.
- **Sink mode** (`smtp` vs `log`) is read from an environment variable. The UI shows the active mode.

#### "Sent notifications" panel

When the sink is `log`, every email the system would have sent is captured to a database table and shown in a "Sent notifications" panel in the UI, including subject, body, recipients, and timestamp. This panel exists in both modes but is empty in `smtp` mode (real emails are not duplicated to the panel).

The captured-emails table is bounded as a **ring buffer**: it holds at most ~1,000 rows, and the oldest row is deleted on insert once the cap is reached. This keeps the table from growing without bound under long-running simulated demos, with no time-based sweeper needed. The panel itself displays the most recent ~100 entries with infinite scroll / load-more for older rows still within the buffer.

### 6.5 Status page (internal)

The status page is an internal view in the app, not a public URL. It lists every endpoint with:

- **Current state badge**: Up / Down / Unknown (e.g., never checked yet).
- **Recent check strip**: a horizontal sparkline-style strip of the last 60 checks, each rendered as a green or red tick, hover for details.
- **Uptime %** over the last 24 h, 7 d, and 30 d, computed from the appropriate storage tier (raw, hourly rollup, daily rollup).

The status page does not show latency statistics in the MVP.

### 6.6 Storage and aggregation

Check results are stored in three tiers:

| Tier | Granularity | Retention |
| --- | --- | --- |
| Raw checks | One row per check | 30 days |
| Hourly rollups | One row per endpoint per hour | 180 days |
| Daily rollups | One row per endpoint per day | Indefinite |

Each rollup row aggregates, at minimum: total checks, successful checks, failed checks, and the resulting uptime percentage for that bucket. (Latency percentiles are not required for the MVP, since the status page does not surface latency.)

A background **rollup job** runs on a schedule, sweeps recently-completed buckets, and writes/updates rollup rows. Once a bucket has been rolled up and its retention window for raw data has elapsed, the raw rows for that bucket are deleted.

#### Granularity-aware history view

The per-endpoint history view in the UI auto-switches resolution based on the requested time range, e.g.:

- "Last hour" / "Last day" → per-check (raw) bins.
- "Last week" / "Last month" → hourly rollup bins.
- "Last quarter" / longer → daily rollup bins.

Bin tooltips label which tier the data came from (e.g. "Hourly rollup, 60 checks, 98.3% up").

#### Storage panel

The UI exposes a small "Storage" panel in settings showing:

- Raw row count, hourly rollup row count, daily rollup row count.
- Retention thresholds for each tier.
- Last rollup run timestamp; next scheduled rollup run.
- A "Run rollup now" button that triggers the rollup job immediately.

This panel makes the aggregation pipeline directly visible to anyone exploring the demo.

#### Demo pre-seeding

On startup, when **all** of the following are true:

- `Check source = simulated`,
- `Email sink = log`,
- The database has no existing endpoints or history,

the system pre-seeds approximately 60–90 days of synthetic history for a handful of example endpoints. The seeded data is laid out across the storage tiers as it would have been if the system had run continuously (raw for the most recent 30 days, hourly rollups for the period before, daily rollups for the oldest portion). The seeded history includes several past incidents of varying durations so the AI postmortem feature has something realistic to demonstrate on the very first page load.

Pre-seeding does not run when there is already data in the database, even in demo mode.

### 6.7 AI postmortem

Every incident has an associated postmortem draft (it may be empty until generated). On the incident detail page:

- A **"Generate postmortem"** button triggers generation. While running, the UI shows a loading state.
- Generation is **manual only**; the system does not auto-generate on incident open or close.
- Generation **persists** the resulting draft against the incident.
- The draft is **editable** in-place by the user; edits are saved.
- A **"Regenerate"** button overwrites the current draft with a fresh generation. The UI confirms before regenerating an edited draft. The previous text — whether AI-generated or user-edited — is **discarded entirely**, not versioned or kept in history.

#### Inputs to the model

The model is given:

- Endpoint name and URL.
- Incident open and close timestamps and duration.
- The full check timeline during the incident: every check's timestamp, outcome, HTTP status code (if any), latency, and error category/message.

The model is **not** given checks from other endpoints, checks outside the incident window, or any system-wide context. Cross-endpoint correlation is out of scope for the MVP.

#### Output

A plain-English postmortem draft, several paragraphs at most, intended as a starting point for a human to edit — not a final report.

### 6.8 Simulated mode behavior

When `Check source = simulated`, the check executor does not perform any HTTP requests. Instead, for each scheduled check, it consults the endpoint's simulator config and produces a synthetic result:

- With probability `failure_rate`, the check fails (error category drawn from a small set, e.g. timeout, connection refused).
- Otherwise the check succeeds.
- If the current time falls inside one of the endpoint's scheduled outage windows, the check fails regardless of failure rate.
- Latency is drawn from the endpoint's configured min/max range.

Simulated results otherwise flow through the same incident, alert, storage, and rollup paths as real results.

### 6.9 Settings

A single settings page in the UI exposes:

- Email recipient list (add, remove, validate addresses).
- Storage panel (described in 6.6).
- Read-only display of: current check source mode, current email sink mode, SMTP from-address, incident thresholds `N` and `M`.

## 7. Non-functional requirements

- **Scale target**: ~200 endpoints comfortably on a single FastAPI process, using async I/O with bounded concurrency. Real-mode checks must use an async HTTP client and a concurrency semaphore so a slow endpoint cannot starve the rest.
- **Deployment**: Runs locally via Docker Compose. One container for the FastAPI backend (which also serves the static-exported Next.js frontend), one container for the database. Additional containers (e.g. a fake SMTP service) are optional.
- **Database**: Persistent across container restarts (mounted volume).
- **Time**: All timestamps stored as UTC. UI may display in local time.
- **Configuration**: Mode switches, SMTP credentials, and the LLM API key are read from environment variables. Everything else is configured in the UI.
- **No emojis in user-facing copy.**
- **README "How would we scale this?" section**: a short write-up in `README.md` describes the scale-out path (separate scheduler service, queue/broker, stateless worker pool, separate alert worker, deeper storage tiering, push-based UI updates). The MVP does not implement any of it; the section exists to make the design rationale legible.

## 8. Defaults proposed for first build

These can be revised without changing scope:

- Incident thresholds (hardcoded): `N = 3` consecutive failures to open an incident; `M = 2` consecutive successes to close.
- Check interval choices: 30 s, 1 min, 5 min, 15 min.
- Default endpoint timeout: 10 s.
- Retention: raw 30 days, hourly 180 days, daily indefinite.
- LLM provider: OpenRouter, model `openai/gpt-oss-120b`. API key provided via `.env`. For public-demo deployments, set a spend cap on the OpenRouter key (supported natively by OpenRouter) to bound exposure if visitors spam the "Generate postmortem" button.
- Pre-seeded demo: ~5 example endpoints, ~60 days of history, ~3 historical incidents of varying duration and severity.

## 9. Open questions

All initial open questions were resolved during review. New questions may surface during tech design and will be tracked there.

Resolutions:

- Recent-check-strip length: **60 checks** (now in §6.5).
- Changing an endpoint's interval (immediate reset vs. next due time): **whichever is simpler in implementation** — a tech-design call, no product preference.
- Postmortem regeneration of an edited draft: **prior text is discarded entirely**, not versioned (now in §6.7).
- Rate-limiting the "Run rollup now" button: **no**; it will be used rarely and rate-limiting is unnecessary complexity for the MVP.
- Incident persistence: **indefinite, with frozen check timeline at close** (now in §6.3).
- "Sent notifications" panel growth: **ring buffer, ~1,000-row cap** (now in §6.4).
