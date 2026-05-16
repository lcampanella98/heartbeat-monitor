"""Unit tests for SmtpSink: verifies aiosmtplib.send is called correctly."""

from unittest.mock import AsyncMock

import aiosmtplib
import pytest

from heartbeat.alerts.smtp_sink import SmtpSink
from heartbeat.models.sent_notification import NotificationKind


class _FakeSettings:
    smtp_host = "smtp.example.com"
    smtp_port = 587
    smtp_username = "user"
    smtp_password = "secret"
    smtp_from = "noreply@example.com"
    smtp_starttls = True


@pytest.fixture
def smtp_settings() -> _FakeSettings:
    return _FakeSettings()


async def test_smtp_sink_calls_send(smtp_settings, monkeypatch) -> None:
    mock_send = AsyncMock(return_value=({}, "250 OK"))
    monkeypatch.setattr(aiosmtplib, "send", mock_send)

    sink = SmtpSink(settings=smtp_settings)
    await sink.send_email(
        kind=NotificationKind.incident_opened,
        incident_id=42,
        subject="[Heartbeat] Incident opened: my-api",
        body="An incident has been opened.",
        recipients=["alice@example.com", "bob@example.com"],
    )

    mock_send.assert_called_once()
    _, call_kwargs = mock_send.call_args
    assert call_kwargs["hostname"] == "smtp.example.com"
    assert call_kwargs["port"] == 587
    assert call_kwargs["username"] == "user"
    assert call_kwargs["password"] == "secret"
    assert call_kwargs["start_tls"] is True


async def test_smtp_sink_no_send_when_no_recipients(smtp_settings, monkeypatch) -> None:
    mock_send = AsyncMock()
    monkeypatch.setattr(aiosmtplib, "send", mock_send)

    sink = SmtpSink(settings=smtp_settings)
    await sink.send_email(
        kind=NotificationKind.incident_opened,
        incident_id=1,
        subject="Test",
        body="Body",
        recipients=[],
    )

    mock_send.assert_not_called()
