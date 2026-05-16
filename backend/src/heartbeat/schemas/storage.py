from datetime import datetime

from pydantic import BaseModel


class StorageStats(BaseModel):
    raw_count: int
    hourly_count: int
    daily_count: int
    raw_retention_days: int
    hourly_retention_days: int
    daily_retention_days: int | None
    last_rollup_at: datetime | None
    next_rollup_at: datetime | None
