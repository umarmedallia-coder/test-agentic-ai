from pydantic import BaseModel

import pytest

from app.config import Settings
from app.llm.factory import build_llm_provider
from app.llm.openai_compatible import OpenAICompatibleProvider


class Interpretation(BaseModel):
    impact: str
    confidence: float


def test_llm_provider_is_disabled_by_default():
    assert build_llm_provider(Settings()) is None


@pytest.mark.asyncio
async def test_ollama_adapter_validates_structured_response(monkeypatch):
    provider = OpenAICompatibleProvider(
        provider="ollama", base_url="http://localhost:11434",
        model="qwen3:4b",
    )
    monkeypatch.setattr(
        provider, "_post_json",
        lambda path, body: {
            "message": {"content": '{"impact":"positive","confidence":0.8}'},
            "prompt_eval_count": 12,
            "eval_count": 8,
        },
    )
    output, usage = await provider.generate_structured(
        system_prompt="Classify facts only.",
        user_payload={"headline": "Company wins contract"},
        output_model=Interpretation,
    )
    assert output.impact == "positive"
    assert usage.total_tokens == 20


@pytest.mark.asyncio
async def test_openrouter_requires_api_key_without_leaking_it():
    provider = OpenAICompatibleProvider(
        provider="openrouter", base_url="https://openrouter.ai/api/v1",
        model="example/model",
    )
    with pytest.raises(Exception, match="API key is not configured"):
        await provider.generate_structured(
            system_prompt="Classify facts.",
            user_payload={"headline": "example"},
            output_model=Interpretation,
        )
