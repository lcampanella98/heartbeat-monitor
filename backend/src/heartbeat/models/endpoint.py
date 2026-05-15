import enum
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from heartbeat.models.base import Base


class StreakOutcome(str, enum.Enum):
    success = "success"
    failure = "failure"


class Endpoint(Base):
    __tablename__ = "endpoints"
    __table_args__ = (
        Index("ix_endpoints_user_id", "user_id"),
        Index(
            "ix_endpoints_next_due_at_enabled",
            "next_due_at",
            postgresql_where=sa.text("enabled = true"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    check_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_streak_outcome: Mapped[StreakOutcome | None] = mapped_column(
        sa.Enum(StreakOutcome, name="streak_outcome"), nullable=True
    )
    current_streak_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    streak_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sim_failure_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sim_latency_min_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    sim_latency_max_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    sim_outage_windows: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
