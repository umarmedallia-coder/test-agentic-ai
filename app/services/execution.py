"""Deterministic paper broker with explicit costs and idempotent fill keys."""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from pydantic import BaseModel, Field

from app.contracts import PaperFill, Signal


class PaperExecutionConfig(BaseModel):
    fee_rate: Decimal = Field(default=Decimal("0.0003"), ge=0)
    slippage_bps: Decimal = Field(default=Decimal("5"), ge=0)
    lot_size: int = Field(default=1, ge=1)


class PaperBroker:
    def __init__(self, config: PaperExecutionConfig | None = None) -> None:
        self.config = config or PaperExecutionConfig()
        self._fills: dict[str, PaperFill] = {}

    def execute(self, signal: Signal, quantity: int, reference_price: Decimal) -> PaperFill:
        if quantity <= 0 or reference_price <= 0:
            raise ValueError("quantity and reference price must be positive")
        if quantity % self.config.lot_size:
            raise ValueError("quantity must be a multiple of lot size")
        key = signal.signal_id
        if key in self._fills:
            return self._fills[key]
        adverse = Decimal("1") + self.config.slippage_bps/Decimal("10000")
        if signal.direction.lower() in {"short", "sell"}:
            adverse = Decimal("1") - self.config.slippage_bps/Decimal("10000")
        price = (reference_price*adverse).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        notional = price*quantity
        fill = PaperFill(signal_id=key,symbol=signal.symbol,side=signal.direction,
            quantity=quantity,price=price,fees=(notional*self.config.fee_rate).quantize(Decimal("0.01")),
            slippage=abs(price-reference_price)*quantity)
        self._fills[key] = fill
        return fill
