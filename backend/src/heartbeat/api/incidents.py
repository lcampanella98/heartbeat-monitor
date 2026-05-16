from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from heartbeat.db import get_session
from heartbeat.schemas.incident import IncidentRead, PostmortemRead, PostmortemUpdate
from heartbeat.services import incident_service, postmortem_service
from heartbeat.services.postmortem_service import PostmortemAPIKeyMissing, PostmortemUpstreamError

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


@router.post("/{incident_id}/postmortem/generate", response_model=PostmortemRead)
async def generate_postmortem(
    incident_id: int,
    session: AsyncSession = Depends(get_session),
) -> PostmortemRead:
    try:
        result = await postmortem_service.generate(session, incident_id)
    except PostmortemAPIKeyMissing as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except PostmortemUpstreamError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.detail) from exc

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return result  # type: ignore[return-value]


@router.put("/{incident_id}/postmortem", response_model=PostmortemRead)
async def update_postmortem(
    incident_id: int,
    body: PostmortemUpdate,
    session: AsyncSession = Depends(get_session),
) -> PostmortemRead:
    result = await postmortem_service.update(session, incident_id, body.content)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return result  # type: ignore[return-value]
