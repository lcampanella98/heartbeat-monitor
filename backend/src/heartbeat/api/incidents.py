from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from heartbeat.db import get_session
from heartbeat.schemas.incident import IncidentRead
from heartbeat.services import incident_service

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.get("", response_model=list[IncidentRead])
async def list_incidents(
    state: Literal["active", "closed", "all"] = Query(default="all"),
    endpoint_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[IncidentRead]:
    return await incident_service.list_incidents(  # type: ignore[return-value]
        session, state=state, endpoint_id=endpoint_id
    )


@router.get("/{incident_id}", response_model=IncidentRead)
async def get_incident(
    incident_id: int,
    session: AsyncSession = Depends(get_session),
) -> IncidentRead:
    incident = await incident_service.get_incident(session, incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return incident  # type: ignore[return-value]
