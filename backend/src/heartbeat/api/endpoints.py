from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from heartbeat.clock import Clock
from heartbeat.db import get_session
from heartbeat.dependencies import get_clock
from heartbeat.schemas.endpoint import EndpointCreate, EndpointRead, EndpointUpdate
from heartbeat.services import endpoint_service

router = APIRouter(prefix="/api/v1/endpoints", tags=["endpoints"])


@router.get("", response_model=list[EndpointRead])
async def list_endpoints(session: AsyncSession = Depends(get_session)) -> list[EndpointRead]:
    return await endpoint_service.list_endpoints(session)  # type: ignore[return-value]


@router.post("", response_model=EndpointRead, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    data: EndpointCreate,
    session: AsyncSession = Depends(get_session),
    clock: Clock = Depends(get_clock),
) -> EndpointRead:
    return await endpoint_service.create_endpoint(session, data, clock)  # type: ignore[return-value]


@router.get("/{endpoint_id}", response_model=EndpointRead)
async def get_endpoint(
    endpoint_id: int, session: AsyncSession = Depends(get_session)
) -> EndpointRead:
    ep = await endpoint_service.get_endpoint(session, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")
    return ep  # type: ignore[return-value]


@router.put("/{endpoint_id}", response_model=EndpointRead)
async def update_endpoint(
    endpoint_id: int,
    data: EndpointUpdate,
    session: AsyncSession = Depends(get_session),
) -> EndpointRead:
    ep = await endpoint_service.update_endpoint(session, endpoint_id, data)
    if ep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")
    return ep  # type: ignore[return-value]


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(endpoint_id: int, session: AsyncSession = Depends(get_session)) -> None:
    deleted = await endpoint_service.delete_endpoint(session, endpoint_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")


@router.post("/{endpoint_id}/enable", response_model=EndpointRead)
async def enable_endpoint(
    endpoint_id: int, session: AsyncSession = Depends(get_session)
) -> EndpointRead:
    ep = await endpoint_service.enable_endpoint(session, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")
    return ep  # type: ignore[return-value]


@router.post("/{endpoint_id}/disable", response_model=EndpointRead)
async def disable_endpoint(
    endpoint_id: int, session: AsyncSession = Depends(get_session)
) -> EndpointRead:
    ep = await endpoint_service.disable_endpoint(session, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")
    return ep  # type: ignore[return-value]
