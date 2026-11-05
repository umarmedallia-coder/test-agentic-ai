"""Construct optional LLM providers from validated settings."""
from app.config import Settings
from app.llm.openai_compatible import OpenAICompatibleProvider


def build_llm_provider(settings: Settings) -> OpenAICompatibleProvider | None:
    if settings.llm_provider == "disabled":
        return None
    return OpenAICompatibleProvider(
        provider=settings.llm_provider,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=(
            settings.llm_api_key.get_secret_value()
            if settings.llm_api_key is not None else None
        ),
        timeout_seconds=settings.llm_timeout_seconds,
        max_concurrency=settings.max_llm_concurrency,
    )
