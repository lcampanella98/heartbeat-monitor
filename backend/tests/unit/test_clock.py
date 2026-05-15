from datetime import UTC, datetime, timedelta

from heartbeat.clock import FakeClock, RealClock


def test_real_clock_returns_utc():
    now = RealClock().now()
    assert now.tzinfo is not None
    # UTC offset should be zero
    assert now.utcoffset().total_seconds() == 0


def test_fake_clock_initial_value():
    t = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    clock = FakeClock(t)
    assert clock.now() == t


def test_fake_clock_set():
    clock = FakeClock(datetime(2025, 1, 1, tzinfo=UTC))
    t = datetime(2026, 6, 15, 9, 30, 0, tzinfo=UTC)
    clock.set(t)
    assert clock.now() == t


def test_fake_clock_advance():
    t = datetime(2025, 1, 1, tzinfo=UTC)
    clock = FakeClock(t)
    clock.advance(timedelta(hours=2, minutes=30))
    assert clock.now() == datetime(2025, 1, 1, 2, 30, tzinfo=UTC)


def test_fake_clock_advance_multiple():
    clock = FakeClock(datetime(2025, 1, 1, tzinfo=UTC))
    clock.advance(timedelta(days=1))
    clock.advance(timedelta(days=1))
    assert clock.now() == datetime(2025, 1, 3, tzinfo=UTC)


def test_fake_clock_advance_negative():
    clock = FakeClock(datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC))
    clock.advance(timedelta(hours=-1))
    assert clock.now() == datetime(2025, 6, 1, 11, 0, 0, tzinfo=UTC)
