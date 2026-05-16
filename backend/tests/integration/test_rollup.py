"""Integration tests for Phase 8: rollup job, history, uptime, and storage API."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from heartbeat.clock import FakeClock
from heartbeat.db import get_session
from heartbeat.dependencies import get_clock, get_rollup_job
from heartbeat.main import app
from heartbeat.models.check_result import CheckResult
from heartbeat.models.daily_rollup import DailyRollup
from heartbeat.models.endpoint import Endpoint, StreakOutcome
from heartbeat.models.hourly_rollup import HourlyRollup
from heartbeat.rollup import RAW_RETENTION_DAYS, RollupJob

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)  # noon on 2025-06-01


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(db_engine) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text("DELETE FROM daily_rollups"))
        await session.execute(text("DELETE FROM hourly_rollups"))
        await session.execute(text("DELETE FROM check_results"))
        await session.execute(text("DELETE FROM endpoints"))
        await session.commit()


@pytest_asyncio.fixture
async def session_factory(db_engine) -> async_sessionmaker:
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def fake_clock() -> FakeClock:
    return FakeClock(_NOW)


@pytest_asyncio.fixture
async def client(db_engine, fake_clock, session_factory) -> AsyncGenerator[AsyncClient, None]:
    async def _test_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    rollup_job = RollupJob(session_factory=session_factory, clock=fake_clock)

    app.dependency_overrides[get_clock] = lambda: fake_clock
    app.dependency_overrides[get_session] = _test_session
    app.dependency_overrides[get_rollup_job] = lambda: rollup_job

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_clock, None)
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_rollup_job, None)


async def _make_endpoint(session_factory: async_sessionmaker, name: str = "ep1") -> int:
    async with session_factory() as session:
        ep = Endpoint(
            user_id=1,
            name=name,
            url="https://example.com",
            check_interval_seconds=60,
            timeout_seconds=10,
        )
        session.add(ep)
        await session.commit()
        return ep.id


async def _insert_checks(
    session_factory: async_sessionmaker,
    endpoint_id: int,
    checks: list[tuple[datetime, str]],
) -> None:
    """Insert check results with given (timestamp, outcome) pairs."""
    async with session_factory() as session:
        for checked_at, outcome in checks:
            session.add(
                CheckResult(
                    endpoint_id=endpoint_id,
                    checked_at=checked_at,
                    outcome=StreakOutcome(outcome),
                    latency_ms=100,
                    status_code=200 if outcome == "success" else None,
                )
            )
        await session.commit()


# ---------------------------------------------------------------------------
# Hourly rollup
# ---------------------------------------------------------------------------


async def test_hourly_rollup_aggregates_correctly(
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    ep_id = await _make_endpoint(session_factory)
    hour0 = _NOW.replace(minute=0, second=0, microsecond=0)  # 2025-06-01 12:00
    hour1 = hour0 - timedelta(hours=1)  # 2025-06-01 11:00

    await _insert_checks(
        session_factory,
        ep_id,
        [
            (hour0 + timedelta(minutes=1), "success"),
            (hour0 + timedelta(minutes=2), "success"),
            (hour0 + timedelta(minutes=3), "failure"),
            (hour1 + timedelta(minutes=10), "success"),
            (hour1 + timedelta(minutes=20), "success"),
            (hour1 + timedelta(minutes=30), "success"),
        ],
    )

    job = RollupJob(session_factory=session_factory, clock=fake_clock)
    await job.run_once()

    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(HourlyRollup)
                    .where(HourlyRollup.endpoint_id == ep_id)
                    .order_by(HourlyRollup.bucket_start)
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 2

    h1 = rows[0]  # hour1 (11:00)
    assert h1.total_checks == 3
    assert h1.successful_checks == 3
    assert h1.failed_checks == 0
    assert float(h1.uptime_pct) == 100.0

    h0 = rows[1]  # hour0 (12:00)
    assert h0.total_checks == 3
    assert h0.successful_checks == 2
    assert h0.failed_checks == 1
    assert float(h0.uptime_pct) == pytest.approx(66.67, abs=0.01)


# ---------------------------------------------------------------------------
# Multi-endpoint rollup — no cross-contamination
# ---------------------------------------------------------------------------


async def test_rollup_partitioned_by_endpoint(
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    """Two endpoints with different uptime rates produce independent rollup rows."""
    ep_a = await _make_endpoint(session_factory, name="ep-a")
    ep_b = await _make_endpoint(session_factory, name="ep-b")

    hour0 = _NOW.replace(minute=0, second=0, microsecond=0)

    # Endpoint A: 4 successes, 0 failures → 100% uptime
    await _insert_checks(
        session_factory,
        ep_a,
        [(hour0 + timedelta(minutes=i), "success") for i in range(4)],
    )
    # Endpoint B: 2 successes, 2 failures → 50% uptime
    await _insert_checks(
        session_factory,
        ep_b,
        [
            (hour0 + timedelta(minutes=0), "success"),
            (hour0 + timedelta(minutes=1), "success"),
            (hour0 + timedelta(minutes=2), "failure"),
            (hour0 + timedelta(minutes=3), "failure"),
        ],
    )

    job = RollupJob(session_factory=session_factory, clock=fake_clock)
    await job.run_once()

    async with session_factory() as session:
        rows_a = (
            (await session.execute(select(HourlyRollup).where(HourlyRollup.endpoint_id == ep_a)))
            .scalars()
            .all()
        )
        rows_b = (
            (await session.execute(select(HourlyRollup).where(HourlyRollup.endpoint_id == ep_b)))
            .scalars()
            .all()
        )

    assert len(rows_a) == 1
    assert rows_a[0].total_checks == 4
    assert rows_a[0].successful_checks == 4
    assert rows_a[0].failed_checks == 0
    assert float(rows_a[0].uptime_pct) == 100.0

    assert len(rows_b) == 1
    assert rows_b[0].total_checks == 4
    assert rows_b[0].successful_checks == 2
    assert rows_b[0].failed_checks == 2
    assert float(rows_b[0].uptime_pct) == 50.0

    # Daily rollup must also be partitioned correctly
    async with session_factory() as session:
        daily_a = (
            (await session.execute(select(DailyRollup).where(DailyRollup.endpoint_id == ep_a)))
            .scalars()
            .all()
        )
        daily_b = (
            (await session.execute(select(DailyRollup).where(DailyRollup.endpoint_id == ep_b)))
            .scalars()
            .all()
        )

    assert len(daily_a) == 1
    assert daily_a[0].total_checks == 4
    assert daily_a[0].successful_checks == 4

    assert len(daily_b) == 1
    assert daily_b[0].total_checks == 4
    assert daily_b[0].successful_checks == 2


# ---------------------------------------------------------------------------
# Daily rollup derived from hourly
# ---------------------------------------------------------------------------


async def test_daily_rollup_aggregates_from_hourly(
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    ep_id = await _make_endpoint(session_factory)

    today = _NOW.date()  # 2025-06-01
    yesterday = today - timedelta(days=1)  # 2025-05-31

    # Insert hourly rollup rows directly (simulating a prior hourly run)
    async with session_factory() as session:
        session.add(
            HourlyRollup(
                endpoint_id=ep_id,
                bucket_start=datetime(2025, 6, 1, 10, 0, tzinfo=UTC),
                total_checks=60,
                successful_checks=60,
                failed_checks=0,
                uptime_pct=100,
            )
        )
        session.add(
            HourlyRollup(
                endpoint_id=ep_id,
                bucket_start=datetime(2025, 6, 1, 11, 0, tzinfo=UTC),
                total_checks=60,
                successful_checks=54,
                failed_checks=6,
                uptime_pct=90,
            )
        )
        session.add(
            HourlyRollup(
                endpoint_id=ep_id,
                bucket_start=datetime(2025, 5, 31, 12, 0, tzinfo=UTC),
                total_checks=60,
                successful_checks=30,
                failed_checks=30,
                uptime_pct=50,
            )
        )
        await session.commit()

    job = RollupJob(session_factory=session_factory, clock=fake_clock)
    await job.run_once()

    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(DailyRollup)
                    .where(DailyRollup.endpoint_id == ep_id)
                    .order_by(DailyRollup.bucket_date)
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 2

    d_yesterday = rows[0]
    assert d_yesterday.bucket_date == yesterday
    assert d_yesterday.total_checks == 60
    assert d_yesterday.successful_checks == 30
    assert float(d_yesterday.uptime_pct) == 50.0

    d_today = rows[1]
    assert d_today.bucket_date == today
    assert d_today.total_checks == 120
    assert d_today.successful_checks == 114
    assert float(d_today.uptime_pct) == pytest.approx(95.0, abs=0.01)


# ---------------------------------------------------------------------------
# Retention deletion
# ---------------------------------------------------------------------------


async def test_raw_retention_deletes_old_rows(
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    ep_id = await _make_endpoint(session_factory)

    # Old row (35 days ago — beyond 30-day retention)
    old_ts = _NOW - timedelta(days=35)
    # Recent row (1 hour ago)
    recent_ts = _NOW - timedelta(hours=1)

    await _insert_checks(
        session_factory,
        ep_id,
        [(old_ts, "success"), (recent_ts, "success")],
    )

    async with session_factory() as session:
        count_before = await session.scalar(
            select(func.count()).select_from(CheckResult).where(CheckResult.endpoint_id == ep_id)
        )
    assert count_before == 2

    job = RollupJob(session_factory=session_factory, clock=fake_clock)
    await job.run_once()

    async with session_factory() as session:
        remaining = list(
            (await session.execute(select(CheckResult).where(CheckResult.endpoint_id == ep_id)))
            .scalars()
            .all()
        )

    assert len(remaining) == 1
    assert remaining[0].checked_at == recent_ts


async def test_hourly_retention_deletes_old_rows(
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    ep_id = await _make_endpoint(session_factory)

    async with session_factory() as session:
        # Old hourly row (200 days ago — beyond 180-day retention)
        session.add(
            HourlyRollup(
                endpoint_id=ep_id,
                bucket_start=_NOW - timedelta(days=200),
                total_checks=60,
                successful_checks=60,
                failed_checks=0,
                uptime_pct=100,
            )
        )
        # Recent hourly row
        session.add(
            HourlyRollup(
                endpoint_id=ep_id,
                bucket_start=_NOW - timedelta(hours=1),
                total_checks=60,
                successful_checks=60,
                failed_checks=0,
                uptime_pct=100,
            )
        )
        await session.commit()

    job = RollupJob(session_factory=session_factory, clock=fake_clock)
    await job.run_once()

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(HourlyRollup).where(HourlyRollup.endpoint_id == ep_id)
        )
    assert count == 1


# ---------------------------------------------------------------------------
# Rollup is idempotent
# ---------------------------------------------------------------------------


async def test_rollup_is_idempotent(
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    ep_id = await _make_endpoint(session_factory)
    hour0 = _NOW.replace(minute=0, second=0, microsecond=0)
    await _insert_checks(
        session_factory,
        ep_id,
        [(hour0 + timedelta(minutes=i), "success") for i in range(5)],
    )

    job = RollupJob(session_factory=session_factory, clock=fake_clock)
    await job.run_once()
    await job.run_once()  # second run must not double-count

    async with session_factory() as session:
        hourly_row = (
            await session.execute(select(HourlyRollup).where(HourlyRollup.endpoint_id == ep_id))
        ).scalar_one()

    assert hourly_row.total_checks == 5
    assert hourly_row.successful_checks == 5

    # Daily rollup should also be idempotent — if any row exists it must have total_checks == 5
    async with session_factory() as session:
        daily_rows = (
            (await session.execute(select(DailyRollup).where(DailyRollup.endpoint_id == ep_id)))
            .scalars()
            .all()
        )

    for daily_row in daily_rows:
        assert daily_row.total_checks == 5


# ---------------------------------------------------------------------------
# /history route — source tier routing
# ---------------------------------------------------------------------------


async def test_history_raw_source(client: AsyncClient, session_factory: async_sessionmaker) -> None:
    resp = await client.post(
        "/api/v1/endpoints",
        json={
            "name": "hist-test",
            "url": "https://example.com",
            "check_interval_seconds": 60,
            "timeout_seconds": 10,
        },
    )
    assert resp.status_code == 201
    ep_id = resp.json()["id"]

    # Insert a check 30 minutes ago
    await _insert_checks(
        session_factory,
        ep_id,
        [(_NOW - timedelta(minutes=30), "success")],
    )

    resp = await client.get(f"/api/v1/endpoints/{ep_id}/history?range=1h")
    assert resp.status_code == 200
    bins = resp.json()
    assert len(bins) == 1
    assert bins[0]["source"] == "raw"
    assert bins[0]["total_checks"] == 1
    assert bins[0]["successful_checks"] == 1


async def test_history_hourly_source(
    client: AsyncClient, session_factory: async_sessionmaker
) -> None:
    resp = await client.post(
        "/api/v1/endpoints",
        json={
            "name": "hist-hourly",
            "url": "https://example.com",
            "check_interval_seconds": 60,
            "timeout_seconds": 10,
        },
    )
    assert resp.status_code == 201
    ep_id = resp.json()["id"]

    async with session_factory() as session:
        session.add(
            HourlyRollup(
                endpoint_id=ep_id,
                bucket_start=_NOW - timedelta(days=3),
                total_checks=60,
                successful_checks=60,
                failed_checks=0,
                uptime_pct=100,
            )
        )
        await session.commit()

    resp = await client.get(f"/api/v1/endpoints/{ep_id}/history?range=7d")
    assert resp.status_code == 200
    bins = resp.json()
    assert len(bins) == 1
    assert bins[0]["source"] == "hourly"
    assert bins[0]["total_checks"] == 60


async def test_history_daily_source(
    client: AsyncClient, session_factory: async_sessionmaker
) -> None:
    resp = await client.post(
        "/api/v1/endpoints",
        json={
            "name": "hist-daily",
            "url": "https://example.com",
            "check_interval_seconds": 60,
            "timeout_seconds": 10,
        },
    )
    assert resp.status_code == 201
    ep_id = resp.json()["id"]

    async with session_factory() as session:
        session.add(
            DailyRollup(
                endpoint_id=ep_id,
                bucket_date=(_NOW - timedelta(days=60)).date(),
                total_checks=1440,
                successful_checks=1420,
                failed_checks=20,
                uptime_pct=98.61,
            )
        )
        await session.commit()

    resp = await client.get(f"/api/v1/endpoints/{ep_id}/history?range=90d")
    assert resp.status_code == 200
    bins = resp.json()
    assert len(bins) == 1
    assert bins[0]["source"] == "daily"
    assert bins[0]["total_checks"] == 1440


async def test_history_1d_raw_source(
    client: AsyncClient, session_factory: async_sessionmaker
) -> None:
    resp = await client.post(
        "/api/v1/endpoints",
        json={
            "name": "hist-1d",
            "url": "https://example.com",
            "check_interval_seconds": 60,
            "timeout_seconds": 10,
        },
    )
    assert resp.status_code == 201
    ep_id = resp.json()["id"]

    # Insert a check 6 hours ago — within the 1d window
    await _insert_checks(
        session_factory,
        ep_id,
        [(_NOW - timedelta(hours=6), "success")],
    )

    resp = await client.get(f"/api/v1/endpoints/{ep_id}/history?range=1d")
    assert resp.status_code == 200
    bins = resp.json()
    assert len(bins) == 1
    assert bins[0]["source"] == "raw"


async def test_history_30d_daily_source(
    client: AsyncClient, session_factory: async_sessionmaker
) -> None:
    resp = await client.post(
        "/api/v1/endpoints",
        json={
            "name": "hist-30d",
            "url": "https://example.com",
            "check_interval_seconds": 60,
            "timeout_seconds": 10,
        },
    )
    assert resp.status_code == 201
    ep_id = resp.json()["id"]

    async with session_factory() as session:
        session.add(
            DailyRollup(
                endpoint_id=ep_id,
                bucket_date=(_NOW - timedelta(days=15)).date(),
                total_checks=1440,
                successful_checks=1440,
                failed_checks=0,
                uptime_pct=100,
            )
        )
        await session.commit()

    resp = await client.get(f"/api/v1/endpoints/{ep_id}/history?range=30d")
    assert resp.status_code == 200
    bins = resp.json()
    assert len(bins) == 1
    assert bins[0]["source"] == "daily"


async def test_history_1y_daily_source(
    client: AsyncClient, session_factory: async_sessionmaker
) -> None:
    resp = await client.post(
        "/api/v1/endpoints",
        json={
            "name": "hist-1y",
            "url": "https://example.com",
            "check_interval_seconds": 60,
            "timeout_seconds": 10,
        },
    )
    assert resp.status_code == 201
    ep_id = resp.json()["id"]

    async with session_factory() as session:
        session.add(
            DailyRollup(
                endpoint_id=ep_id,
                bucket_date=(_NOW - timedelta(days=180)).date(),
                total_checks=1440,
                successful_checks=1200,
                failed_checks=240,
                uptime_pct=83.33,
            )
        )
        await session.commit()

    resp = await client.get(f"/api/v1/endpoints/{ep_id}/history?range=1y")
    assert resp.status_code == 200
    bins = resp.json()
    assert len(bins) == 1
    assert bins[0]["source"] == "daily"


async def test_history_unknown_endpoint_is_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/endpoints/99999/history?range=1h")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /uptime route
# ---------------------------------------------------------------------------


async def test_uptime_unknown_endpoint_is_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/endpoints/99999/uptime")
    assert resp.status_code == 404


async def test_uptime_returns_zeros_when_no_data(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/endpoints",
        json={
            "name": "uptime-empty",
            "url": "https://example.com",
            "check_interval_seconds": 60,
            "timeout_seconds": 10,
        },
    )
    assert resp.status_code == 201
    ep_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/endpoints/{ep_id}/uptime")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"h24": 0.0, "d7": 0.0, "d30": 0.0}


async def test_uptime_computed_from_tiers(
    client: AsyncClient, session_factory: async_sessionmaker
) -> None:
    resp = await client.post(
        "/api/v1/endpoints",
        json={
            "name": "uptime-test",
            "url": "https://example.com",
            "check_interval_seconds": 60,
            "timeout_seconds": 10,
        },
    )
    assert resp.status_code == 201
    ep_id = resp.json()["id"]

    # Raw: 2 success, 1 failure in last 24h
    await _insert_checks(
        session_factory,
        ep_id,
        [
            (_NOW - timedelta(hours=1), "success"),
            (_NOW - timedelta(hours=2), "success"),
            (_NOW - timedelta(hours=3), "failure"),
        ],
    )

    resp = await client.get(f"/api/v1/endpoints/{ep_id}/uptime")
    assert resp.status_code == 200
    data = resp.json()
    assert data["h24"] == pytest.approx(66.67, abs=0.01)
    assert data["d7"] == 0.0  # no hourly rollups
    assert data["d30"] == 0.0  # no daily rollups


# ---------------------------------------------------------------------------
# /storage/stats and POST /storage/rollup-now
# ---------------------------------------------------------------------------


async def test_storage_stats_returns_counts(
    client: AsyncClient, session_factory: async_sessionmaker
) -> None:
    ep_id = await _make_endpoint(session_factory)
    await _insert_checks(session_factory, ep_id, [(_NOW - timedelta(hours=1), "success")])

    resp = await client.get("/api/v1/storage/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["raw_count"] == 1
    assert data["hourly_count"] == 0
    assert data["daily_count"] == 0
    assert data["raw_retention_days"] == RAW_RETENTION_DAYS
    assert data["last_rollup_at"] is None


async def test_rollup_now_updates_counts(
    client: AsyncClient, session_factory: async_sessionmaker
) -> None:
    ep_id = await _make_endpoint(session_factory)
    await _insert_checks(
        session_factory,
        ep_id,
        [(_NOW - timedelta(minutes=30), "success"), (_NOW - timedelta(minutes=20), "failure")],
    )

    resp = await client.post("/api/v1/storage/rollup-now")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hourly_count"] == 1
    assert data["raw_count"] == 2  # within retention
    assert data["last_rollup_at"] is not None
    assert data["next_rollup_at"] is not None


async def test_rollup_now_after_retention_removes_raw(
    client: AsyncClient, session_factory: async_sessionmaker
) -> None:
    ep_id = await _make_endpoint(session_factory)
    # One old check (beyond retention), one recent check
    await _insert_checks(
        session_factory,
        ep_id,
        [
            (_NOW - timedelta(days=35), "success"),
            (_NOW - timedelta(hours=1), "success"),
        ],
    )

    resp = await client.post("/api/v1/storage/rollup-now")
    assert resp.status_code == 200
    data = resp.json()
    # Old row deleted, recent row kept
    assert data["raw_count"] == 1
