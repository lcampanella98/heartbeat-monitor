import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command

# Set DATABASE_URL before any heartbeat imports so the settings singleton picks it up.
_TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://heartbeat:heartbeat@localhost:5432/heartbeat_test",
)
os.environ.setdefault("DATABASE_URL", _TEST_DB_URL)

BACKEND_DIR = Path(__file__).parent.parent.parent


@pytest.fixture(scope="session")
def db_engine():
    async def reset_schema() -> None:
        engine = create_async_engine(_TEST_DB_URL, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await engine.dispose()

    asyncio.run(reset_schema())

    # Ensure env.py picks up the test URL when alembic runs.
    os.environ["DATABASE_URL"] = _TEST_DB_URL
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    # NullPool: no connection caching, so each test's event loop gets a fresh connection.
    engine = create_async_engine(_TEST_DB_URL, poolclass=NullPool)
    yield engine
    asyncio.run(engine.dispose())


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
