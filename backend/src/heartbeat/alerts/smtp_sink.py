from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import TYPE_CHECKING

import aiosmtplib

from heartbeat.models.sent_notification import NotificationKind

if TYPE_CHECKING:
    from heartbeat.config import Settings

logger = logging.getLogger(__name__)


class SmtpSink:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send_email(
        self,
        kind: NotificationKind,
        incident_id: int,
        subject: str,
        body: str,
        recipients: list[str],
    ) -> None:
        if not recipients:
            return

        message = EmailMessage()
        message["From"] = self._settings.smtp_from
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message.set_content(body)

        try:
            await aiosmtplib.send(
                message,
                hostname=self._settings.smtp_host,
                port=self._settings.smtp_port,
                username=self._settings.smtp_username or None,
                password=self._settings.smtp_password or None,
                start_tls=self._settings.smtp_starttls,
            )
        except Exception:
            logger.warning("SMTP delivery failed for incident %d", incident_id, exc_info=True)
            raise
        logger.info("SMTP alert sent for incident %d (kind=%s)", incident_id, kind.value)
