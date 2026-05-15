from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heartbeat.clock import Clock
from heartbeat.models.endpoint import Endpoint
from heartbeat.schemas.endpoint import EndpointCreate, EndpointUpdate

_USER_ID = 1


async def list_endpoints(session: AsyncSession) -> list[Endpoint]:
    result = await session.execute(select(Endpoint).where(Endpoint.user_id == _USER_ID))
    return list(result.scalars().all())


async def get_endpoint(session: AsyncSession, endpoint_id: int) -> Endpoint | None:
    result = await session.execute(
        select(Endpoint).where(Endpoint.id == endpoint_id, Endpoint.user_id == _USER_ID)
    )
    return result.scalar_one_or_none()


async def create_endpoint(session: AsyncSession, data: EndpointCreate, clock: Clock) -> Endpoint:
    endpoint = Endpoint(
        user_id=_USER_ID,
        name=data.name,
        url=data.url,
        enabled=data.enabled,
        check_interval_seconds=data.check_interval_seconds,
        timeout_seconds=data.timeout_seconds,
        next_due_at=clock.now(),
        sim_failure_rate=data.sim_failure_rate,
        sim_latency_min_ms=data.sim_latency_min_ms,
        sim_latency_max_ms=data.sim_latency_max_ms,
        sim_outage_windows=[w.model_dump() for w in data.sim_outage_windows],
    )
    session.add(endpoint)
    await session.commit()
    await session.refresh(endpoint)
    return endpoint


async def update_endpoint(
    session: AsyncSession, endpoint_id: int, data: EndpointUpdate
) -> Endpoint | None:
    endpoint = await get_endpoint(session, endpoint_id)
    if endpoint is None:
        return None

    update_data = data.model_dump(exclude_unset=True)
    if "sim_outage_windows" in update_data:
        # null and [] are both treated as "clear all outage windows"
        windows = data.sim_outage_windows or []
        update_data["sim_outage_windows"] = [w.model_dump() for w in windows]

    for key, value in update_data.items():
        setattr(endpoint, key, value)

    await session.commit()
    await session.refresh(endpoint)
    return endpoint


async def delete_endpoint(session: AsyncSession, endpoint_id: int) -> bool:
    endpoint = await get_endpoint(session, endpoint_id)
    if endpoint is None:
        return False
    await session.delete(endpoint)
    await session.commit()
    return True


async def enable_endpoint(session: AsyncSession, endpoint_id: int) -> Endpoint | None:
    endpoint = await get_endpoint(session, endpoint_id)
    if endpoint is None:
        return None
    # next_due_at is preserved intentionally: if it is in the past the scheduler picks the
    # endpoint up on the next tick; if it is in the future it remains scheduled as-is.
    endpoint.enabled = True
    await session.commit()
    await session.refresh(endpoint)
    return endpoint


async def disable_endpoint(session: AsyncSession, endpoint_id: int) -> Endpoint | None:
    endpoint = await get_endpoint(session, endpoint_id)
    if endpoint is None:
        return None
    endpoint.enabled = False
    await session.commit()
    await session.refresh(endpoint)
    return endpoint
