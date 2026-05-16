"""Integration tests for streak/incident transition logic via apply_check_result.

Replaces the former unit simulation (tests/unit/test_incident_service.py).
Divergence between apply_check_result and these expectations is caught directly.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from heartbeat.models.check_result import CheckResult, ErrorCategory
from heartbeat.models.endpoint import Endpoint, StreakOutcome
from heartbeat.models.incident import Incident
from heartbeat.services.incident_service import apply_check_result

_FIXED_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_TICK = timedelta(seconds=60)

S = StreakOutcome.success
F = StreakOutcome.failure


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(db_engine) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text("DELETE FROM postmortems"))
        await session.execute(text("DELETE FROM incidents"))
        await session.execute(text("DELETE FROM check_results"))
        await session.execute(text("DELETE FROM endpoints"))
        await session.commit()


async def _run_sequence(
    factory: async_sessionmaker,
    outcomes: list[StreakOutcome],
) -> tuple[int, int, bool]:
    """Create an endpoint and drive each outcome through apply_check_result.

    One session per outcome, matching the scheduler's commit-per-tick pattern so
    streak state is persisted and re-fetched exactly as in production.

    Returns (incidents_opened, incidents_closed, has_open_incident_at_end).
    """
    async with factory() as session:
        endpoint = Endpoint(
            user_id=1,
            name="test",
            url="https://example.com/health",
            check_interval_seconds=60,
            timeout_seconds=10,
        )
        session.add(endpoint)
        await session.commit()
        await session.refresh(endpoint)
        endpoint_id = endpoint.id

    now = _FIXED_NOW
    for outcome in outcomes:
        async with factory() as session:
            endpoint = await session.get(Endpoint, endpoint_id)
            check_result = CheckResult(
                endpoint_id=endpoint_id,
                checked_at=now,
                outcome=outcome,
                latency_ms=100,
                status_code=200 if outcome == S else None,
                error_category=None if outcome == S else ErrorCategory.other,
                error_message=None if outcome == S else "simulated failure",
            )
            session.add(check_result)
            await apply_check_result(session, endpoint, check_result)
            await session.commit()
        now += _TICK

    async with factory() as session:
        incidents = (
            (await session.execute(select(Incident).where(Incident.endpoint_id == endpoint_id)))
            .scalars()
            .all()
        )

    opened = len(incidents)
    closed = sum(1 for i in incidents if i.ended_at is not None)
    has_open = any(i.ended_at is None for i in incidents)
    return opened, closed, has_open


@pytest.mark.parametrize(
    "outcomes, exp_opened, exp_closed, exp_open",
    [
        # Basic: 3 failures open, 2 successes close
        ([S, S, F, F, F, S, S], 1, 1, False),
        # Failures from the start (no preceding success)
        ([F, F, F, F, S, S], 1, 1, False),
        # Success resets partial failure streak, then a full failure streak opens
        ([F, F, S, F, F, F, S, S], 1, 1, False),
        # Incident already open: N more failures do not open a second incident
        ([F, F, F, F, F, S, S], 1, 1, False),
        # Not enough failures to open
        ([F, F, S], 0, 0, False),
        # Single success inside an open incident does not close it (need M=2)
        ([F, F, F, S, F, F, F], 1, 0, True),
        # Open, close, then open again
        ([F, F, F, S, S, F, F, F], 2, 1, True),
        # Success resets partial failure streak; F,F,S,F,F never reaches N
        ([F, F, S, F, F], 0, 0, False),
        # Exact N failures, exact M successes — boundary
        ([F, F, F, S, S], 1, 1, False),
        # No incidents at all
        ([S, S, S], 0, 0, False),
        # Stays open after partial success then more failures
        ([F, F, F, S, F, F], 1, 0, True),
    ],
)
async def test_apply_check_result_sequence(
    db_engine,
    outcomes: list[StreakOutcome],
    exp_opened: int,
    exp_closed: int,
    exp_open: bool,
) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    opened, closed, has_open = await _run_sequence(factory, outcomes)
    assert opened == exp_opened
    assert closed == exp_closed
    assert has_open == exp_open
