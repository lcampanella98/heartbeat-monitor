from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from heartbeat.config import settings
from heartbeat.db import check_db_connection, engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await check_db_connection()
    yield
    await engine.dispose()


app = FastAPI(title="Heartbeat Monitor", lifespan=lifespan)


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
        n=3,
        m=2,
    )
