from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from heartbeat.models.check_result import CheckResult
from heartbeat.models.daily_rollup import DailyRollup
from heartbeat.models.endpoint import StreakOutcome
from heartbeat.models.hourly_rollup import HourlyRollup

RangeKey = Literal["1h", "1d", "7d", "30d", "90d", "1y"]
HistorySource = Literal["raw", "hourly", "daily"]

_RANGE_MAP: dict[str, tuple[timedelta, HistorySource]] = {
    "1h": (timedelta(hours=1), "raw"),
    "1d": (timedelta(days=1), "raw"),
    "7d": (timedelta(days=7), "hourly"),
    "30d": (timedelta(days=30), "daily"),
    "90d": (timedelta(days=90), "daily"),
    "1y": (timedelta(days=365), "daily"),
}


def resolve_range(range_key: str) -> tuple[timedelta, HistorySource]:
    """Return (lookback_duration, source_tier) for the given range key."""
    if range_key not in _RANGE_MAP:
        raise ValueError(f"Unknown range key: {range_key!r}")
    return _RANGE_MAP[range_key]


@dataclass(slots=True)
class HistoryBin:
    bucket_start: datetime
    source: HistorySource
    total_checks: int
    successful_checks: int
    failed_checks: int
    uptime_pct: float


async def get_history(
    session: AsyncSession,
    endpoint_id: int,
    range_key: str,
    now: datetime,
) -> list[HistoryBin]:
    duration, source = resolve_range(range_key)
    since = now - duration

    if source == "raw":
        rows = (
            (
                await session.execute(
                    select(CheckResult)
                    .where(
                        CheckResult.endpoint_id == endpoint_id,
                        CheckResult.checked_at >= since,
                    )
                    .order_by(asc(CheckResult.checked_at))
                )
            )
            .scalars()
            .all()
        )
        return [
            HistoryBin(
                bucket_start=r.checked_at,
                source="raw",
                total_checks=1,
                successful_checks=1 if r.outcome == StreakOutcome.success else 0,
                failed_checks=0 if r.outcome == StreakOutcome.success else 1,
                uptime_pct=100.0 if r.outcome == StreakOutcome.success else 0.0,
            )
            for r in rows
        ]

    if source == "hourly":
        rows = (
            (
                await session.execute(
                    select(HourlyRollup)
                    .where(
                        HourlyRollup.endpoint_id == endpoint_id,
                        HourlyRollup.bucket_start >= since,
                    )
                    .order_by(asc(HourlyRollup.bucket_start))
                )
            )
            .scalars()
            .all()
        )
        return [
            HistoryBin(
                bucket_start=r.bucket_start,
                source="hourly",
                total_checks=r.total_checks,
                successful_checks=r.successful_checks,
                failed_checks=r.failed_checks,
                uptime_pct=float(r.uptime_pct),
            )
            for r in rows
        ]

    # daily
    rows = (
        (
            await session.execute(
                select(DailyRollup)
                .where(
                    DailyRollup.endpoint_id == endpoint_id,
                    DailyRollup.bucket_date >= since.date(),
                )
                .order_by(asc(DailyRollup.bucket_date))
            )
        )
        .scalars()
        .all()
    )
    return [
        HistoryBin(
            bucket_start=datetime(
                r.bucket_date.year,
                r.bucket_date.month,
                r.bucket_date.day,
                tzinfo=now.tzinfo,
            ),
            source="daily",
            total_checks=r.total_checks,
            successful_checks=r.successful_checks,
            failed_checks=r.failed_checks,
            uptime_pct=float(r.uptime_pct),
        )
        for r in rows
    ]
