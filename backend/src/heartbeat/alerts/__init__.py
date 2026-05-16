from typing import Protocol

from heartbeat.models.sent_notification import NotificationKind


class AlertSink(Protocol):
    async def send_email(
        self,
        kind: NotificationKind,
        incident_id: int,
        subject: str,
        body: str,
        recipients: list[str],
    ) -> None: ...


__all__ = ["AlertSink", "NotificationKind"]
