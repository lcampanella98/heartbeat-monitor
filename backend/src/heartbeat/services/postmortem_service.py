import logging
from datetime import UTC, datetime

from openai import APIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from heartbeat.ai import client as ai_client
from heartbeat.ai.prompts import SYSTEM_PROMPT, render_incident_prompt
from heartbeat.config import settings
from heartbeat.models.endpoint import Endpoint
from heartbeat.models.incident import Incident, Postmortem

logger = logging.getLogger(__name__)


class PostmortemAPIKeyMissing(Exception):
    pass


class PostmortemUpstreamError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


async def generate(session: AsyncSession, incident_id: int) -> Postmortem | None:
    if not settings.openrouter_api_key:
        raise PostmortemAPIKeyMissing("OPENROUTER_API_KEY is not configured")

    incident = await session.scalar(
        select(Incident)
        .options(selectinload(Incident.postmortem))
        .where(Incident.id == incident_id)
    )
    if incident is None:
        return None

    endpoint = await session.get(Endpoint, incident.endpoint_id)
    if endpoint is None:
        return None

    prompt = render_incident_prompt(
        endpoint_name=endpoint.name,
        endpoint_url=endpoint.url,
        started_at=incident.started_at,
        ended_at=incident.ended_at,
        duration_seconds=incident.duration_seconds,
        frozen_timeline=incident.frozen_timeline or [],
    )

    try:
        client = ai_client.get_ai_client()
        response = await client.chat.completions.create(
            model=settings.openrouter_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=800,
        )
        content = response.choices[0].message.content or ""
    except APIError as exc:
        raise PostmortemUpstreamError(str(exc)[:200]) from exc

    now = datetime.now(UTC)
    if incident.postmortem is None:
        postmortem = Postmortem(
            incident_id=incident_id,
            content=content,
            generated_at=now,
            edited_at=None,
        )
        session.add(postmortem)
        incident.postmortem = postmortem
    else:
        incident.postmortem.content = content
        incident.postmortem.generated_at = now
        incident.postmortem.edited_at = None

    await session.commit()
    await session.refresh(incident.postmortem)
    return incident.postmortem


async def update(session: AsyncSession, incident_id: int, content: str) -> Postmortem | None:
    incident = await session.scalar(
        select(Incident)
        .options(selectinload(Incident.postmortem))
        .where(Incident.id == incident_id)
    )
    if incident is None:
        return None

    now = datetime.now(UTC)
    if incident.postmortem is None:
        postmortem = Postmortem(
            incident_id=incident_id,
            content=content,
            generated_at=None,
            edited_at=now,
        )
        session.add(postmortem)
        incident.postmortem = postmortem
    else:
        incident.postmortem.content = content
        incident.postmortem.edited_at = now

    await session.commit()
    await session.refresh(incident.postmortem)
    return incident.postmortem
