import asyncio
import random
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from heartbeat.checker import CheckOutcome
from heartbeat.checker.simulated import SimulatedChecker
from heartbeat.clock import FakeClock
from heartbeat.db import get_session
from heartbeat.dependencies import get_clock
from heartbeat.main import app
from heartbeat.models.check_result import CheckResult
from heartbeat.models.endpoint import Endpoint, StreakOutcome
from heartbeat.scheduler import Scheduler

_FIXED_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

_BASE_ENDPOINT = {
    "name": "Test API",
    "url": "https://example.com/health",
    "check_interval_seconds": 60,
    "timeout_seconds": 10,
}


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(db_engine) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
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


async def test_tick_inserts_check_results_for_due_endpoints(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    # Create 3 endpoints with fixed clock so all have next_due_at == _FIXED_NOW
    ep1 = await _create_endpoint(client, {"name": "EP1"})
    ep2 = await _create_endpoint(client, {"name": "EP2"})
    ep3 = await _create_endpoint(client, {"name": "EP3"})

    checker = SimulatedChecker(clock=fake_clock, rng=random.Random(42))
    scheduler = Scheduler(
        session_factory=session_factory,
        checker=checker,
        clock=fake_clock,
        concurrency=10,
    )

    tasks = await scheduler.tick()
    assert len(tasks) == 3
    await asyncio.gather(*tasks)

    endpoint_ids = {ep1["id"], ep2["id"], ep3["id"]}
    async with session_factory() as session:
        rows = (await session.execute(select(CheckResult))).scalars().all()
    assert len(rows) == 3
    assert {r.endpoint_id for r in rows} == endpoint_ids
    for row in rows:
        assert row.outcome in (StreakOutcome.success, StreakOutcome.failure)
        assert row.latency_ms >= 0
        assert row.checked_at == _FIXED_NOW


async def test_tick_advances_next_due_at(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    ep = await _create_endpoint(client)
    interval = ep["check_interval_seconds"]

    checker = SimulatedChecker(clock=fake_clock, rng=random.Random(0))
    scheduler = Scheduler(
        session_factory=session_factory,
        checker=checker,
        clock=fake_clock,
        concurrency=10,
    )

    tasks = await scheduler.tick()
    await asyncio.gather(*tasks)

    async with session_factory() as session:
        endpoint = await session.get(Endpoint, ep["id"])
    assert endpoint is not None
    assert endpoint.next_due_at == _FIXED_NOW + timedelta(seconds=interval)


async def test_tick_skips_inflight_endpoints(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    ep = await _create_endpoint(client)

    # Stub checker that blocks until an event is set
    event = asyncio.Event()

    class BlockingChecker:
        async def check(self, endpoint: Endpoint) -> CheckOutcome:
            await event.wait()
            return CheckOutcome(
                outcome="success",
                latency_ms=50,
                status_code=200,
                error_category=None,
                error_message=None,
            )

    scheduler = Scheduler(
        session_factory=session_factory,
        checker=BlockingChecker(),
        clock=fake_clock,
        concurrency=10,
    )

    # First tick: spawns a task, endpoint goes into in_flight
    tasks1 = await scheduler.tick()
    assert len(tasks1) == 1
    assert ep["id"] in scheduler.in_flight

    # Second tick: endpoint is still in_flight, nothing spawned
    tasks2 = await scheduler.tick()
    assert len(tasks2) == 0

    # Unblock and let the first check complete
    event.set()
    await asyncio.gather(*tasks1)

    # Endpoint is removed from in_flight after completion
    assert ep["id"] not in scheduler.in_flight

    # Only one check_result row was inserted
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(CheckResult))
    assert count == 1


async def test_tick_skips_disabled_endpoints(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    ep = await _create_endpoint(client)
    await client.post(f"/api/v1/endpoints/{ep['id']}/disable")

    checker = SimulatedChecker(clock=fake_clock, rng=random.Random(0))
    scheduler = Scheduler(
        session_factory=session_factory,
        checker=checker,
        clock=fake_clock,
        concurrency=10,
    )

    tasks = await scheduler.tick()
    assert len(tasks) == 0

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(CheckResult))
    assert count == 0


async def test_recent_checks_route(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    ep = await _create_endpoint(client)

    checker = SimulatedChecker(clock=fake_clock, rng=random.Random(1))
    scheduler = Scheduler(
        session_factory=session_factory,
        checker=checker,
        clock=fake_clock,
        concurrency=10,
    )

    tasks = await scheduler.tick()
    await asyncio.gather(*tasks)

    resp = await client.get(f"/api/v1/endpoints/{ep['id']}/recent-checks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["endpoint_id"] == ep["id"]
    assert data[0]["outcome"] in ("success", "failure")
    assert data[0]["latency_ms"] >= 0


async def test_recent_checks_limit(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    ep = await _create_endpoint(client)

    checker = SimulatedChecker(clock=fake_clock, rng=random.Random(2))
    scheduler = Scheduler(
        session_factory=session_factory,
        checker=checker,
        clock=fake_clock,
        concurrency=10,
    )

    # Run 5 ticks, advancing clock so each gets a fresh next_due_at
    for _ in range(5):
        tasks = await scheduler.tick()
        await asyncio.gather(*tasks)
        fake_clock.advance(timedelta(seconds=60))

    resp = await client.get(f"/api/v1/endpoints/{ep['id']}/recent-checks?limit=3")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


async def test_recent_checks_nonexistent_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/endpoints/99999/recent-checks")
    assert resp.status_code == 404
