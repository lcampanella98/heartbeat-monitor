import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from heartbeat.alerts import AlertSink
from heartbeat.models.email_recipient import EmailRecipient
from heartbeat.models.endpoint import Endpoint
from heartbeat.models.incident import Incident
from heartbeat.models.sent_notification import NotificationKind

logger = logging.getLogger(__name__)


def _build_message(
    kind: NotificationKind, incident: Incident, endpoint: Endpoint
) -> tuple[str, str]:
    name = endpoint.name
    url = endpoint.url
    started = incident.started_at.isoformat()

    if kind == NotificationKind.incident_opened:
        subject = f"[Heartbeat] Incident opened: {name}"
        body = (
            f"An incident has been opened for endpoint '{name}'.\n\n"
            f"URL: {url}\n"
            f"Started at: {started}\n"
            f"Incident details: /incidents/{incident.id}\n"
        )
    elif kind == NotificationKind.incident_closed:
        ended = incident.ended_at.isoformat() if incident.ended_at else "unknown"
        duration = (
            f"{incident.duration_seconds}s" if incident.duration_seconds is not None else "unknown"
        )
        subject = f"[Heartbeat] Incident closed: {name}"
        body = (
            f"The incident for endpoint '{name}' has been closed.\n\n"
            f"URL: {url}\n"
            f"Started at: {started}\n"
            f"Ended at: {ended}\n"
            f"Duration: {duration}\n"
            f"Incident details: /incidents/{incident.id}\n"
        )
    else:
        raise ValueError(f"Unknown notification kind: {kind}")

    return subject, body


class AlertDispatcher:
    def __init__(self, session_factory: async_sessionmaker, sink: AlertSink) -> None:
        self._session_factory = session_factory
        self._sink = sink

    async def dispatch(self, kind: NotificationKind, incident_id: int) -> None:
        try:
            async with self._session_factory() as session:
                incident = await session.get(Incident, incident_id)
                if incident is None:
                    logger.warning("Dispatch called for unknown incident %d", incident_id)
                    return
                endpoint = await session.get(Endpoint, incident.endpoint_id)
                if endpoint is None:
                    logger.warning("Dispatch: endpoint not found for incident %d", incident_id)
                    return

                recipients_rows = (
                    (
                        await session.execute(
                            select(EmailRecipient)
                            .where(EmailRecipient.user_id == 1)
                            .order_by(EmailRecipient.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                recipients = [r.address for r in recipients_rows]
                subject, body = _build_message(kind, incident, endpoint)

            await self._sink.send_email(kind, incident_id, subject, body, recipients)
        except Exception:
            logger.exception("Alert dispatch failed for incident %d", incident_id)
