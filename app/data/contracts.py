"""Read-only provider protocol for all source-of-truth market and company data."""
from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from app.agents.contracts import FundamentalSnapshot, InstitutionalSnapshot
from app.contracts import (
    CompanyAnnouncement,
    CompanyProfile,
    CorporateActionRecord,
    DataEnvelope,
    NewsRecord,
    OHLCVBar,
    Quote,
    RelationshipEdge,
)


class MarketDataError(RuntimeError):
    pass


class MarketDataProvider(Protocol):
    async def get_stock_quote(
        self, symbol: str, exchange: str = "NSE"
    ) -> DataEnvelope[Quote]: ...

    async def get_historical_prices(
        self, symbol: str, start: datetime, end: datetime, exchange: str = "NSE"
    ) -> DataEnvelope[list[OHLCVBar]]: ...

    async def get_market_indices(self) -> DataEnvelope[dict[str, float]]: ...

    async def get_trading_calendar(
        self, day: date
    ) -> DataEnvelope[dict[str, bool]]: ...

    async def get_stock_universe(
        self, exchange: str = "NSE"
    ) -> DataEnvelope[list[str]]: ...

    async def validate_stock_symbol(
        self, symbol: str, exchange: str = "NSE"
    ) -> DataEnvelope[bool]: ...

    async def get_stock_news(
        self, symbol: str, since: datetime | None = None
    ) -> DataEnvelope[list[NewsRecord]]: ...

    async def get_news_details(self, news_id: str) -> DataEnvelope[NewsRecord]: ...

    async def get_company_announcements(
        self, symbol: str
    ) -> DataEnvelope[list[CompanyAnnouncement]]: ...

    async def get_corporate_actions(
        self, symbol: str
    ) -> DataEnvelope[list[CorporateActionRecord]]: ...

    async def resolve_company_entity(
        self, query: str
    ) -> DataEnvelope[str | None]: ...

    async def get_company_profile(self, symbol: str) -> DataEnvelope[CompanyProfile]: ...

    async def get_company_relationships(
        self, symbol: str
    ) -> DataEnvelope[list[RelationshipEdge]]: ...

    async def get_fundamental_snapshot(
        self, symbol: str, exchange: str = "NSE"
    ) -> DataEnvelope[FundamentalSnapshot | None]: ...

    async def get_institutional_activity(
        self, symbol: str, exchange: str = "NSE"
    ) -> DataEnvelope[InstitutionalSnapshot | None]: ...
