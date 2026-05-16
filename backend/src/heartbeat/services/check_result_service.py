from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from heartbeat.models.check_result import CheckResult


async def get_recent_checks(
    session: AsyncSession, endpoint_id: int, limit: int
) -> list[CheckResult]:
    result = await session.execute(
        select(CheckResult)
        .where(CheckResult.endpoint_id == endpoint_id)
        .order_by(desc(CheckResult.checked_at))
        .limit(limit)
    )
    return list(result.scalars().all())
