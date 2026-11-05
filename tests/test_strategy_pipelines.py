from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.contracts import (
    CompanyProfile, CorporateActionRecord, DataEnvelope, NewsRecord,
)
from app.data.mock_provider import MockMarketDataProvider
from app.models import AgentStatus
from app.llm.provider import LLMUsage
from app.services.news import NewsInterpretation
from app.services.strategy_pipelines import (
    run_corporate_actions_pipeline,
    run_news_pipeline,
)


class NewsProvider(MockMarketDataProvider):
    async def get_stock_news(self, symbol, since=None):
        now = datetime.now(UTC)
        record = NewsRecord(
            news_id="n1",
            headline="BEL wins major order, profit rises, upgrade approval",
            body="Bharat Electronics",
            source="exchange",
            published_at=now,
            symbols=[],
        )
        return DataEnvelope(source="test", as_of=now, payload=[record])

    async def get_company_profile(self, symbol):
        now = datetime.now(UTC)
        return DataEnvelope(
            source="test", as_of=now,
            payload=CompanyProfile(
                symbol=symbol, company_name="Bharat Electronics",
                exchange="NSE", source="test",
            ),
        )


class ActionProvider(MockMarketDataProvider):
    async def get_corporate_actions(self, symbol):
        now = datetime.now(UTC)
        record = CorporateActionRecord(
            action_id="a1", symbol=symbol, action_type="dividend",
            announcement_date=now, ex_date=now + timedelta(days=1),
            source="exchange", verified=True, cash_amount=Decimal("2"),
        )
        return DataEnvelope(source="test", as_of=now, payload=[record])


@pytest.mark.asyncio
async def test_news_pipeline_maps_company_and_uses_quote_atr():
    result, intent = await run_news_pipeline(NewsProvider(), "BEL", 100, 2)
    assert result.status == AgentStatus.SUCCEEDED
    assert intent is not None
    assert intent.symbol == "BEL"
    assert intent.entry_price == 100


@pytest.mark.asyncio
async def test_corporate_action_pipeline_blocks_near_ex_date():
    result, blocked = await run_corporate_actions_pipeline(
        ActionProvider(), "BEL", datetime.now(UTC).date(),
    )
    assert result.status == AgentStatus.SUCCEEDED
    assert blocked is True


@pytest.mark.asyncio
async def test_empty_corporate_action_feed_is_explicitly_skipped():
    result, blocked = await run_corporate_actions_pipeline(
        MockMarketDataProvider(), "BEL", datetime.now(UTC).date(),
    )
    assert result.status == AgentStatus.SKIPPED
    assert blocked is False


class FakeLLM:
    async def generate_structured(self, *, system_prompt, user_payload, output_model):
        assert "Do not invent" in system_prompt
        output = output_model(
            event_category="order_win",
            extracted_source_facts=["The article reports a major order win."],
            interpretation="Potentially positive catalyst; independently verify.",
            mentioned_entities=["Bharat Electronics"],
            horizon="short_term",
            risk_flags=["Order value and execution terms need verification"],
        )
        return output, LLMUsage(prompt_tokens=30, completion_tokens=20, total_tokens=50)


@pytest.mark.asyncio
async def test_optional_llm_interpretation_is_structured_and_separate_from_impact():
    result, intent = await run_news_pipeline(
        NewsProvider(), "BEL", 100, 2, llm_provider=FakeLLM(),
    )
    assert result.status == AgentStatus.SUCCEEDED
    assert result.findings["impact_score"] == 75
    assert result.findings["llm_interpretation"]["event_category"] == "order_win"
    assert result.findings["llm_usage"]["total_tokens"] == 50
    assert intent is not None
