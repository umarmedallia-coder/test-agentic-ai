"""Deterministic async mock provider for typed market-data contracts."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import numpy as np

from app.contracts import CompanyAnnouncement, CompanyProfile, CorporateActionRecord, DataEnvelope, DataStatus, NewsRecord, OHLCVBar, Quote, RelationshipEdge


class MockMarketDataProvider:
    def __init__(self, seed: int = 17) -> None:
        self._rng = np.random.default_rng(seed)
        self._symbols = ["RELIANCE", "HDFCBANK", "INFY", "BEL", "TCS"]

    async def get_stock_quote(self, symbol: str, exchange: str = "NSE") -> DataEnvelope[Quote]:
        bars = await self.get_historical_prices(symbol, datetime.now(timezone.utc)-timedelta(days=2), datetime.now(timezone.utc), exchange)
        bar = bars.payload[-1]
        quote = Quote(symbol=symbol, exchange=exchange, price=bar.close, volume=bar.volume, as_of=bar.timestamp)
        return DataEnvelope(source="mock", as_of=quote.as_of, payload=quote, warnings=["synthetic data"])

    async def get_historical_prices(self, symbol: str, start: datetime, end: datetime, exchange: str = "NSE") -> DataEnvelope[list[OHLCVBar]]:
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("timezone-aware start must precede end")
        count = max(2, min(500, int((end-start).total_seconds()//86400)+1))
        prices = [100.0 + sum(map(ord, symbol)) % 900]
        changes = self._rng.normal(0.0005, 0.015, count)
        for change in changes[1:]:
            prices.append(max(1.0, prices[-1]*(1+float(change))))
        stamps = np.linspace(start.timestamp(), end.timestamp(), count)
        bars = []
        for stamp, price in zip(stamps, prices):
            close = Decimal(str(round(price, 2)))
            spread = max(Decimal("0.01"), close*Decimal("0.006"))
            bars.append(OHLCVBar(timestamp=datetime.fromtimestamp(float(stamp), timezone.utc), symbol=symbol.upper(),
                exchange=exchange, open=close, high=close+spread, low=max(Decimal("0.01"),close-spread),
                close=close, volume=int(self._rng.integers(100_000,2_000_000))))
        return DataEnvelope(source="mock", as_of=bars[-1].timestamp, payload=bars, warnings=["synthetic data"])

    async def get_market_indices(self) -> DataEnvelope[dict[str,float]]:
        return DataEnvelope(source="mock",as_of=datetime.now(timezone.utc),payload={"NIFTY 50":0.25,"BANK NIFTY":-0.1},warnings=["synthetic data"])

    async def get_trading_calendar(self, day: date) -> DataEnvelope[dict[str,bool]]:
        return DataEnvelope(source="mock",as_of=datetime.now(timezone.utc),payload={"is_open":day.weekday()<5},warnings=["weekday-only mock calendar; exchange holidays are not modelled"])

    async def get_stock_universe(self, exchange: str = "NSE") -> DataEnvelope[list[str]]:
        return DataEnvelope(source="mock",as_of=datetime.now(timezone.utc),payload=self._symbols.copy(),warnings=["synthetic universe"])

    async def validate_stock_symbol(self, symbol: str, exchange: str = "NSE") -> DataEnvelope[bool]:
        return DataEnvelope(source="mock",as_of=datetime.now(timezone.utc),payload=symbol.upper() in self._symbols,warnings=["synthetic symbol registry"])


    async def get_stock_news(self, symbol: str, since: datetime | None = None) -> DataEnvelope[list[NewsRecord]]:
        return DataEnvelope(
            source="mock", as_of=datetime.now(timezone.utc), status=DataStatus.EMPTY,
            payload=[], warnings=["mock news feed contains no articles"],
        )

    async def get_news_details(self, news_id: str) -> DataEnvelope[NewsRecord]:
        raise ValueError(f"unknown mock news id: {news_id}")

    async def get_company_announcements(self, symbol: str) -> DataEnvelope[list[CompanyAnnouncement]]:
        return DataEnvelope(
            source="mock", as_of=datetime.now(timezone.utc), status=DataStatus.EMPTY,
            payload=[], warnings=["mock announcement feed contains no records"],
        )

    async def get_corporate_actions(self, symbol: str) -> DataEnvelope[list[CorporateActionRecord]]:
        return DataEnvelope(
            source="mock", as_of=datetime.now(timezone.utc), status=DataStatus.EMPTY,
            payload=[], warnings=["mock corporate-action feed contains no records"],
        )

    async def resolve_company_entity(self, query: str) -> DataEnvelope[str | None]:
        aliases = {
            "reliance industries": "RELIANCE", "hdfc bank": "HDFCBANK",
            "infosys": "INFY", "bharat electronics": "BEL",
            "tata consultancy services": "TCS",
        }
        resolved = aliases.get(query.strip().lower())
        return DataEnvelope(
            source="mock", as_of=datetime.now(timezone.utc),
            status=DataStatus.OK if resolved else DataStatus.EMPTY,
            payload=resolved, warnings=["exact mock alias matching only"],
        )

    async def get_company_profile(self, symbol: str) -> DataEnvelope[CompanyProfile]:
        names = {
            "RELIANCE": "Reliance Industries", "HDFCBANK": "HDFC Bank",
            "INFY": "Infosys", "BEL": "Bharat Electronics",
            "TCS": "Tata Consultancy Services",
        }
        normalized = symbol.upper()
        if normalized not in names:
            raise ValueError(f"unknown mock symbol: {symbol}")
        profile = CompanyProfile(
            symbol=normalized, company_name=names[normalized], exchange="NSE", source="mock",
        )
        return DataEnvelope(source="mock", as_of=datetime.now(timezone.utc), payload=profile,
                            warnings=["synthetic company profile"])

    async def get_company_relationships(self, symbol: str) -> DataEnvelope[list[RelationshipEdge]]:
        return DataEnvelope(
            source="mock", as_of=datetime.now(timezone.utc), status=DataStatus.EMPTY,
            payload=[], warnings=["no relationship graph has been configured"],
        )
