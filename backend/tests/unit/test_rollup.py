"""Unit tests for rollup math and history routing."""

from datetime import timedelta

import pytest

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
