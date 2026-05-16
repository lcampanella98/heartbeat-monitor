from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heartbeat.db import get_session
from heartbeat.models.email_recipient import EmailRecipient
from heartbeat.schemas.email_recipient import EmailRecipientCreate, EmailRecipientRead

router = APIRouter(prefix="/api/v1/recipients", tags=["recipients"])

_USER_ID = 1  # single implicit user


@router.get("", response_model=list[EmailRecipientRead])
async def list_recipients(
    session: AsyncSession = Depends(get_session),
) -> list[EmailRecipientRead]:
    rows = (
        (
            await session.execute(
                select(EmailRecipient)
                .where(EmailRecipient.user_id == _USER_ID)
                .order_by(EmailRecipient.created_at)
            )
        )
        .scalars()
        .all()
    )
    return rows  # type: ignore[return-value]


@router.post("", response_model=EmailRecipientRead, status_code=status.HTTP_201_CREATED)
async def create_recipient(
    payload: EmailRecipientCreate,
    session: AsyncSession = Depends(get_session),
) -> EmailRecipientRead:
    existing = await session.scalar(
        select(EmailRecipient).where(
            EmailRecipient.user_id == _USER_ID,
            EmailRecipient.address == payload.address,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Address already exists")

    recipient = EmailRecipient(user_id=_USER_ID, address=payload.address)
    session.add(recipient)
    await session.commit()
    await session.refresh(recipient)
    return recipient  # type: ignore[return-value]


@router.delete("/{recipient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipient(
    recipient_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    recipient = await session.get(EmailRecipient, recipient_id)
    if recipient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipient not found")
    await session.delete(recipient)
    await session.commit()
