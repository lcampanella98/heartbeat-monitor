from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from heartbeat.clock import FakeClock
from heartbeat.db import get_session
from heartbeat.dependencies import get_clock
from heartbeat.main import app

_FIXED_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

_VALID_PAYLOAD = {
    "name": "My API",
    "url": "https://example.com/health",
    "check_interval_seconds": 60,
    "timeout_seconds": 10,
}


@pytest_asyncio.fixture(autouse=True)
async def clean_endpoints(db_engine) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text("DELETE FROM endpoints"))
        await session.commit()


@pytest_asyncio.fixture
async def fake_clock() -> FakeClock:
    return FakeClock(_FIXED_NOW)


@pytest_asyncio.fixture
async def client(db_engine, fake_clock: FakeClock) -> AsyncGenerator[AsyncClient, None]:
    # Override get_session so FastAPI routes use the test engine (NullPool),
    # preventing event-loop reuse issues across tests on Windows.
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_clock] = lambda: fake_clock
    app.dependency_overrides[get_session] = _test_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_clock, None)
    app.dependency_overrides.pop(get_session, None)


async def test_create_endpoint_returns_201(client: AsyncClient) -> None:
    response = await client.post("/api/v1/endpoints", json=_VALID_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "My API"
    assert data["url"] == "https://example.com/health"
    assert data["check_interval_seconds"] == 60
    assert data["timeout_seconds"] == 10
    assert data["enabled"] is True
    assert data["id"] is not None
    assert data["user_id"] == 1


async def test_create_sets_next_due_at_to_now(client: AsyncClient, fake_clock: FakeClock) -> None:
    response = await client.post("/api/v1/endpoints", json=_VALID_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    next_due = datetime.fromisoformat(data["next_due_at"])
    assert next_due == fake_clock.now()


async def test_list_endpoints_returns_created(client: AsyncClient) -> None:
    await client.post("/api/v1/endpoints", json=_VALID_PAYLOAD)
    response = await client.get("/api/v1/endpoints")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["name"] == "My API"


async def test_get_endpoint_by_id(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/endpoints", json=_VALID_PAYLOAD)).json()
    response = await client.get(f"/api/v1/endpoints/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_get_nonexistent_endpoint_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/endpoints/99999")
    assert response.status_code == 404


async def test_update_endpoint(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/endpoints", json=_VALID_PAYLOAD)).json()
    response = await client.put(
        f"/api/v1/endpoints/{created['id']}",
        json={"name": "Updated Name", "timeout_seconds": 30},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["timeout_seconds"] == 30
    assert data["url"] == _VALID_PAYLOAD["url"]  # unchanged


async def test_update_nonexistent_returns_404(client: AsyncClient) -> None:
    response = await client.put("/api/v1/endpoints/99999", json={"name": "x"})
    assert response.status_code == 404


async def test_delete_endpoint(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/endpoints", json=_VALID_PAYLOAD)).json()
    delete_resp = await client.delete(f"/api/v1/endpoints/{created['id']}")
    assert delete_resp.status_code == 204
    get_resp = await client.get(f"/api/v1/endpoints/{created['id']}")
    assert get_resp.status_code == 404


async def test_delete_nonexistent_returns_404(client: AsyncClient) -> None:
    response = await client.delete("/api/v1/endpoints/99999")
    assert response.status_code == 404


async def test_disable_endpoint(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/endpoints", json=_VALID_PAYLOAD)).json()
    assert created["enabled"] is True
    response = await client.post(f"/api/v1/endpoints/{created['id']}/disable")
    assert response.status_code == 200
    assert response.json()["enabled"] is False


async def test_enable_endpoint(client: AsyncClient) -> None:
    payload = {**_VALID_PAYLOAD, "enabled": False}
    created = (await client.post("/api/v1/endpoints", json=payload)).json()
    assert created["enabled"] is False
    response = await client.post(f"/api/v1/endpoints/{created['id']}/enable")
    assert response.status_code == 200
    assert response.json()["enabled"] is True


async def test_enable_nonexistent_returns_404(client: AsyncClient) -> None:
    response = await client.post("/api/v1/endpoints/99999/enable")
    assert response.status_code == 404


async def test_disable_nonexistent_returns_404(client: AsyncClient) -> None:
    response = await client.post("/api/v1/endpoints/99999/disable")
    assert response.status_code == 404


async def test_create_bad_url_returns_422(client: AsyncClient) -> None:
    payload = {**_VALID_PAYLOAD, "url": "ftp://bad.com"}
    response = await client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 422


async def test_create_bad_interval_returns_422(client: AsyncClient) -> None:
    payload = {**_VALID_PAYLOAD, "check_interval_seconds": 45}
    response = await client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 422


async def test_create_timeout_too_low_returns_422(client: AsyncClient) -> None:
    payload = {**_VALID_PAYLOAD, "timeout_seconds": 0}
    response = await client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 422


async def test_create_timeout_too_high_returns_422(client: AsyncClient) -> None:
    payload = {**_VALID_PAYLOAD, "timeout_seconds": 61}
    response = await client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 422


async def test_list_empty_returns_empty_list(client: AsyncClient) -> None:
    response = await client.get("/api/v1/endpoints")
    assert response.status_code == 200
    assert response.json() == []


async def test_sim_outage_windows_roundtrip(client: AsyncClient) -> None:
    payload = {
        **_VALID_PAYLOAD,
        "sim_outage_windows": [{"start": "02:00", "end": "02:30"}],
    }
    created = (await client.post("/api/v1/endpoints", json=payload)).json()
    assert created["sim_outage_windows"] == [{"start": "02:00", "end": "02:30"}]
    fetched = (await client.get(f"/api/v1/endpoints/{created['id']}")).json()
    assert fetched["sim_outage_windows"] == [{"start": "02:00", "end": "02:30"}]


async def test_create_empty_name_returns_422(client: AsyncClient) -> None:
    payload = {**_VALID_PAYLOAD, "name": ""}
    response = await client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 422


async def test_create_inverted_latency_range_returns_422(client: AsyncClient) -> None:
    payload = {**_VALID_PAYLOAD, "sim_latency_min_ms": 500, "sim_latency_max_ms": 100}
    response = await client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 422


async def test_update_inverted_latency_range_returns_422(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/endpoints", json=_VALID_PAYLOAD)).json()
    response = await client.put(
        f"/api/v1/endpoints/{created['id']}",
        json={"sim_latency_min_ms": 800, "sim_latency_max_ms": 200},
    )
    assert response.status_code == 422


async def test_update_null_outage_windows_clears_to_empty(client: AsyncClient) -> None:
    payload = {
        **_VALID_PAYLOAD,
        "sim_outage_windows": [{"start": "02:00", "end": "02:30"}],
    }
    created = (await client.post("/api/v1/endpoints", json=payload)).json()
    assert created["sim_outage_windows"] == [{"start": "02:00", "end": "02:30"}]

    response = await client.put(
        f"/api/v1/endpoints/{created['id']}",
        json={"sim_outage_windows": None},
    )
    assert response.status_code == 200
    assert response.json()["sim_outage_windows"] == []
