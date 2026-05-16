from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class HistoryBinRead(BaseModel):
    bucket_start: datetime
    source: Literal["raw", "hourly", "daily"]
    total_checks: int
    successful_checks: int
    failed_checks: int
    uptime_pct: float


class UptimeRead(BaseModel):
    h24: float
    d7: float
    d30: float
