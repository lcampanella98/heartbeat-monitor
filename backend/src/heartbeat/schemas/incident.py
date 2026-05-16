from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PostmortemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content: str | None
    generated_at: datetime | None
    edited_at: datetime | None


class PostmortemUpdate(BaseModel):
    content: str


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    endpoint_id: int
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    frozen_timeline: list[dict[str, Any]] | None
    created_at: datetime
    postmortem: PostmortemRead | None = None
