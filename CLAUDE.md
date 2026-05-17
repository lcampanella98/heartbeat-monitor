# Heartbeat Monitor MVP web app

## Project Overview
Heartbeat Monitor is an uptime monitor and status page. It actively polls registered endpoints, which are added/removed/modified in the frontend. It stores check history and alerts on failures. AI feature: summarize an incident's logs into a plain-English postmortem draft. The stack is Next.JS static export with Python FastAPI backend. 

## Project documents

The authoritative product, design, and implementation references live in `docs/`:

- `docs/REQUIREMENTS.md` — product scope, in/out of scope, behavior.
- `docs/DESIGN.md` — technical decisions (data model, interfaces, scheduler shape, libraries).
- `docs/PLAN.md` — phased implementation order with per-phase tests and acceptance criteria.

## Limitations
For the MVP, there will only be a single user (always logged in by default) but the database will support multiple users for future.

For the MVP, this will run locally (in one or more docker containers)

## Coding standards

1. Keep it simple — no over-engineering, no unnecessary defensive programming, no extra features.
2. No emojis anywhere.
3. When hitting issues, identify root cause before fixing. Prove with evidence, then fix.
4. Latest idiomatic library versions and patterns.
5. Always invoke Python through `uv` — e.g., `uv run pytest`, `uv run python ...`, `uv add ...`, `uv sync`, `uvx <tool>`. Never call `python`, `pip`, `pipx`, or `virtualenv` directly.

