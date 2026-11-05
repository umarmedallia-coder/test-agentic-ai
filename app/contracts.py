"""Canonical, timezone-aware contracts shared by data and strategy pipelines."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    @field_validator("fetched_at", "as_of")
    @classmethod
    def require_aware_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class OHLCVBar(BaseModel):
    timestamp: datetime
    symbol: str
    exchange: str = "NSE"
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(ge=0)

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("bar timestamp must be timezone-aware")
        return value

    @field_validator("high")
    @classmethod
    def high_not_below_low(cls, value: Decimal, info: Any) -> Decimal:
        low = info.data.get("low")
        if low is not None and value < low:
            raise ValueError("high cannot be below low")
        return value


class Quote(BaseModel):
    symbol: str
    exchange: str = "NSE"
    price: Decimal = Field(gt=0)
    bid: Decimal | None = None
    ask: Decimal | None = None
    volume: int = Field(default=0, ge=0)
    as_of: datetime

    @field_validator("as_of")
    @classmethod
    def aware_quote_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("quote timestamp must be timezone-aware")
        return value


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
    equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    open_positions: int
    daily_loss: Decimal
