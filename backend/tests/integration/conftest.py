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

# Test DB URL
_TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://heartbeat:heartbeat@localhost:5432/heartbeat_test",
)

os.environ.setdefault("DATABASE_URL", _TEST_DB_URL)

BACKEND_DIR = Path(__file__).parent.parent.parent


def _admin_db_url() -> str:
    """
    Convert:
      postgresql+asyncpg://.../heartbeat_test
    into:
      postgresql+asyncpg://.../postgres
    """
    return _TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"


def _database_name() -> str:
    return _TEST_DB_URL.rsplit("/", 1)[1]


@pytest.fixture(scope="session")
def db_engine():
    async def ensure_database_exists() -> None:
        admin_engine = create_async_engine(
            _admin_db_url(),
            poolclass=NullPool,
            isolation_level="AUTOCOMMIT",
        )

        db_name = _database_name()

        async with admin_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :db_name"),
                {"db_name": db_name},
            )

            exists = result.scalar() is not None

            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))

        await admin_engine.dispose()

    async def reset_schema() -> None:
        engine = create_async_engine(_TEST_DB_URL, poolclass=NullPool)

        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))

        await engine.dispose()

    # Create DB if needed
    asyncio.run(ensure_database_exists())

    # Reset schema
    asyncio.run(reset_schema())

    # Run migrations
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
