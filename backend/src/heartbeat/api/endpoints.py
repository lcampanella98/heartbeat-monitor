from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from heartbeat.clock import Clock
from heartbeat.db import get_session
from heartbeat.dependencies import get_clock
from heartbeat.schemas.check_result import CheckResultRead
from heartbeat.schemas.endpoint import EndpointCreate, EndpointRead, EndpointUpdate
from heartbeat.schemas.history import HistoryBinRead, UptimeRead
from heartbeat.services import (
    check_result_service,
    endpoint_service,
    history_service,
    uptime_service,
)

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


@router.get("/{endpoint_id}/recent-checks", response_model=list[CheckResultRead])
async def get_recent_checks(
    endpoint_id: int,
    limit: int = Query(default=60, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[CheckResultRead]:
    ep = await endpoint_service.get_endpoint(session, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")
    return await check_result_service.get_recent_checks(session, endpoint_id, limit)  # type: ignore[return-value]


@router.get("/{endpoint_id}/history", response_model=list[HistoryBinRead])
async def get_history(
    endpoint_id: int,
    range: Literal["1h", "1d", "7d", "30d", "90d", "1y"] = Query(default="1d"),
    session: AsyncSession = Depends(get_session),
    clock: Clock = Depends(get_clock),
) -> list[HistoryBinRead]:
    ep = await endpoint_service.get_endpoint(session, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")
    bins = await history_service.get_history(session, endpoint_id, range, clock.now())
    return [
        HistoryBinRead(
            bucket_start=b.bucket_start,
            source=b.source,
            total_checks=b.total_checks,
            successful_checks=b.successful_checks,
            failed_checks=b.failed_checks,
            uptime_pct=b.uptime_pct,
        )
        for b in bins
    ]


@router.get("/{endpoint_id}/uptime", response_model=UptimeRead)
async def get_uptime(
    endpoint_id: int,
    session: AsyncSession = Depends(get_session),
    clock: Clock = Depends(get_clock),
) -> UptimeRead:
    ep = await endpoint_service.get_endpoint(session, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")
    result = await uptime_service.get_uptime(session, endpoint_id, clock.now())
    return UptimeRead(**result)
