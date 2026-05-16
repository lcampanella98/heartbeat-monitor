import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from heartbeat.models.sent_notification import NotificationKind, SentNotification

logger = logging.getLogger(__name__)

_RING_BUFFER_SIZE = 1000


class LogSink:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        ring_buffer_size: int = _RING_BUFFER_SIZE,
    ) -> None:
        self._session_factory = session_factory
        self._ring_buffer_size = ring_buffer_size

    async def send_email(
        self,
        kind: NotificationKind,
        incident_id: int,
        subject: str,
        body: str,
        recipients: list[str],
    ) -> None:
        async with self._session_factory() as session:
            notification = SentNotification(
                kind=kind,
                incident_id=incident_id,
                subject=subject,
                body=body,
                recipients=recipients,
            )
            session.add(notification)
            await session.flush()

            # Ring buffer: keep only ring_buffer_size rows.
            # The subquery returns the id of the ring_buffer_size-th-newest row.
            # If <= ring_buffer_size rows exist the subquery returns NULL and no
            # rows are deleted (NULL comparisons are always false in SQL).
            cutoff_subq = (
                select(SentNotification.id)
                .order_by(SentNotification.id.desc())
                .offset(self._ring_buffer_size - 1)
                .limit(1)
                .scalar_subquery()
            )
            await session.execute(delete(SentNotification).where(SentNotification.id < cutoff_subq))
            await session.commit()
        logger.debug("Notification captured for incident %d (kind=%s)", incident_id, kind.value)
