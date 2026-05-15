import random
from datetime import datetime
from datetime import time as dt_time

from heartbeat.checker import CheckOutcome, ErrorCategory
from heartbeat.clock import Clock
from heartbeat.models.endpoint import Endpoint

_FAILURE_CATEGORIES = [
    ErrorCategory.timeout,
    ErrorCategory.connection_refused,
    ErrorCategory.non_2xx,
]
_FAILURE_WEIGHTS = [0.4, 0.4, 0.2]


def _in_outage_window(now: datetime, windows: list[dict]) -> bool:
    current = now.time().replace(tzinfo=None)
    for w in windows:
        start = dt_time.fromisoformat(w["start"])
        end = dt_time.fromisoformat(w["end"])
        if start <= current < end:
            return True
    return False


class SimulatedChecker:
    def __init__(self, clock: Clock, rng: random.Random) -> None:
        self._clock = clock
        self._rng = rng

    async def check(self, endpoint: Endpoint) -> CheckOutcome:
        now = self._clock.now()
        latency_ms = self._rng.randint(endpoint.sim_latency_min_ms, endpoint.sim_latency_max_ms)

        if _in_outage_window(now, endpoint.sim_outage_windows):
            return CheckOutcome(
                outcome="failure",
                latency_ms=latency_ms,
                status_code=None,
                error_category=ErrorCategory.other,
                error_message="scheduled outage",
            )

        if self._rng.random() < endpoint.sim_failure_rate:
            category = self._rng.choices(_FAILURE_CATEGORIES, weights=_FAILURE_WEIGHTS, k=1)[0]
            return CheckOutcome(
                outcome="failure",
                latency_ms=latency_ms,
                status_code=None,
                error_category=category,
                error_message=f"simulated {category.value}",
            )

        return CheckOutcome(
            outcome="success",
            latency_ms=latency_ms,
            status_code=200,
            error_category=None,
            error_message=None,
        )
