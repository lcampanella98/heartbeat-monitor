import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from heartbeat.models.endpoint import Endpoint


class ErrorCategory(str, enum.Enum):
    timeout = "timeout"
    connection_refused = "connection_refused"
    dns = "dns"
    tls = "tls"
    non_2xx = "non_2xx"
    other = "other"


@dataclass
class CheckOutcome:
    outcome: Literal["success", "failure"]
    latency_ms: int
    status_code: int | None
    error_category: ErrorCategory | None
    error_message: str | None


class Checker(Protocol):
    async def check(self, endpoint: "Endpoint") -> CheckOutcome: ...
