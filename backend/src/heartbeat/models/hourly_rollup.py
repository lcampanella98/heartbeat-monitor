from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from heartbeat.models.base import Base


class HourlyRollup(Base):
    __tablename__ = "hourly_rollups"
    __table_args__ = (
        sa.UniqueConstraint(
            "endpoint_id", "bucket_start", name="uq_hourly_rollups_endpoint_bucket"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False
    )
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_checks: Mapped[int] = mapped_column(Integer, nullable=False)
    successful_checks: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_checks: Mapped[int] = mapped_column(Integer, nullable=False)
    uptime_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
