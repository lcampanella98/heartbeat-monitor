from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    endpoint_id: int
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    frozen_timeline: list[dict[str, Any]] | None
    created_at: datetime
    # postmortem field (content, generated_at, edited_at) added in Phase 9
