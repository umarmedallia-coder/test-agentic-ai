from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class AgentStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    SKIPPED = "skipped"
    DISABLED = "disabled"
    UNIMPLEMENTED = "unimplemented"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class DataEnvelope(StrictModel):
    payload: dict
    source: str
    is_mock: bool
    observed_at: datetime
    retrieved_at: datetime = Field(default_factory=utc_now)
    freshness_seconds: int = Field(ge=0)
    quality: str = "valid"
    errors: list[str] = Field(default_factory=list)


class Evidence(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source: str
    observed_at: datetime
    statement: str
    provenance: str
    limitations: list[str] = Field(default_factory=list)


class AgentResult(StrictModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_name: str
    status: AgentStatus
    symbol: str | None = None
    exchange: str | None = None
    conclusion: str
    findings: dict = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    is_mock: bool = True


class TradeIntent(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    exchange: str = "NSE"
    direction: str = "long"
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    target_price: float = Field(gt=0)
    quantity: int = Field(gt=0)
    strategy: str = "technical"
    policy_version: str = "technical-v1"
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    source_agent: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def valid_prices(self) -> "TradeIntent":
        if self.direction == "long" and not self.stop_price < self.entry_price < self.target_price:
            raise ValueError("long intent requires stop < entry < target")
        if self.direction == "short" and not self.target_price < self.entry_price < self.stop_price:
            raise ValueError("short intent requires target < entry < stop")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        return self


class RiskDecision(StrictModel):
    accepted: bool
    approved_quantity: int = Field(default=0, ge=0)
    risk_amount: float = Field(default=0, ge=0)
    reasons: list[str] = Field(default_factory=list)


class Position(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    intent_id: str
    symbol: str
    exchange: str
    direction: str
    quantity: int
    entry_price: float
    stop_price: float
    target_price: float
    policy_version: str
    opened_at: datetime = Field(default_factory=utc_now)
    entry_fees: float = Field(default=0, ge=0)
    entry_fill_id: str | None = None
