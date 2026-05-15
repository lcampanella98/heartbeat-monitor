import pytest
from httpx import ASGITransport, AsyncClient

import heartbeat.main as main_module
from heartbeat.main import app


@pytest.fixture
async def client(db_engine):
    # db_engine ensures the test DB is ready and DATABASE_URL points to it.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_system_status_returns_200(client: AsyncClient) -> None:
    response = await client.get("/api/v1/system/status")
    assert response.status_code == 200


async def test_system_status_shape(client: AsyncClient) -> None:
    data = (await client.get("/api/v1/system/status")).json()
    assert "check_source" in data
    assert "email_sink" in data
    assert "n" in data
    assert "m" in data
    assert data["n"] == 3
    assert data["m"] == 2


async def test_system_status_reflects_settings(monkeypatch, db_engine) -> None:
    monkeypatch.setattr(main_module.settings, "check_source", "simulated")
    monkeypatch.setattr(main_module.settings, "email_sink", "log")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        data = (await client.get("/api/v1/system/status")).json()
    assert data["check_source"] == "simulated"
    assert data["email_sink"] == "log"
