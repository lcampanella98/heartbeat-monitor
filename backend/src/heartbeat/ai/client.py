from openai import AsyncOpenAI

from heartbeat.config import settings


def get_ai_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.openrouter_api_key,
    )
