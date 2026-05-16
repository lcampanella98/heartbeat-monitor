"""Integration tests for the demo seed."""

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from heartbeat.clock import FakeClock
from heartbeat.config import settings
from heartbeat.models.check_result import CheckResult
from heartbeat.models.daily_rollup import DailyRollup
from heartbeat.models.endpoint import Endpoint
from heartbeat.models.hourly_rollup import HourlyRollup
from heartbeat.models.incident import Incident
from heartbeat.seed import maybe_seed


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(db_engine) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text("DELETE FROM postmortems"))
        await session.execute(text("DELETE FROM incidents"))
        await session.execute(text("DELETE FROM sent_notifications"))
        await session.execute(text("DELETE FROM check_results"))
        await session.execute(text("DELETE FROM hourly_rollups"))
        await session.execute(text("DELETE FROM daily_rollups"))
        await session.execute(text("DELETE FROM endpoints"))
        await session.commit()


async def test_maybe_seed_populates_empty_db(db_engine, monkeypatch) -> None:
    monkeypatch.setattr(settings, "check_source", "simulated")
    monkeypatch.setattr(settings, "email_sink", "log")

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    clock = FakeClock()

    await maybe_seed(factory, clock, days=2, rng_seed=0)

    async with factory() as session:
        ep_count = await session.scalar(select(func.count()).select_from(Endpoint))
        cr_count = await session.scalar(select(func.count()).select_from(CheckResult))
        hr_count = await session.scalar(select(func.count()).select_from(HourlyRollup))
        dr_count = await session.scalar(select(func.count()).select_from(DailyRollup))
        incidents = (await session.execute(select(Incident))).scalars().all()

    assert ep_count == 5
    # 2 days of history across the 5 planned endpoints yields ~12k checks
    assert cr_count > 1_000
    assert hr_count > 0
    assert dr_count > 0

    for inc in incidents:
        if inc.ended_at is not None:
            assert inc.frozen_timeline is not None
            assert len(inc.frozen_timeline) > 0


async def test_maybe_seed_noop_when_endpoints_exist(db_engine, monkeypatch) -> None:
    monkeypatch.setattr(settings, "check_source", "simulated")
    monkeypatch.setattr(settings, "email_sink", "log")

    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    # Pre-create one endpoint
    async with factory() as session:
        session.add(
            Endpoint(
                user_id=1,
                name="existing",
                url="https://example.com",
                check_interval_seconds=60,
                timeout_seconds=10,
            )
        )
        await session.commit()

    clock = FakeClock()
    await maybe_seed(factory, clock, days=2, rng_seed=0)

    async with factory() as session:
        ep_count = await session.scalar(select(func.count()).select_from(Endpoint))
        cr_count = await session.scalar(select(func.count()).select_from(CheckResult))

    assert ep_count == 1   # still only the pre-existing endpoint
    assert cr_count == 0   # no check results seeded


async def test_maybe_seed_noop_when_not_demo_mode(db_engine, monkeypatch) -> None:
    monkeypatch.setattr(settings, "check_source", "real")
    monkeypatch.setattr(settings, "email_sink", "log")

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    clock = FakeClock()

    await maybe_seed(factory, clock, days=2, rng_seed=0)

    async with factory() as session:
        ep_count = await session.scalar(select(func.count()).select_from(Endpoint))

    assert ep_count == 0
