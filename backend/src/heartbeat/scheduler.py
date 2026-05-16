import asyncio
import contextlib
import logging
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from heartbeat.checker import Checker
from heartbeat.clock import Clock
from heartbeat.models.check_result import CheckResult
from heartbeat.models.endpoint import Endpoint, StreakOutcome
from heartbeat.services import incident_service

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        checker: Checker,
        clock: Clock,
        concurrency: int = 50,
    ) -> None:
        self._session_factory = session_factory
        self._checker = checker
        self._clock = clock
        self._semaphore = asyncio.Semaphore(concurrency)
        self.in_flight: set[int] = set()
        self._loop_task: asyncio.Task | None = None
        self._in_flight_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._loop_task = asyncio.create_task(self._loop(), name="scheduler-loop")
        logger.info("Scheduler started")

    async def stop(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None
        if self._in_flight_tasks:
            await asyncio.gather(*list(self._in_flight_tasks), return_exceptions=True)
        logger.info("Scheduler stopped")

    async def _loop(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(1.0)

    async def tick(self) -> set[asyncio.Task[None]]:
        """Run one scheduler iteration. Returns the tasks spawned this tick."""
        now = self._clock.now()

        conditions = [
            Endpoint.enabled == True,  # noqa: E712
            or_(Endpoint.next_due_at.is_(None), Endpoint.next_due_at <= now),
        ]
        if self.in_flight:
            conditions.append(Endpoint.id.notin_(list(self.in_flight)))

        async with self._session_factory() as session:
            result = await session.execute(
                select(Endpoint).where(*conditions).order_by(Endpoint.next_due_at.nullsfirst())
            )
            due_endpoints = list(result.scalars().all())

        spawned: set[asyncio.Task] = set()
        for endpoint in due_endpoints:
            self.in_flight.add(endpoint.id)
            task = asyncio.create_task(
                self._check_endpoint(endpoint.id), name=f"check-{endpoint.id}"
            )
            self._in_flight_tasks.add(task)
            task.add_done_callback(self._in_flight_tasks.discard)
            spawned.add(task)

        return spawned

    async def _check_endpoint(self, endpoint_id: int) -> None:
        try:
            now = self._clock.now()
            async with self._session_factory() as session:
                endpoint = await session.get(Endpoint, endpoint_id)
                if endpoint is None:
                    return

                async with self._semaphore:
                    outcome = await self._checker.check(endpoint)

                check_result = CheckResult(
                    endpoint_id=endpoint.id,
                    checked_at=now,
                    outcome=StreakOutcome(outcome.outcome),
                    latency_ms=outcome.latency_ms,
                    status_code=outcome.status_code,
                    error_category=outcome.error_category,
                    error_message=outcome.error_message,
                )
                session.add(check_result)

                await incident_service.apply_check_result(session, endpoint, check_result)

                interval = timedelta(seconds=endpoint.check_interval_seconds)
                prev_due = endpoint.next_due_at
                if prev_due is not None:
                    next_due = max(prev_due + interval, now)
                else:
                    next_due = now + interval
                endpoint.next_due_at = next_due

                await session.commit()
        except Exception:
            logger.exception("Error checking endpoint %d", endpoint_id)
        finally:
            self.in_flight.discard(endpoint_id)
