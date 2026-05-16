"""Integration tests for Phase 6: streaks, incidents, and frozen timelines."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from heartbeat.checker import CheckOutcome
from heartbeat.clock import FakeClock
from heartbeat.db import get_session
from heartbeat.dependencies import get_clock
from heartbeat.main import app
from heartbeat.models.check_result import ErrorCategory
from heartbeat.models.endpoint import Endpoint
from heartbeat.models.incident import Incident
from heartbeat.scheduler import Scheduler

_FIXED_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

_BASE_ENDPOINT = {
    "name": "Test API",
    "url": "https://example.com/health",
    "check_interval_seconds": 60,
    "timeout_seconds": 10,
}


class SequenceChecker:
    """Returns a predetermined sequence of outcomes, raising IndexError when exhausted."""

    def __init__(self, outcomes: list[str]) -> None:
        self._outcomes = outcomes
        self._index = 0

    async def check(self, endpoint: Endpoint) -> CheckOutcome:
        if self._index >= len(self._outcomes):
            raise IndexError(f"SequenceChecker exhausted after {len(self._outcomes)} outcomes")
        outcome = self._outcomes[self._index]
        self._index += 1
        return CheckOutcome(
            outcome=outcome,
            latency_ms=100,
            status_code=200 if outcome == "success" else None,
            error_category=None if outcome == "success" else ErrorCategory.other,
            error_message=None if outcome == "success" else "simulated failure",
        )


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(db_engine) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text("DELETE FROM postmortems"))
        await session.execute(text("DELETE FROM incidents"))
        await session.execute(text("DELETE FROM check_results"))
        await session.execute(text("DELETE FROM endpoints"))
        await session.commit()


@pytest_asyncio.fixture
async def session_factory(db_engine) -> async_sessionmaker:
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def fake_clock() -> FakeClock:
    return FakeClock(_FIXED_NOW)


@pytest_asyncio.fixture
async def client(db_engine, fake_clock) -> AsyncGenerator[AsyncClient, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_clock] = lambda: fake_clock
    app.dependency_overrides[get_session] = _test_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_clock, None)
    app.dependency_overrides.pop(get_session, None)


async def _create_endpoint(client: AsyncClient, overrides: dict | None = None) -> dict:
    payload = {**_BASE_ENDPOINT, **(overrides or {})}
    resp = await client.post("/api/v1/endpoints", json=payload)
    assert resp.status_code == 201
    return resp.json()


async def _run_sequence(
    session_factory: async_sessionmaker,
    checker: SequenceChecker,
    fake_clock: FakeClock,
    n_ticks: int,
    tick_interval_seconds: int = 60,
) -> None:
    """Run n_ticks scheduler ticks, advancing the clock between each.

    A fresh Scheduler is created on each call, so in_flight state does not
    carry over. This is intentional: ticks are driven synchronously and the
    endpoint's next_due_at (committed to the DB) is what determines scheduling
    on subsequent calls.
    """
    scheduler = Scheduler(
        session_factory=session_factory,
        checker=checker,
        clock=fake_clock,
        concurrency=10,
    )
    for _ in range(n_ticks):
        tasks = await scheduler.tick()
        await asyncio.gather(*tasks)
        fake_clock.advance(timedelta(seconds=tick_interval_seconds))


async def test_three_failures_open_incident(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    ep = await _create_endpoint(client)
    checker = SequenceChecker(["failure", "failure", "failure"])

    await _run_sequence(session_factory, checker, fake_clock, n_ticks=3)

    async with session_factory() as session:
        incidents = (
            (await session.execute(select(Incident).where(Incident.endpoint_id == ep["id"])))
            .scalars()
            .all()
        )

    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.ended_at is None
    assert incident.duration_seconds is None
    assert incident.frozen_timeline is None
    # started_at = timestamp of the first failure (before N reached)
    assert incident.started_at == _FIXED_NOW


async def test_two_successes_close_incident(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    ep = await _create_endpoint(client)
    checker = SequenceChecker(["failure", "failure", "failure", "success", "success"])

    await _run_sequence(session_factory, checker, fake_clock, n_ticks=5)

    async with session_factory() as session:
        incident = await session.scalar(select(Incident).where(Incident.endpoint_id == ep["id"]))

    assert incident is not None
    assert incident.ended_at is not None
    assert incident.duration_seconds is not None
    assert incident.duration_seconds >= 0
    assert incident.frozen_timeline is not None
    assert len(incident.frozen_timeline) > 0


async def test_frozen_timeline_structure(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    """frozen_timeline entries must have the required keys and correct values."""
    await _create_endpoint(client)
    checker = SequenceChecker(["failure", "failure", "failure", "success", "success"])

    await _run_sequence(session_factory, checker, fake_clock, n_ticks=5)

    async with session_factory() as session:
        incident = await session.scalar(select(Incident))

    assert incident is not None
    timeline = incident.frozen_timeline
    assert timeline is not None

    required_keys = {
        "checked_at",
        "outcome",
        "latency_ms",
        "status_code",
        "error_category",
        "error_message",
    }
    for entry in timeline:
        assert required_keys == set(entry.keys())
        assert entry["outcome"] in ("success", "failure")
        assert isinstance(entry["latency_ms"], int)

    # All 5 checks in the timeline (no preceding success to prepend)
    assert len(timeline) == 5
    assert all(e["outcome"] == "failure" for e in timeline[:3])
    assert all(e["outcome"] == "success" for e in timeline[3:])


async def test_frozen_timeline_includes_preceding_success(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    """When a success precedes the incident, it is included in the frozen_timeline."""
    await _create_endpoint(client)
    # 2 successes, then 3 failures open, then 2 successes close
    checker = SequenceChecker(
        ["success", "success", "failure", "failure", "failure", "success", "success"]
    )

    await _run_sequence(session_factory, checker, fake_clock, n_ticks=7)

    async with session_factory() as session:
        incident = await session.scalar(select(Incident))

    assert incident is not None
    timeline = incident.frozen_timeline
    assert timeline is not None

    # frozen_timeline range: from last success before started_at through current check.
    # = [S(tick1), F(tick2), F(tick3), F(tick4), S(tick5), S(tick6)]  — 6 entries
    # (tick0 = first success; tick1 = second success = the "preceding success")
    assert len(timeline) == 6
    assert timeline[0]["outcome"] == "success"  # preceding success
    assert timeline[1]["outcome"] == "failure"  # first failure (= incident.started_at)
    assert timeline[-1]["outcome"] == "success"  # closing success (current check)


async def test_incident_not_opened_twice(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    """N more failures while an incident is already open do not open a second incident."""
    await _create_endpoint(client)
    checker = SequenceChecker(["failure"] * 6)

    await _run_sequence(session_factory, checker, fake_clock, n_ticks=6)

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Incident))

    assert count == 1


async def test_incident_lifecycle_end_to_end_via_api(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    """Full incident open/close lifecycle visible through the incidents API."""
    ep = await _create_endpoint(client)
    checker = SequenceChecker(["failure", "failure", "failure", "success", "success"])

    # Before any checks: no incidents
    resp = await client.get("/api/v1/incidents")
    assert resp.status_code == 200
    assert resp.json() == []

    # Run 3 failures → incident opens
    await _run_sequence(session_factory, checker, fake_clock, n_ticks=3)
    resp = await client.get(f"/api/v1/incidents?endpoint_id={ep['id']}&state=active")
    assert resp.status_code == 200
    incidents = resp.json()
    assert len(incidents) == 1
    incident_id = incidents[0]["id"]
    assert incidents[0]["ended_at"] is None

    # Run 2 successes → incident closes
    await _run_sequence(session_factory, checker, fake_clock, n_ticks=2)
    resp = await client.get(f"/api/v1/incidents/{incident_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ended_at"] is not None
    assert data["duration_seconds"] is not None
    assert data["frozen_timeline"] is not None
    assert len(data["frozen_timeline"]) == 5

    # Active list is now empty; closed list has the one incident
    resp = await client.get("/api/v1/incidents?state=active")
    assert resp.json() == []
    resp = await client.get("/api/v1/incidents?state=closed")
    assert len(resp.json()) == 1


async def test_incidents_404_for_unknown(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/incidents/99999")
    assert resp.status_code == 404


async def test_endpoint_streak_state_persisted(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    """Endpoint streak state is updated on each check."""
    ep = await _create_endpoint(client)
    checker = SequenceChecker(["failure", "failure"])

    await _run_sequence(session_factory, checker, fake_clock, n_ticks=2)

    async with session_factory() as session:
        endpoint = await session.get(Endpoint, ep["id"])

    assert endpoint is not None
    assert endpoint.current_streak_outcome is not None
    assert endpoint.current_streak_outcome.value == "failure"
    assert endpoint.current_streak_count == 2
    assert endpoint.streak_started_at is not None


async def test_deleting_endpoint_removes_open_incident(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    """Deleting an endpoint CASCADE-deletes its open incident."""
    ep = await _create_endpoint(client)
    checker = SequenceChecker(["failure", "failure", "failure"])

    await _run_sequence(session_factory, checker, fake_clock, n_ticks=3)

    async with session_factory() as session:
        count_before = await session.scalar(select(func.count()).select_from(Incident))
    assert count_before == 1

    resp = await client.delete(f"/api/v1/endpoints/{ep['id']}")
    assert resp.status_code == 204

    async with session_factory() as session:
        count_after = await session.scalar(select(func.count()).select_from(Incident))
    assert count_after == 0
