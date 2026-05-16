from datetime import datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from heartbeat.models.check_result import CheckResult
from heartbeat.models.daily_rollup import DailyRollup
from heartbeat.models.endpoint import StreakOutcome
from heartbeat.models.hourly_rollup import HourlyRollup


async def get_uptime(
    session: AsyncSession,
    endpoint_id: int,
    now: datetime,
) -> dict[str, float]:
    """Return uptime percentages for 24h (raw), 7d (hourly), and 30d (daily)."""
    return {
        "h24": await _uptime_raw(session, endpoint_id, now, timedelta(hours=24)),
        "d7": await _uptime_hourly(session, endpoint_id, now, timedelta(days=7)),
        "d30": await _uptime_daily(session, endpoint_id, now, timedelta(days=30)),
    }


async def _uptime_raw(
    session: AsyncSession,
    endpoint_id: int,
    now: datetime,
    window: timedelta,
) -> float:
    since = now - window
    row = (
        await session.execute(
            select(
                func.count().label("total"),
                func.sum(case((CheckResult.outcome == StreakOutcome.success, 1), else_=0)).label(
                    "successes"
                ),
            ).where(
                CheckResult.endpoint_id == endpoint_id,
                CheckResult.checked_at >= since,
            )
        )
    ).one()
    total = row.total or 0
    successes = row.successes or 0
    return round(successes / total * 100, 2) if total > 0 else 0.0


async def _uptime_hourly(
    session: AsyncSession,
    endpoint_id: int,
    now: datetime,
    window: timedelta,
) -> float:
    since = now - window
    row = (
        await session.execute(
            select(
                func.sum(HourlyRollup.total_checks).label("total"),
                func.sum(HourlyRollup.successful_checks).label("successes"),
            ).where(
                HourlyRollup.endpoint_id == endpoint_id,
                HourlyRollup.bucket_start >= since,
            )
        )
    ).one()
    total = row.total or 0
    successes = row.successes or 0
    return round(successes / total * 100, 2) if total > 0 else 0.0


async def _uptime_daily(
    session: AsyncSession,
    endpoint_id: int,
    now: datetime,
    window: timedelta,
) -> float:
    since_date = (now - window).date()
    row = (
        await session.execute(
            select(
                func.sum(DailyRollup.total_checks).label("total"),
                func.sum(DailyRollup.successful_checks).label("successes"),
            ).where(
                DailyRollup.endpoint_id == endpoint_id,
                DailyRollup.bucket_date >= since_date,
            )
        )
    ).one()
    total = row.total or 0
    successes = row.successes or 0
    return round(successes / total * 100, 2) if total > 0 else 0.0
