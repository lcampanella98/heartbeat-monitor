import logging
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from heartbeat.alerts.log_sink import LogSink
from heartbeat.alerts.smtp_sink import SmtpSink
from heartbeat.api.endpoints import router as endpoints_router
from heartbeat.api.incidents import router as incidents_router
from heartbeat.api.notifications import router as notifications_router
from heartbeat.api.recipients import router as recipients_router
from heartbeat.checker.real import RealChecker
from heartbeat.checker.simulated import SimulatedChecker
from heartbeat.clock import RealClock
from heartbeat.config import settings
from heartbeat.db import async_session_factory, check_db_connection, engine
from heartbeat.scheduler import Scheduler
from heartbeat.services.alert_dispatcher import AlertDispatcher
from heartbeat.services.incident_service import M, N

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await check_db_connection()

    http_client: httpx.AsyncClient | None = None
    clock = RealClock()

    if settings.check_source == "real":
        http_client = httpx.AsyncClient(
            follow_redirects=True,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        checker = RealChecker(http_client=http_client)
        logger.info("Checker: real (live HTTP requests)")
    else:
        checker = SimulatedChecker(clock=clock, rng=random.Random())
        logger.info("Checker: simulated (no outbound HTTP)")

    app.state.checker = checker

    if settings.email_sink == "log":
        sink = LogSink(session_factory=async_session_factory)
        logger.info("Alert sink: log (captured to DB)")
    else:
        sink = SmtpSink(settings=settings)
        logger.info("Alert sink: smtp (outbound email)")

    dispatcher = AlertDispatcher(session_factory=async_session_factory, sink=sink)

    scheduler = Scheduler(
        session_factory=async_session_factory,
        checker=checker,
        clock=clock,
        concurrency=settings.scheduler_concurrency,
        dispatcher=dispatcher,
    )
    app.state.scheduler = scheduler
    await scheduler.start()

    yield

    await scheduler.stop()
    if http_client is not None:
        await http_client.aclose()
    await engine.dispose()


app = FastAPI(title="Heartbeat Monitor", lifespan=lifespan)
app.include_router(endpoints_router)
app.include_router(incidents_router)
app.include_router(recipients_router)
app.include_router(notifications_router)


class SystemStatus(BaseModel):
    check_source: Literal["real", "simulated"]
    email_sink: Literal["smtp", "log"]
    smtp_from: str | None
    n: int
    m: int


@app.get("/api/v1/system/status")
async def system_status() -> SystemStatus:
    return SystemStatus(
        check_source=settings.check_source,
        email_sink=settings.email_sink,
        smtp_from=settings.smtp_from or None,
        n=N,
        m=M,
    )
