from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    def __init__(self, initial: datetime | None = None) -> None:
        self._now = initial if initial is not None else datetime.now(UTC)

    def now(self) -> datetime:
        return self._now

    def set(self, t: datetime) -> None:
        self._now = t

    def advance(self, delta: timedelta) -> None:
        self._now += delta
