"""Canonical timezone-aware market and execution contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DataStatus(StrEnum):
    OK = "ok"
    EMPTY = "empty"
    STALE = "stale"
    ERROR = "error"


class DataEnvelope(BaseModel, Generic[T]):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    source: str
    fetched_at: datetime = Field(default_factory=utc_now)
    as_of: datetime
    status: DataStatus = DataStatus.OK
    payload: T
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    @model_validator(mode="after")
    def timestamps_are_aware(self):
        for value in (self.fetched_at, self.as_of):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamps must be timezone-aware")
        if self.status == DataStatus.ERROR and not self.error:
            raise ValueError("error status requires an error message")
        return self


class OHLCVBar(BaseModel):
    timestamp: datetime
    symbol: str
    exchange: str = "NSE"
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_bar(self):
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("bar timestamp must be timezone-aware")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be the maximum OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be the minimum OHLC value")
        return self


class Quote(BaseModel):
    symbol: str
    exchange: str = "NSE"
    price: Decimal = Field(gt=0)
    bid: Decimal | None = None
    ask: Decimal | None = None
    volume: int = Field(default=0, ge=0)
    as_of: datetime

    @model_validator(mode="after")
    def validate_quote(self):
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("quote timestamp must be timezone-aware")
        if self.bid is not None and self.bid <= 0:
            raise ValueError("bid must be positive")
        if self.ask is not None and self.ask <= 0:
            raise ValueError("ask must be positive")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid cannot exceed ask")
        return self


class Evidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: str
    source: str
    observed_at: datetime
    published_at: datetime | None = None
    symbol: str | None = None
    headline: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    url: str | None = None

    @model_validator(mode="after")
    def validate_times(self):
        for value in (self.observed_at, self.published_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("evidence timestamps must be timezone-aware")
        return self


class Signal(BaseModel):
    signal_id: str = Field(default_factory=lambda: str(uuid4()))
    strategy: str
    symbol: str
    exchange: str = "NSE"
    direction: str
    entry: Decimal = Field(gt=0)
    stop: Decimal = Field(gt=0)
    target: Decimal = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_prices(self):
        if self.direction.lower() in {"long", "buy"} and not self.stop < self.entry < self.target:
            raise ValueError("long signal requires stop < entry < target")
        if self.direction.lower() in {"short", "sell"} and not self.target < self.entry < self.stop:
            raise ValueError("short signal requires target < entry < stop")
        if self.direction.lower() not in {"long", "buy", "short", "sell"}:
            raise ValueError("direction must be long/buy or short/sell")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return self


class PaperFill(BaseModel):
    fill_id: str = Field(default_factory=lambda: str(uuid4()))
    signal_id: str
    symbol: str
    side: str
    quantity: int = Field(gt=0)
    price: Decimal = Field(gt=0)
    fees: Decimal = Field(default=Decimal("0"), ge=0)
    slippage: Decimal = Field(default=Decimal("0"), ge=0)
    filled_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def aware_fill_time(self):
        if self.filled_at.tzinfo is None or self.filled_at.utcoffset() is None:
            raise ValueError("filled_at must be timezone-aware")
        return self


class TradeOutcome(BaseModel):
    outcome_id: str = Field(default_factory=lambda: str(uuid4()))
    fill_id: str
    symbol: str
    entry_price: Decimal
    exit_price: Decimal
    quantity: int
    gross_pnl: Decimal
    fees: Decimal
    net_pnl: Decimal
    reason: str
    closed_at: datetime = Field(default_factory=utc_now)


class ExecutionSnapshot(BaseModel):
    timestamp: datetime = Field(default_factory=utc_now)
    cash: Decimal
    equity: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    open_positions: int
    daily_loss: Decimal
