"""Provider-neutral structured LLM contract."""
from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class LLMUsage(BaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)


class StructuredLLMResult(BaseModel):
    output: dict[str, Any]
    model: str
    provider: str
    usage: LLMUsage = Field(default_factory=LLMUsage)


class LLMProvider(Protocol):
    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_model: type[T],
    ) -> tuple[T, LLMUsage]: ...


class LLMProviderError(RuntimeError):
    pass
