"""Integration tests for Phase 7: alert sinks, dispatcher, and notification routes."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from heartbeat.alerts.log_sink import LogSink
from heartbeat.checker import CheckOutcome
from heartbeat.clock import FakeClock
from heartbeat.db import get_session
from heartbeat.dependencies import get_clock
from heartbeat.main import app
from heartbeat.models.check_result import ErrorCategory
from heartbeat.models.email_recipient import EmailRecipient
from heartbeat.models.endpoint import Endpoint
from heartbeat.models.incident import Incident
from heartbeat.models.sent_notification import NotificationKind, SentNotification
from heartbeat.scheduler import Scheduler
from heartbeat.services.alert_dispatcher import AlertDispatcher

_FIXED_NOW = datetime(2025, 7, 1, 10, 0, 0, tzinfo=UTC)

_BASE_ENDPOINT = {
    "name": "Alert Test API",
    "url": "https://example.com/health",
    "check_interval_seconds": 60,
    "timeout_seconds": 10,
}


class SequenceChecker:
    def __init__(self, outcomes: list[str]) -> None:
        self._outcomes = outcomes
        self._index = 0

    async def check(self, endpoint: Endpoint) -> CheckOutcome:
        if self._index >= len(self._outcomes):
            raise IndexError("SequenceChecker exhausted")
        outcome = self._outcomes[self._index]
        self._index += 1
        return CheckOutcome(
            outcome=outcome,
            latency_ms=100,
            status_code=200 if outcome == "success" else None,
            error_category=None if outcome == "success" else ErrorCategory.other,
            error_message=None if outcome == "success" else "simulated failure",
        )


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(db_engine) -> None:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text("DELETE FROM sent_notifications"))
        await session.execute(text("DELETE FROM email_recipients"))
        await session.execute(text("DELETE FROM postmortems"))
        await session.execute(text("DELETE FROM incidents"))
        await session.execute(text("DELETE FROM check_results"))
        await session.execute(text("DELETE FROM endpoints"))
        await session.commit()


@pytest_asyncio.fixture
async def session_factory(db_engine) -> async_sessionmaker:
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def fake_clock() -> FakeClock:
    return FakeClock(_FIXED_NOW)


@pytest_asyncio.fixture
async def client(db_engine, fake_clock) -> AsyncGenerator[AsyncClient, None]:
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


async def _run_sequence(
    session_factory: async_sessionmaker,
    checker: SequenceChecker,
    clock: FakeClock,
    n_ticks: int,
    dispatcher: AlertDispatcher | None = None,
    tick_interval_seconds: int = 60,
) -> Scheduler:
    scheduler = Scheduler(
        session_factory=session_factory,
        checker=checker,
        clock=clock,
        concurrency=10,
        dispatcher=dispatcher,
    )
    for _ in range(n_ticks):
        tasks = await scheduler.tick()
        await asyncio.gather(*tasks)
        clock.advance(timedelta(seconds=tick_interval_seconds))
    await scheduler.wait_for_dispatch()
    return scheduler


# ---------------------------------------------------------------------------
# LogSink ring buffer
# ---------------------------------------------------------------------------


async def test_log_sink_ring_buffer(session_factory: async_sessionmaker) -> None:
    """Ring buffer keeps exactly ring_buffer_size rows; the oldest is evicted first."""
    async with session_factory() as session:
        endpoint = Endpoint(
            user_id=1,
            name="ring-buf-test",
            url="https://example.com",
            check_interval_seconds=60,
            timeout_seconds=10,
        )
        session.add(endpoint)
        await session.flush()
        incident = Incident(endpoint_id=endpoint.id, started_at=_FIXED_NOW)
        session.add(incident)
        await session.commit()
        incident_id = incident.id

    # Use a small ring_buffer_size so the test only needs 11 round-trips, not 1001.
    sink = LogSink(session_factory=session_factory, ring_buffer_size=10)

    for i in range(11):
        await sink.send_email(
            kind=NotificationKind.incident_opened,
            incident_id=incident_id,
            subject=f"subject {i}",
            body="body",
            recipients=["test@example.com"],
        )

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(SentNotification))
        oldest = await session.scalar(
            select(SentNotification).order_by(SentNotification.id.asc()).limit(1)
        )

    assert count == 10
    assert oldest is not None
    # subject 0 (first inserted) should be gone; oldest remaining is subject 1
    assert oldest.subject == "subject 1"


# ---------------------------------------------------------------------------
# Dispatcher integration: incident open → sent_notifications
# ---------------------------------------------------------------------------


async def test_incident_open_produces_notification(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    # Add a recipient so the dispatcher has someone to notify
    async with session_factory() as session:
        session.add(EmailRecipient(user_id=1, address="ops@example.com"))
        await session.commit()

    resp = await client.post("/api/v1/endpoints", json=_BASE_ENDPOINT)
    assert resp.status_code == 201

    sink = LogSink(session_factory=session_factory)
    dispatcher = AlertDispatcher(session_factory=session_factory, sink=sink)
    checker = SequenceChecker(["failure", "failure", "failure"])

    await _run_sequence(session_factory, checker, fake_clock, n_ticks=3, dispatcher=dispatcher)

    async with session_factory() as session:
        notifications = (
            (await session.execute(select(SentNotification).order_by(SentNotification.id)))
            .scalars()
            .all()
        )

    assert len(notifications) == 1
    notif = notifications[0]
    assert notif.kind == NotificationKind.incident_opened
    assert notif.recipients == ["ops@example.com"]
    assert "Incident opened" in notif.subject
    assert "/incidents/" in notif.body


async def test_incident_open_and_close_produces_two_notifications(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    async with session_factory() as session:
        session.add(EmailRecipient(user_id=1, address="ops@example.com"))
        await session.commit()

    resp = await client.post("/api/v1/endpoints", json=_BASE_ENDPOINT)
    assert resp.status_code == 201

    sink = LogSink(session_factory=session_factory)
    dispatcher = AlertDispatcher(session_factory=session_factory, sink=sink)
    checker = SequenceChecker(["failure", "failure", "failure", "success", "success"])

    await _run_sequence(session_factory, checker, fake_clock, n_ticks=5, dispatcher=dispatcher)

    async with session_factory() as session:
        notifications = (
            (await session.execute(select(SentNotification).order_by(SentNotification.id)))
            .scalars()
            .all()
        )

    assert len(notifications) == 2
    assert notifications[0].kind == NotificationKind.incident_opened
    assert notifications[1].kind == NotificationKind.incident_closed
    assert "Incident closed" in notifications[1].subject
    assert "Duration" in notifications[1].body


async def test_no_notifications_when_no_recipients(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    resp = await client.post("/api/v1/endpoints", json=_BASE_ENDPOINT)
    assert resp.status_code == 201

    sink = LogSink(session_factory=session_factory)
    dispatcher = AlertDispatcher(session_factory=session_factory, sink=sink)
    checker = SequenceChecker(["failure", "failure", "failure"])

    await _run_sequence(session_factory, checker, fake_clock, n_ticks=3, dispatcher=dispatcher)

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(SentNotification))
    # LogSink still inserts a row even with empty recipients
    assert count == 1
    async with session_factory() as session:
        notif = await session.scalar(select(SentNotification))
    assert notif is not None
    assert notif.recipients == []


# ---------------------------------------------------------------------------
# Recipients API
# ---------------------------------------------------------------------------


async def test_recipients_crud(client: AsyncClient) -> None:
    # Empty list
    resp = await client.get("/api/v1/recipients")
    assert resp.status_code == 200
    assert resp.json() == []

    # Create
    resp = await client.post("/api/v1/recipients", json={"address": "alice@example.com"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["address"] == "alice@example.com"
    rid = data["id"]

    # List
    resp = await client.get("/api/v1/recipients")
    assert len(resp.json()) == 1

    # Duplicate rejected
    resp = await client.post("/api/v1/recipients", json={"address": "alice@example.com"})
    assert resp.status_code == 409

    # Invalid address rejected
    resp = await client.post("/api/v1/recipients", json={"address": "not-an-email"})
    assert resp.status_code == 422

    # Delete
    resp = await client.delete(f"/api/v1/recipients/{rid}")
    assert resp.status_code == 204

    resp = await client.get("/api/v1/recipients")
    assert resp.json() == []


async def test_delete_unknown_recipient_is_404(client: AsyncClient) -> None:
    resp = await client.delete("/api/v1/recipients/99999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Notifications API
# ---------------------------------------------------------------------------


async def test_notifications_list(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    async with session_factory() as session:
        session.add(EmailRecipient(user_id=1, address="ops@example.com"))
        await session.commit()

    resp = await client.post("/api/v1/endpoints", json=_BASE_ENDPOINT)
    assert resp.status_code == 201

    sink = LogSink(session_factory=session_factory)
    dispatcher = AlertDispatcher(session_factory=session_factory, sink=sink)
    checker = SequenceChecker(["failure", "failure", "failure", "success", "success"])

    await _run_sequence(session_factory, checker, fake_clock, n_ticks=5, dispatcher=dispatcher)

    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    # Newest first
    assert items[0]["kind"] == NotificationKind.incident_closed.value
    assert items[1]["kind"] == NotificationKind.incident_opened.value


async def test_notifications_cursor_pagination(
    client: AsyncClient,
    session_factory: async_sessionmaker,
    fake_clock: FakeClock,
) -> None:
    async with session_factory() as session:
        endpoint = Endpoint(
            user_id=1,
            name="cursor-test",
            url="https://example.com",
            check_interval_seconds=60,
            timeout_seconds=10,
        )
        session.add(endpoint)
        await session.flush()
        incident = Incident(endpoint_id=endpoint.id, started_at=_FIXED_NOW)
        session.add(incident)
        await session.flush()
        incident_id = incident.id
        for i in range(5):
            session.add(
                SentNotification(
                    kind=NotificationKind.incident_opened,
                    incident_id=incident_id,
                    subject=f"subject {i}",
                    body="body",
                    recipients=[],
                )
            )
        await session.commit()

    # Get first 3 (newest first)
    resp = await client.get("/api/v1/notifications?limit=3")
    assert resp.status_code == 200
    first_page = resp.json()
    assert len(first_page) == 3
    oldest_id_in_page = first_page[-1]["id"]

    # Get next page using before_id
    resp = await client.get(f"/api/v1/notifications?limit=3&before_id={oldest_id_in_page}")
    assert resp.status_code == 200
    second_page = resp.json()
    assert len(second_page) == 2
    # All IDs in second page are less than the cursor
    assert all(item["id"] < oldest_id_in_page for item in second_page)
