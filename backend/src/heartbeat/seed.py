import logging
import random
from datetime import datetime, timedelta

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from heartbeat.checker.simulated import SimulatedChecker
from heartbeat.clock import Clock, FakeClock
from heartbeat.config import settings
from heartbeat.models.check_result import CheckResult
from heartbeat.models.endpoint import Endpoint, StreakOutcome
from heartbeat.models.incident import Incident
from heartbeat.rollup import RollupJob
from heartbeat.services.incident_service import StreakState, streak_step

logger = logging.getLogger(__name__)

_SEED_ENDPOINTS = [
    {
        "name": "api-prod",
        "url": "https://api.example.com/health",
        "check_interval_seconds": 60,
        "timeout_seconds": 10,
        "sim_failure_rate": 0.005,
        "sim_latency_min_ms": 80,
        "sim_latency_max_ms": 200,
        "sim_outage_windows": [],
    },
    {
        "name": "marketing-site",
        "url": "https://example.com",
        "check_interval_seconds": 300,
        "timeout_seconds": 10,
        "sim_failure_rate": 0.005,
        "sim_latency_min_ms": 80,
        "sim_latency_max_ms": 200,
        "sim_outage_windows": [],
    },
    {
        "name": "metrics-collector",
        "url": "https://metrics.example.com/health",
        "check_interval_seconds": 30,
        "timeout_seconds": 10,
        "sim_failure_rate": 0.03,
        "sim_latency_min_ms": 100,
        "sim_latency_max_ms": 400,
        "sim_outage_windows": [],
    },
    {
        "name": "payments-webhook",
        "url": "https://payments.example.com/webhook/health",
        "check_interval_seconds": 60,
        "timeout_seconds": 10,
        "sim_failure_rate": 0.08,
        "sim_latency_min_ms": 150,
        "sim_latency_max_ms": 600,
        "sim_outage_windows": [],
    },
    {
        "name": "nightly-batch",
        "url": "https://batch.example.com/status",
        "check_interval_seconds": 900,
        "timeout_seconds": 10,
        "sim_failure_rate": 0.01,
        "sim_latency_min_ms": 80,
        "sim_latency_max_ms": 200,
        "sim_outage_windows": [{"start": "03:00", "end": "03:15"}],
    },
]

_BATCH_SIZE = 5000


async def maybe_seed(
    session_factory: async_sessionmaker,
    clock: Clock,
    days: int = 75,
    rng_seed: int = 0,
) -> None:
    if settings.check_source != "simulated" or settings.email_sink != "log":
        return

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Endpoint))
    if count > 0:
        return

    logger.info("Seeding demo data (%d days)...", days)

    now = clock.now()
    start_t = now - timedelta(days=days)
    rng = random.Random(rng_seed)

    # Insert seed endpoints
    async with session_factory() as session:
        for ep_data in _SEED_ENDPOINTS:
            session.add(Endpoint(user_id=1, next_due_at=now, **ep_data))
        await session.commit()

    # Re-fetch with IDs
    async with session_factory() as session:
        endpoints = (await session.execute(select(Endpoint))).scalars().all()

    # Simulate history in memory
    fake_clock = FakeClock(initial=start_t)
    checker = SimulatedChecker(clock=fake_clock, rng=rng)

    all_check_rows: list[dict] = []
    all_incidents: list[Incident] = []

    for endpoint in endpoints:
        state = StreakState(outcome=None, count=0, started_at=None)
        open_incident: dict | None = None
        buffer: list[dict] = []

        t = start_t
        while t <= now:
            fake_clock.set(t)
            outcome = await checker.check(endpoint)

            row = {
                "endpoint_id": endpoint.id,
                "checked_at": t,
                "outcome": StreakOutcome(outcome.outcome),
                "latency_ms": outcome.latency_ms,
                "status_code": outcome.status_code,
                "error_category": outcome.error_category,
                "error_message": outcome.error_message,
            }
            all_check_rows.append(row)
            buffer.append(row)

            decision = streak_step(state, StreakOutcome(outcome.outcome), t)
            state = decision.next_state

            if decision.open_at is not None and open_incident is None:
                open_incident = {
                    "endpoint_id": endpoint.id,
                    "started_at": decision.open_at,
                }

            if decision.close_at is not None and open_incident is not None:
                ended_at = decision.close_at
                duration = int((ended_at - open_incident["started_at"]).total_seconds())
                frozen = _build_frozen_timeline(buffer, open_incident["started_at"], t)
                all_incidents.append(
                    Incident(
                        endpoint_id=open_incident["endpoint_id"],
                        started_at=open_incident["started_at"],
                        ended_at=ended_at,
                        duration_seconds=duration,
                        frozen_timeline=frozen,
                    )
                )
                open_incident = None

            t += timedelta(seconds=endpoint.check_interval_seconds)

    # Bulk persist check results in batches then incidents
    async with session_factory() as session:
        for i in range(0, len(all_check_rows), _BATCH_SIZE):
            await session.execute(insert(CheckResult), all_check_rows[i : i + _BATCH_SIZE])
        for incident in all_incidents:
            session.add(incident)
        await session.commit()

    # Backfill rollups and apply retention
    rollup_job = RollupJob(session_factory=session_factory, clock=clock)
    await rollup_job.run_once(full=True)

    logger.info(
        "Seed complete: %d check rows, %d closed incidents",
        len(all_check_rows),
        len(all_incidents),
    )


def _build_frozen_timeline(
    buffer: list[dict],
    started_at: datetime,
    current_checked_at: datetime,
) -> list[dict]:
    preceding_checked_at: datetime | None = None
    for row in reversed(buffer):
        if row["checked_at"] < started_at and row["outcome"] == StreakOutcome.success:
            preceding_checked_at = row["checked_at"]
            break

    range_start = preceding_checked_at if preceding_checked_at is not None else started_at

    return [
        {
            "checked_at": r["checked_at"].isoformat(),
            "outcome": r["outcome"].value,
            "latency_ms": r["latency_ms"],
            "status_code": r["status_code"],
            "error_category": r["error_category"].value if r["error_category"] else None,
            "error_message": r["error_message"],
        }
        for r in buffer
        if range_start <= r["checked_at"] <= current_checked_at
    ]
