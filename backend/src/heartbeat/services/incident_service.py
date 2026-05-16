import logging
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from heartbeat.models.check_result import CheckResult
from heartbeat.models.endpoint import Endpoint, StreakOutcome
from heartbeat.models.incident import Incident
from heartbeat.models.sent_notification import NotificationKind

logger = logging.getLogger(__name__)

N = 3  # consecutive failures to open an incident
M = 2  # consecutive successes to close an incident


async def apply_check_result(
    session: AsyncSession,
    endpoint: Endpoint,
    check_result: CheckResult,
) -> list[tuple[NotificationKind, Incident]]:
    # Returns (kind, incident) pairs to be dispatched after the caller commits;
    # dispatching post-commit ensures the dispatcher opens a fresh session to
    # a fully consistent snapshot.
    outcome = check_result.outcome
    events: list[tuple[NotificationKind, Incident]] = []

    # Update streak state in-place on the endpoint
    if outcome == endpoint.current_streak_outcome:
        endpoint.current_streak_count += 1
    else:
        endpoint.current_streak_outcome = outcome
        endpoint.current_streak_count = 1
        endpoint.streak_started_at = check_result.checked_at

    if (
        endpoint.current_streak_outcome == StreakOutcome.failure
        and endpoint.current_streak_count == N
    ):
        # Guard against crash-recovery re-entry: if the server restarted with
        # streak_count already at N and an open incident exists, do not open a second.
        open_incident = await _get_open_incident(session, endpoint.id)
        if open_incident is None:
            incident = Incident(
                endpoint_id=endpoint.id,
                started_at=endpoint.streak_started_at,
            )
            session.add(incident)
            events.append((NotificationKind.incident_opened, incident))
            logger.info("Incident opened for endpoint %d", endpoint.id)

    elif (
        endpoint.current_streak_outcome == StreakOutcome.success
        and endpoint.current_streak_count == M
    ):
        open_incident = await _get_open_incident(session, endpoint.id)
        if open_incident is not None:
            # ended_at is the timestamp of the first success in the closing streak
            ended_at = endpoint.streak_started_at
            open_incident.ended_at = ended_at
            open_incident.duration_seconds = int(
                (ended_at - open_incident.started_at).total_seconds()
            )
            # Flush before querying so the current check_result row is visible
            # within this transaction (it has been added but not yet committed).
            await session.flush()
            open_incident.frozen_timeline = await _build_frozen_timeline(
                session,
                endpoint.id,
                open_incident.started_at,
                check_result.checked_at,
            )
            events.append((NotificationKind.incident_closed, open_incident))
            logger.info("Incident %d closed for endpoint %d", open_incident.id, endpoint.id)

    return events


async def _get_open_incident(session: AsyncSession, endpoint_id: int) -> Incident | None:
    return await session.scalar(
        select(Incident).where(
            Incident.endpoint_id == endpoint_id,
            Incident.ended_at.is_(None),
        )
    )


async def _build_frozen_timeline(
    session: AsyncSession,
    endpoint_id: int,
    incident_started_at: datetime,
    current_checked_at: datetime,
) -> list[dict]:
    # Find the last success immediately before the incident opened.
    # Filtering on outcome=success matches the spec ("immediately preceding success");
    # if none exists, range_start falls back to incident_started_at so the first
    # failure row is still captured.
    preceding = await session.scalar(
        select(CheckResult)
        .where(
            CheckResult.endpoint_id == endpoint_id,
            CheckResult.checked_at < incident_started_at,
            CheckResult.outcome == StreakOutcome.success,
        )
        .order_by(desc(CheckResult.checked_at))
        .limit(1)
    )

    range_start = preceding.checked_at if preceding is not None else incident_started_at

    checks = (
        (
            await session.execute(
                select(CheckResult)
                .where(
                    CheckResult.endpoint_id == endpoint_id,
                    CheckResult.checked_at >= range_start,
                    CheckResult.checked_at <= current_checked_at,
                )
                .order_by(CheckResult.checked_at)
            )
        )
        .scalars()
        .all()
    )

    return [
        {
            "checked_at": c.checked_at.isoformat(),
            "outcome": c.outcome.value,
            "latency_ms": c.latency_ms,
            "status_code": c.status_code,
            "error_category": c.error_category.value if c.error_category else None,
            "error_message": c.error_message,
        }
        for c in checks
    ]


async def list_incidents(
    session: AsyncSession,
    state: str = "all",
    endpoint_id: int | None = None,
) -> list[Incident]:
    stmt = select(Incident).order_by(desc(Incident.started_at))
    if state == "active":
        stmt = stmt.where(Incident.ended_at.is_(None))
    elif state == "closed":
        stmt = stmt.where(Incident.ended_at.is_not(None))
    if endpoint_id is not None:
        stmt = stmt.where(Incident.endpoint_id == endpoint_id)
    return (await session.execute(stmt)).scalars().all()  # type: ignore[return-value]


async def get_incident(session: AsyncSession, incident_id: int) -> Incident | None:
    return await session.get(Incident, incident_id)
