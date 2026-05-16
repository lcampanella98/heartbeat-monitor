from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from heartbeat.models.check_result import ErrorCategory

if TYPE_CHECKING:
    from heartbeat.models.endpoint import Endpoint


@dataclass
class CheckOutcome:
    outcome: Literal["success", "failure"]
    latency_ms: int
    status_code: int | None
    error_category: ErrorCategory | None
    error_message: str | None


class Checker(Protocol):
    async def check(self, endpoint: "Endpoint") -> CheckOutcome: ...
