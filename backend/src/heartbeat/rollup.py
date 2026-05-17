import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from heartbeat.clock import Clock

logger = logging.getLogger(__name__)

RAW_RETENTION_DAYS = 30
HOURLY_RETENTION_DAYS = 180
ROLLUP_INTERVAL_SECONDS = 300  # 5 minutes

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _hourly_lookback(now: datetime, full: bool) -> datetime:
    return _EPOCH if full else now - timedelta(days=RAW_RETENTION_DAYS)


def _daily_lookback(now: datetime, full: bool) -> datetime:
    return _EPOCH if full else now - timedelta(days=HOURLY_RETENTION_DAYS)


_HOURLY_UPSERT = text(
    """
    INSERT INTO hourly_rollups
        (endpoint_id, bucket_start, total_checks, successful_checks, failed_checks, uptime_pct)
    SELECT
        endpoint_id,
        date_trunc('hour', checked_at) AS bucket_start,
        count(*) AS total_checks,
        sum(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS successful_checks,
        sum(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) AS failed_checks,
        COALESCE(round(
            sum(CASE WHEN outcome = 'success' THEN 1.0 ELSE 0.0 END)
            / nullif(count(*), 0) * 100,
            2
        ), 0) AS uptime_pct
    FROM check_results
    WHERE checked_at >= :lookback
    GROUP BY endpoint_id, date_trunc('hour', checked_at)
    ON CONFLICT (endpoint_id, bucket_start) DO UPDATE SET
        total_checks      = EXCLUDED.total_checks,
        successful_checks = EXCLUDED.successful_checks,
        failed_checks     = EXCLUDED.failed_checks,
        uptime_pct        = EXCLUDED.uptime_pct
    """
)

_DAILY_UPSERT = text(
    """
    INSERT INTO daily_rollups
        (endpoint_id, bucket_date, total_checks, successful_checks, failed_checks, uptime_pct)
    SELECT
        endpoint_id,
        (bucket_start AT TIME ZONE 'UTC')::date AS bucket_date,
        sum(total_checks) AS total_checks,
        sum(successful_checks) AS successful_checks,
        sum(failed_checks) AS failed_checks,
        COALESCE(round(
            sum(successful_checks)::numeric / nullif(sum(total_checks), 0) * 100,
            2
        ), 0) AS uptime_pct
    FROM hourly_rollups
    WHERE bucket_start >= :lookback
    GROUP BY endpoint_id, (bucket_start AT TIME ZONE 'UTC')::date
    ON CONFLICT (endpoint_id, bucket_date) DO UPDATE SET
        total_checks      = EXCLUDED.total_checks,
        successful_checks = EXCLUDED.successful_checks,
        failed_checks     = EXCLUDED.failed_checks,
        uptime_pct        = EXCLUDED.uptime_pct
    """
)


class RollupJob:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        clock: Clock,
        interval_seconds: int = ROLLUP_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self.interval_seconds = interval_seconds
        self._loop_task: asyncio.Task | None = None
        self.last_run_at: datetime | None = None

    async def start(self) -> None:
        self._loop_task = asyncio.create_task(self._loop(), name="rollup-loop")
        logger.info("RollupJob started (interval=%ds)", self.interval_seconds)

    async def stop(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None
        logger.info("RollupJob stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Rollup failed; will retry in 60 s")
                await asyncio.sleep(60)
                continue
            await asyncio.sleep(self.interval_seconds)

    async def run_once(self, full: bool = False) -> None:
        """Run all rollup and retention steps.

        When full=True, widens the UPSERT lookback to cover all available data
        (used after bulk seeding to backfill rollups across the full history).
        """
        now = self._clock.now()
        async with self._session_factory() as session:
            await session.execute(
                _HOURLY_UPSERT,
                {"lookback": _hourly_lookback(now, full)},
            )
            await session.execute(
                _DAILY_UPSERT,
                {"lookback": _daily_lookback(now, full)},
            )
            await session.execute(
                text("DELETE FROM check_results WHERE checked_at < :cutoff"),
                {"cutoff": now - timedelta(days=RAW_RETENTION_DAYS)},
            )
            await session.execute(
                text("DELETE FROM hourly_rollups WHERE bucket_start < :cutoff"),
                {"cutoff": now - timedelta(days=HOURLY_RETENTION_DAYS)},
            )
            await session.commit()
        self.last_run_at = now
        logger.info("Rollup complete at %s (full=%s)", now, full)
