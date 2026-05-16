from datetime import datetime

from pydantic import BaseModel, ConfigDict

from heartbeat.models.check_result import ErrorCategory
from heartbeat.models.endpoint import StreakOutcome


class CheckResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    endpoint_id: int
    checked_at: datetime
    outcome: StreakOutcome
    latency_ms: int
    status_code: int | None
    error_category: ErrorCategory | None
    error_message: str | None
