"""Integration tests for Phase 9: AI postmortem generation and editing."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from heartbeat.config import settings
from heartbeat.db import get_session
from heartbeat.main import app
from heartbeat.models.incident import Incident
from heartbeat.services.postmortem_service import PostmortemUpstreamError

_STARTED_AT = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
_ENDED_AT = datetime(2025, 1, 15, 10, 5, 0, tzinfo=UTC)
_FROZEN_TIMELINE = [
    {
        "checked_at": "2025-01-15T10:00:00+00:00",
        "outcome": "failure",
        "latency_ms": 10005,
        "status_code": None,
        "error_category": "timeout",
        "error_message": "request timed out",
    },
    {
        "checked_at": "2025-01-15T10:01:00+00:00",
        "outcome": "success",
        "latency_ms": 120,
        "status_code": 200,
        "error_category": None,
        "error_message": None,
    },
]

_CANNED_CONTENT = (
    "The service experienced a brief timeout incident. "
    "Root cause was likely a slow upstream dependency. "
    "Recommended: add a circuit breaker and review timeout thresholds."
)


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(db_engine) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text("DELETE FROM postmortems"))
        await session.execute(text("DELETE FROM incidents"))
        await session.execute(text("DELETE FROM endpoints"))
        await session.commit()


@pytest_asyncio.fixture
async def session_factory(db_engine) -> async_sessionmaker:
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(db_engine) -> AsyncGenerator[AsyncClient, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _test_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _test_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_session, None)


async def _create_endpoint(client: AsyncClient) -> int:
    resp = await client.post(
        "/api/v1/endpoints",
        json={
            "name": "Test Service",
            "url": "https://example.com/health",
            "check_interval_seconds": 60,
            "timeout_seconds": 10,
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _create_incident(session_factory: async_sessionmaker, endpoint_id: int) -> int:
    async with session_factory() as session:
        incident = Incident(
            endpoint_id=endpoint_id,
            started_at=_STARTED_AT,
            ended_at=_ENDED_AT,
            duration_seconds=300,
            frozen_timeline=_FROZEN_TIMELINE,
        )
        session.add(incident)
        await session.commit()
        await session.refresh(incident)
        return incident.id


def _make_mock_client(content: str = _CANNED_CONTENT) -> MagicMock:
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    return mock_client


async def test_generate_postmortem(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    monkeypatch,
) -> None:
    endpoint_id = await _create_endpoint(client)
    incident_id = await _create_incident(session_factory, endpoint_id)

    monkeypatch.setattr("heartbeat.ai.client.get_ai_client", lambda: _make_mock_client())
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")

    resp = await client.post(f"/api/v1/incidents/{incident_id}/postmortem/generate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == _CANNED_CONTENT
    assert data["generated_at"] is not None
    assert data["edited_at"] is None


async def test_update_postmortem(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    monkeypatch,
) -> None:
    endpoint_id = await _create_endpoint(client)
    incident_id = await _create_incident(session_factory, endpoint_id)

    monkeypatch.setattr("heartbeat.ai.client.get_ai_client", lambda: _make_mock_client())
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")

    # Generate first
    await client.post(f"/api/v1/incidents/{incident_id}/postmortem/generate")

    # Edit
    edited = "Human-written postmortem replacing the AI draft."
    resp = await client.put(
        f"/api/v1/incidents/{incident_id}/postmortem",
        json={"content": edited},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == edited
    assert data["edited_at"] is not None


async def test_regenerate_resets_edited_at(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    monkeypatch,
) -> None:
    endpoint_id = await _create_endpoint(client)
    incident_id = await _create_incident(session_factory, endpoint_id)

    monkeypatch.setattr("heartbeat.ai.client.get_ai_client", lambda: _make_mock_client())
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")

    # Generate, then edit, then regenerate
    await client.post(f"/api/v1/incidents/{incident_id}/postmortem/generate")
    await client.put(
        f"/api/v1/incidents/{incident_id}/postmortem",
        json={"content": "My edited text."},
    )

    new_content = "Fresh AI draft after regeneration."
    monkeypatch.setattr("heartbeat.ai.client.get_ai_client", lambda: _make_mock_client(new_content))
    resp = await client.post(f"/api/v1/incidents/{incident_id}/postmortem/generate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == new_content
    assert data["generated_at"] is not None
    assert data["edited_at"] is None


async def test_incident_detail_includes_postmortem(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    monkeypatch,
) -> None:
    endpoint_id = await _create_endpoint(client)
    incident_id = await _create_incident(session_factory, endpoint_id)

    # Before generation: postmortem field is null
    resp = await client.get(f"/api/v1/incidents/{incident_id}")
    assert resp.status_code == 200
    assert resp.json()["postmortem"] is None

    # After generation: postmortem field populated
    monkeypatch.setattr("heartbeat.ai.client.get_ai_client", lambda: _make_mock_client())
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")
    await client.post(f"/api/v1/incidents/{incident_id}/postmortem/generate")

    resp = await client.get(f"/api/v1/incidents/{incident_id}")
    assert resp.status_code == 200
    pm = resp.json()["postmortem"]
    assert pm is not None
    assert pm["content"] == _CANNED_CONTENT


async def test_generate_no_api_key(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    resp = await client.post("/api/v1/incidents/99999/postmortem/generate")
    assert resp.status_code == 503
    assert "OPENROUTER_API_KEY" in resp.json()["detail"]


async def test_generate_upstream_error(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    monkeypatch,
) -> None:
    endpoint_id = await _create_endpoint(client)
    incident_id = await _create_incident(session_factory, endpoint_id)

    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")
    monkeypatch.setattr(
        "heartbeat.services.postmortem_service.generate",
        AsyncMock(side_effect=PostmortemUpstreamError("connection reset by peer")),
    )

    resp = await client.post(f"/api/v1/incidents/{incident_id}/postmortem/generate")
    assert resp.status_code == 502
    assert "connection reset" in resp.json()["detail"]


async def test_generate_incident_not_found(
    client: AsyncClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")
    monkeypatch.setattr("heartbeat.ai.client.get_ai_client", lambda: _make_mock_client())

    resp = await client.post("/api/v1/incidents/99999/postmortem/generate")
    assert resp.status_code == 404


async def test_update_incident_not_found(client: AsyncClient) -> None:
    resp = await client.put(
        "/api/v1/incidents/99999/postmortem",
        json={"content": "some content"},
    )
    assert resp.status_code == 404
