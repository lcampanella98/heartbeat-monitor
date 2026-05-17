"""Unit tests for rollup math and history routing."""

from datetime import UTC, datetime, timedelta

import pytest

from heartbeat.rollup import (
    HOURLY_RETENTION_DAYS,
    RAW_RETENTION_DAYS,
    _daily_lookback,
    _hourly_lookback,
)
from heartbeat.services.history_service import resolve_range


def test_resolve_range_raw():
    duration, source = resolve_range("1h")
    assert source == "raw"
    assert duration == timedelta(hours=1)

    duration, source = resolve_range("1d")
    assert source == "raw"
    assert duration == timedelta(days=1)


def test_resolve_range_hourly():
    duration, source = resolve_range("7d")
    assert source == "hourly"
    assert duration == timedelta(days=7)


def test_resolve_range_daily():
    for key in ("30d", "90d", "1y"):
        duration, source = resolve_range(key)
        assert source == "daily", f"expected daily for {key}"


def test_resolve_range_unknown():
    with pytest.raises(ValueError, match="Unknown range key"):
        resolve_range("bad")


def test_rollup_full_lookback_wider_than_default() -> None:
    now = datetime(2025, 6, 1, tzinfo=UTC)
    assert _hourly_lookback(now, full=True) < _hourly_lookback(now, full=False)
    assert _daily_lookback(now, full=True) < _daily_lookback(now, full=False)


def test_rollup_default_lookback_matches_retention() -> None:
    now = datetime(2025, 6, 1, tzinfo=UTC)
    assert _hourly_lookback(now, full=False) == now - timedelta(days=RAW_RETENTION_DAYS)
    assert _daily_lookback(now, full=False) == now - timedelta(days=HOURLY_RETENTION_DAYS)
