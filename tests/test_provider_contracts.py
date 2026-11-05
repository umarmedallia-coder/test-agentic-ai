from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import DataStatus
from app.data.mock_provider import MockMarketDataProvider


@pytest.mark.asyncio
async def test_mock_provider_uses_explicit_empty_status_for_unavailable_feeds():
    provider = MockMarketDataProvider(seed=4)
    news = await provider.get_stock_news("BEL")
    actions = await provider.get_corporate_actions("BEL")
    relationships = await provider.get_company_relationships("BEL")
    assert news.status == DataStatus.EMPTY and news.payload == []
    assert actions.status == DataStatus.EMPTY and actions.payload == []
    assert relationships.status == DataStatus.EMPTY and relationships.payload == []


@pytest.mark.asyncio
async def test_mock_provider_returns_typed_timezone_aware_prices():
    provider = MockMarketDataProvider(seed=4)
    end = datetime.now(UTC)
    start = end - timedelta(days=20)
    history = await provider.get_historical_prices("BEL", start, end)
    assert history.payload
    assert history.payload[-1].timestamp.tzinfo is not None
    quote = await provider.get_stock_quote("BEL")
    assert quote.payload.price > 0


@pytest.mark.asyncio
async def test_mock_company_resolution_is_exact_not_fuzzy():
    provider = MockMarketDataProvider()
    resolved = await provider.resolve_company_entity("Bharat Electronics")
    unknown = await provider.resolve_company_entity("Bharat Electronic")
    assert resolved.payload == "BEL"
    assert unknown.status == DataStatus.EMPTY
