from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import BigInteger, Date, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from heartbeat.models.base import Base


class DailyRollup(Base):
    __tablename__ = "daily_rollups"
    __table_args__ = (
        sa.UniqueConstraint("endpoint_id", "bucket_date", name="uq_daily_rollups_endpoint_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False
    )
    bucket_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_checks: Mapped[int] = mapped_column(Integer, nullable=False)
    successful_checks: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_checks: Mapped[int] = mapped_column(Integer, nullable=False)
    uptime_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
