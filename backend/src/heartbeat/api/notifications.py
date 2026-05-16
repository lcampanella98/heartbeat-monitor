from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heartbeat.db import get_session
from heartbeat.models.sent_notification import SentNotification
from heartbeat.schemas.sent_notification import SentNotificationRead

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("", response_model=list[SentNotificationRead])
async def list_notifications(
    limit: int = Query(default=100, ge=1, le=1000),
    before_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[SentNotificationRead]:
    stmt = select(SentNotification).order_by(SentNotification.id.desc()).limit(limit)
    if before_id is not None:
        stmt = stmt.where(SentNotification.id < before_id)
    rows = (await session.execute(stmt)).scalars().all()
    return rows  # type: ignore[return-value]
