from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from heartbeat.db import get_session
from heartbeat.dependencies import get_rollup_job
from heartbeat.models.check_result import CheckResult
from heartbeat.models.daily_rollup import DailyRollup
from heartbeat.models.hourly_rollup import HourlyRollup
from heartbeat.rollup import HOURLY_RETENTION_DAYS, RAW_RETENTION_DAYS, RollupJob
from heartbeat.schemas.storage import StorageStats

router = APIRouter(prefix="/api/v1/storage", tags=["storage"])


async def _compute_stats(session: AsyncSession, rollup_job: RollupJob) -> StorageStats:
    raw_count = (await session.scalar(select(func.count()).select_from(CheckResult))) or 0
    hourly_count = (await session.scalar(select(func.count()).select_from(HourlyRollup))) or 0
    daily_count = (await session.scalar(select(func.count()).select_from(DailyRollup))) or 0

    last_run = rollup_job.last_run_at
    next_run = last_run + timedelta(seconds=rollup_job.interval_seconds) if last_run else None

    return StorageStats(
        raw_count=raw_count,
        hourly_count=hourly_count,
        daily_count=daily_count,
        raw_retention_days=RAW_RETENTION_DAYS,
        hourly_retention_days=HOURLY_RETENTION_DAYS,
        daily_retention_days=None,
        last_rollup_at=last_run,
        next_rollup_at=next_run,
    )


@router.get("/stats", response_model=StorageStats)
async def storage_stats(
    session: AsyncSession = Depends(get_session),
    rollup_job: RollupJob = Depends(get_rollup_job),
) -> StorageStats:
    return await _compute_stats(session, rollup_job)


@router.post("/rollup-now", response_model=StorageStats)
async def rollup_now(
    session: AsyncSession = Depends(get_session),
    rollup_job: RollupJob = Depends(get_rollup_job),
) -> StorageStats:
    await rollup_job.run_once()
    return await _compute_stats(session, rollup_job)
