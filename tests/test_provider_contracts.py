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
    assert news.is_mock is True
    assert actions.status == DataStatus.EMPTY and actions.payload == []
    assert relationships.status == DataStatus.EMPTY and relationships.payload == []


@pytest.mark.asyncio
async def test_mock_provider_returns_typed_timezone_aware_prices():
    provider = MockMarketDataProvider(seed=4)
    end = datetime.now(UTC)
    start = end - timedelta(days=20)
    history = await provider.get_historical_prices("BEL", start, end)
    assert history.payload
    assert history.is_mock is True
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


def test_trading_engine_accepts_an_injected_market_data_provider(tmp_path):
    from app.config import Settings
    from app.services.engine import TradingEngine

    provider = MockMarketDataProvider(seed=99)
    engine = TradingEngine(Settings(journal_dir=tmp_path), provider=provider)
    assert engine.provider is provider


def test_trading_engine_defaults_to_mock_provider(tmp_path):
    from app.config import Settings
    from app.services.engine import TradingEngine

    engine = TradingEngine(Settings(journal_dir=tmp_path))
    assert isinstance(engine.provider, MockMarketDataProvider)
