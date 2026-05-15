import random
from datetime import UTC, datetime

from heartbeat.checker import ErrorCategory
from heartbeat.checker.simulated import SimulatedChecker, _in_outage_window
from heartbeat.clock import FakeClock

_NOON = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


class _FakeEndpoint:
    def __init__(
        self,
        failure_rate: float = 0.0,
        latency_min: int = 100,
        latency_max: int = 200,
        outage_windows: list[dict] | None = None,
    ) -> None:
        self.sim_failure_rate = failure_rate
        self.sim_latency_min_ms = latency_min
        self.sim_latency_max_ms = latency_max
        self.sim_outage_windows = outage_windows or []


def _checker(now: datetime = _NOON, seed: int = 42) -> SimulatedChecker:
    return SimulatedChecker(clock=FakeClock(now), rng=random.Random(seed))


async def test_always_success_with_zero_failure_rate():
    checker = _checker()
    endpoint = _FakeEndpoint(failure_rate=0.0)
    outcome = await checker.check(endpoint)
    assert outcome.outcome == "success"
    assert outcome.error_category is None


async def test_always_failure_with_full_failure_rate():
    checker = _checker()
    endpoint = _FakeEndpoint(failure_rate=1.0)
    for _ in range(10):
        outcome = await checker.check(endpoint)
        assert outcome.outcome == "failure"
        assert outcome.error_category in (
            ErrorCategory.timeout,
            ErrorCategory.connection_refused,
            ErrorCategory.non_2xx,
        )


async def test_outage_window_hit_overrides_success():
    # Clock at 14:15 UTC, window 14:00-14:30 → always fail
    checker = SimulatedChecker(
        clock=FakeClock(datetime(2024, 1, 1, 14, 15, 0, tzinfo=UTC)),
        rng=random.Random(0),
    )
    endpoint = _FakeEndpoint(failure_rate=0.0, outage_windows=[{"start": "14:00", "end": "14:30"}])
    outcome = await checker.check(endpoint)
    assert outcome.outcome == "failure"
    assert outcome.error_category == ErrorCategory.other
    assert outcome.error_message == "scheduled outage"


async def test_outage_window_miss_allows_success():
    # Clock at 15:00 UTC, outside window 14:00-14:30
    checker = SimulatedChecker(
        clock=FakeClock(datetime(2024, 1, 1, 15, 0, 0, tzinfo=UTC)),
        rng=random.Random(0),
    )
    endpoint = _FakeEndpoint(failure_rate=0.0, outage_windows=[{"start": "14:00", "end": "14:30"}])
    outcome = await checker.check(endpoint)
    assert outcome.outcome == "success"


async def test_outage_window_boundary_start_is_inclusive():
    checker = SimulatedChecker(
        clock=FakeClock(datetime(2024, 1, 1, 14, 0, 0, tzinfo=UTC)),
        rng=random.Random(0),
    )
    endpoint = _FakeEndpoint(failure_rate=0.0, outage_windows=[{"start": "14:00", "end": "14:30"}])
    outcome = await checker.check(endpoint)
    assert outcome.outcome == "failure"
    assert outcome.error_message == "scheduled outage"


async def test_outage_window_boundary_end_is_exclusive():
    checker = SimulatedChecker(
        clock=FakeClock(datetime(2024, 1, 1, 14, 30, 0, tzinfo=UTC)),
        rng=random.Random(0),
    )
    endpoint = _FakeEndpoint(failure_rate=0.0, outage_windows=[{"start": "14:00", "end": "14:30"}])
    outcome = await checker.check(endpoint)
    assert outcome.outcome == "success"


async def test_latency_within_configured_bounds():
    checker = _checker()
    endpoint = _FakeEndpoint(failure_rate=0.0, latency_min=50, latency_max=150)
    for _ in range(20):
        outcome = await checker.check(endpoint)
        assert 50 <= outcome.latency_ms <= 150


async def test_latency_exact_bounds_when_equal():
    checker = _checker()
    endpoint = _FakeEndpoint(failure_rate=0.0, latency_min=123, latency_max=123)
    outcome = await checker.check(endpoint)
    assert outcome.latency_ms == 123


async def test_deterministic_with_same_seed():
    r1 = SimulatedChecker(clock=FakeClock(_NOON), rng=random.Random(7))
    r2 = SimulatedChecker(clock=FakeClock(_NOON), rng=random.Random(7))
    ep = _FakeEndpoint(failure_rate=0.5)
    o1 = await r1.check(ep)
    o2 = await r2.check(ep)
    assert o1.outcome == o2.outcome
    assert o1.latency_ms == o2.latency_ms
    assert o1.error_category == o2.error_category


async def test_success_has_status_200():
    checker = _checker()
    outcome = await checker.check(_FakeEndpoint(failure_rate=0.0))
    assert outcome.status_code == 200


async def test_failure_has_no_status_code():
    checker = _checker()
    outcome = await checker.check(_FakeEndpoint(failure_rate=1.0))
    assert outcome.status_code is None


def test_in_outage_window_unit():
    now = datetime(2024, 1, 1, 14, 15, 0, tzinfo=UTC)
    assert _in_outage_window(now, [{"start": "14:00", "end": "14:30"}]) is True
    assert _in_outage_window(now, [{"start": "10:00", "end": "11:00"}]) is False
    assert _in_outage_window(now, []) is False
