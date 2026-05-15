from datetime import datetime
from datetime import time as dt_time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from heartbeat.models.endpoint import StreakOutcome


class SimOutageWindow(BaseModel):
    start: str  # "HH:MM" UTC
    end: str  # "HH:MM" UTC

    @model_validator(mode="after")
    def start_must_be_before_end(self) -> "SimOutageWindow":
        try:
            start_t = dt_time.fromisoformat(self.start)
            end_t = dt_time.fromisoformat(self.end)
        except ValueError as exc:
            raise ValueError("outage window start/end must be in HH:MM format") from exc
        if start_t >= end_t:
            raise ValueError(
                "outage window start must be before end"
                " (midnight-spanning windows are not supported)"
            )
        return self


class EndpointCreate(BaseModel):
    name: str
    url: str
    check_interval_seconds: Literal[30, 60, 300, 900]
    timeout_seconds: Annotated[int, Field(ge=1, le=60)] = 10
    enabled: bool = True
    sim_failure_rate: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    sim_latency_min_ms: Annotated[int, Field(ge=0)] = 100
    sim_latency_max_ms: Annotated[int, Field(ge=0)] = 500
    sim_outage_windows: list[SimOutageWindow] = []

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v

    @field_validator("url")
    @classmethod
    def url_must_be_http_or_https(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("url must start with http:// or https://")
        return v

    @model_validator(mode="after")
    def validate_latency_range(self) -> "EndpointCreate":
        if self.sim_latency_min_ms > self.sim_latency_max_ms:
            raise ValueError("sim_latency_min_ms must be <= sim_latency_max_ms")
        return self


class EndpointUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    check_interval_seconds: Literal[30, 60, 300, 900] | None = None
    timeout_seconds: Annotated[int, Field(ge=1, le=60)] | None = None
    enabled: bool | None = None
    sim_failure_rate: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    sim_latency_min_ms: Annotated[int, Field(ge=0)] | None = None
    sim_latency_max_ms: Annotated[int, Field(ge=0)] | None = None
    sim_outage_windows: list[SimOutageWindow] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def name_must_not_be_empty(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            raise ValueError("name must not be empty")
        return v

    @field_validator("url", mode="before")
    @classmethod
    def url_must_be_http_or_https(cls, v: object) -> object:
        if isinstance(v, str) and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("url must start with http:// or https://")
        return v

    @model_validator(mode="after")
    def validate_latency_range(self) -> "EndpointUpdate":
        if (
            self.sim_latency_min_ms is not None
            and self.sim_latency_max_ms is not None
            and self.sim_latency_min_ms > self.sim_latency_max_ms
        ):
            raise ValueError("sim_latency_min_ms must be <= sim_latency_max_ms")
        return self


class EndpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    url: str
    enabled: bool
    check_interval_seconds: int
    timeout_seconds: int
    next_due_at: datetime | None
    current_streak_outcome: StreakOutcome | None
    current_streak_count: int
    streak_started_at: datetime | None
    sim_failure_rate: float
    sim_latency_min_ms: int
    sim_latency_max_ms: int
    sim_outage_windows: list[SimOutageWindow]
    created_at: datetime
    updated_at: datetime
