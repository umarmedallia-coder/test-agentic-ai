"""Typed inputs for optional analytical agents; no synthetic values are implied."""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FundamentalSnapshot(AgentInput):
    symbol: str
    exchange: str = "NSE"
    as_of: datetime
    source: str = Field(min_length=1)
    is_mock: bool = False
    revenue_growth_pct: float | None = None
    earnings_growth_pct: float | None = None
    roe_pct: float | None = None
    roce_pct: float | None = None
    operating_margin_pct: float | None = None
    debt_to_equity: float | None = Field(default=None, ge=0)
    pe_ratio: float | None = Field(default=None, ge=0)
    pb_ratio: float | None = Field(default=None, ge=0)
    free_cash_flow: float | None = None

    @model_validator(mode="after")
    def validate_snapshot(self):
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("fundamental as_of must be timezone-aware")
        for name in ("revenue_growth_pct", "earnings_growth_pct", "roe_pct", "roce_pct", "operating_margin_pct", "debt_to_equity", "pe_ratio", "pb_ratio", "free_cash_flow"):
            value = getattr(self, name)
            if value is not None and not isfinite(value):
                raise ValueError(f"{name} must be finite")
        return self


class InstitutionalSnapshot(AgentInput):
    symbol: str
    exchange: str = "NSE"
    as_of: datetime
    source: str = Field(min_length=1)
    is_mock: bool = False
    fii_net_value: float | None = None
    dii_net_value: float | None = None
    delivery_pct: float | None = Field(default=None, ge=0, le=100)
    volume_ratio: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_snapshot(self):
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("institutional as_of must be timezone-aware")
        for name in ("fii_net_value", "dii_net_value", "delivery_pct", "volume_ratio"):
            value = getattr(self, name)
            if value is not None and not isfinite(value):
                raise ValueError(f"{name} must be finite")
        return self


class DiscoveryCandidate(AgentInput):
    symbol: str
    exchange: str = "NSE"
    last_price: float = Field(gt=0)
    average_daily_turnover: float = Field(ge=0)
    atr_pct: float = Field(ge=0, le=100)
    trend_direction: str
    trend_strength: float = Field(ge=0, le=1)
    data_as_of: datetime
    source: str = Field(min_length=1)
    is_mock: bool = False

    @model_validator(mode="after")
    def validate_candidate(self):
        if self.data_as_of.tzinfo is None or self.data_as_of.utcoffset() is None:
            raise ValueError("data_as_of must be timezone-aware")
        if self.trend_direction not in {"bullish", "bearish", "sideways", "unknown"}:
            raise ValueError("unsupported trend_direction")
        for name in ("last_price", "average_daily_turnover", "atr_pct", "trend_strength"):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        return self
