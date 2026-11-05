"""Read-only market data provider protocol and explicit error type."""
from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from app.contracts import DataEnvelope, OHLCVBar, Quote


class MarketDataError(RuntimeError):
    pass


class MarketDataProvider(Protocol):
    async def get_stock_quote(self, symbol: str, exchange: str = "NSE") -> DataEnvelope[Quote]: ...
    async def get_historical_prices(
        self, symbol: str, start: datetime, end: datetime, exchange: str = "NSE"
    ) -> DataEnvelope[list[OHLCVBar]]: ...
    async def get_market_indices(self) -> DataEnvelope[dict[str, float]]: ...
    async def get_trading_calendar(self, day: date) -> DataEnvelope[dict[str, bool]]: ...
    async def get_stock_universe(self, exchange: str = "NSE") -> DataEnvelope[list[str]]: ...
    async def validate_stock_symbol(self, symbol: str, exchange: str = "NSE") -> DataEnvelope[bool]: ...
