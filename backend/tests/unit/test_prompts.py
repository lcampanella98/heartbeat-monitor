"""Unit tests for AI prompt rendering — Phase 9."""

from datetime import UTC, datetime

from heartbeat.ai.prompts import render_incident_prompt

_STARTED_AT = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
_ENDED_AT = datetime(2025, 1, 15, 10, 5, 0, tzinfo=UTC)
_TIMELINE = [
    {
        "checked_at": "2025-01-15T09:59:00+00:00",
        "outcome": "success",
        "latency_ms": 120,
        "status_code": 200,
        "error_category": None,
        "error_message": None,
    },
    {
        "checked_at": "2025-01-15T10:00:00+00:00",
        "outcome": "failure",
        "latency_ms": 10005,
        "status_code": None,
        "error_category": "timeout",
        "error_message": "request timed out",
    },
    {
        "checked_at": "2025-01-15T10:05:00+00:00",
        "outcome": "success",
        "latency_ms": 115,
        "status_code": 200,
        "error_category": None,
        "error_message": None,
    },
]

_EXPECTED = """\
Endpoint: Example API
URL: https://example.com/health
Incident started: 2025-01-15T10:00:00+00:00
Incident ended: 2025-01-15T10:05:00+00:00
Duration: 300s

Check timeline:
Timestamp                    Outcome   Latency  Status  Error
----------------------------------------------------------------------
2025-01-15T09:59:00+00:00    success     120ms     200
2025-01-15T10:00:00+00:00    failure   10005ms       -  timeout: request timed out
2025-01-15T10:05:00+00:00    success     115ms     200"""


def test_render_incident_prompt_snapshot() -> None:
    result = render_incident_prompt(
        endpoint_name="Example API",
        endpoint_url="https://example.com/health",
        started_at=_STARTED_AT,
        ended_at=_ENDED_AT,
        duration_seconds=300,
        frozen_timeline=_TIMELINE,
    )
    assert result == _EXPECTED


def test_render_open_incident() -> None:
    result = render_incident_prompt(
        endpoint_name="My Service",
        endpoint_url="https://service.example.com",
        started_at=_STARTED_AT,
        ended_at=None,
        duration_seconds=None,
        frozen_timeline=[],
    )
    assert "Incident status: open" in result
    assert "Incident ended" not in result
    assert "Duration" not in result


def test_render_empty_timeline() -> None:
    result = render_incident_prompt(
        endpoint_name="X",
        endpoint_url="https://x.example.com",
        started_at=_STARTED_AT,
        ended_at=None,
        duration_seconds=None,
        frozen_timeline=[],
    )
    lines = result.splitlines()
    # After the separator there should be no data rows
    sep_idx = next(i for i, line in enumerate(lines) if line.startswith("---"))
    assert sep_idx == len(lines) - 1
