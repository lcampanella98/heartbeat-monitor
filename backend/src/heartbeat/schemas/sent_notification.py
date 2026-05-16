from datetime import datetime

from pydantic import BaseModel

from heartbeat.models.sent_notification import NotificationKind


class SentNotificationRead(BaseModel):
    id: int
    kind: NotificationKind
    incident_id: int
    subject: str
    body: str
    recipients: list[str]
    sent_at: datetime

    model_config = {"from_attributes": True}
