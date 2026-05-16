import enum
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from heartbeat.models.base import Base


class NotificationKind(str, enum.Enum):
    incident_opened = "incident_opened"
    incident_closed = "incident_closed"


class SentNotification(Base):
    __tablename__ = "sent_notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[NotificationKind] = mapped_column(
        sa.Enum(NotificationKind, name="notification_kind"), nullable=False
    )
    incident_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    subject: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    recipients: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
