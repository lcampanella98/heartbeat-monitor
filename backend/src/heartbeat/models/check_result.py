import enum
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from heartbeat.models.base import Base
from heartbeat.models.endpoint import StreakOutcome


class ErrorCategory(str, enum.Enum):
    timeout = "timeout"
    connection_refused = "connection_refused"
    dns = "dns"
    tls = "tls"
    non_2xx = "non_2xx"
    other = "other"


class CheckResult(Base):
    __tablename__ = "check_results"
    __table_args__ = (
        Index(
            "ix_check_results_endpoint_checked_at",
            "endpoint_id",
            sa.text("checked_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[StreakOutcome] = mapped_column(
        sa.Enum(StreakOutcome, name="streak_outcome", create_type=False), nullable=False
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_category: Mapped[ErrorCategory | None] = mapped_column(
        sa.Enum(ErrorCategory, name="error_category", create_type=False), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
