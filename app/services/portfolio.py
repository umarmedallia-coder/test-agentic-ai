"""Mark-to-market accounting using Decimal arithmetic."""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from app.contracts import PaperFill


class OpenPosition(BaseModel):
    symbol: str
    quantity: int = Field(gt=0)
    average_entry: Decimal = Field(gt=0)
    entry_fees: Decimal = Decimal("0")
    mark: Decimal | None = None

    @property
    def unrealized_pnl(self) -> Decimal | None:
        if self.mark is None:
            return None
        return (self.mark-self.average_entry)*self.quantity-self.entry_fees


class PortfolioLedger:
    def __init__(self, starting_cash: Decimal = Decimal("1000000")) -> None:
        if starting_cash <= 0:
            raise ValueError("starting cash must be positive")
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.realized_pnl = Decimal("0")
        self.positions: dict[str, OpenPosition] = {}
        self._applied_fills: set[str] = set()
        self._applied_actions: set[str] = set()

    def apply_buy(self, fill: PaperFill) -> None:
        if fill.fill_id in self._applied_fills:
            return
        if fill.side.lower() not in {"buy", "long"}:
            raise ValueError("apply_buy requires a buy/long fill")
        notional = fill.price*fill.quantity
        if notional+fill.fees > self.cash:
            raise ValueError("insufficient paper cash")
        old = self.positions.get(fill.symbol)
        total_qty = fill.quantity+(old.quantity if old else 0)
        total_cost = notional+(old.average_entry*old.quantity if old else 0)
        fees = fill.fees+(old.entry_fees if old else Decimal("0"))
        self.positions[fill.symbol] = OpenPosition(symbol=fill.symbol,quantity=total_qty,
            average_entry=total_cost/total_qty,entry_fees=fees,mark=fill.price)
        self.cash -= notional+fill.fees
        self._applied_fills.add(fill.fill_id)

    def apply_split(
        self, symbol: str, ratio_from: Decimal, ratio_to: Decimal, action_id: str,
    ) -> tuple[int, Decimal] | None:
        if not action_id.strip():
            raise ValueError("action_id is required for idempotent split accounting")
        if action_id in self._applied_actions:
            position = self.positions.get(symbol)
            return (position.quantity, position.average_entry) if position else None
        if ratio_from <= 0 or ratio_to <= 0:
            raise ValueError("split ratios must be positive")
        position = self.positions.get(symbol)
        if position is None:
            self._applied_actions.add(action_id)
            return None
        adjusted_quantity = Decimal(position.quantity) * ratio_to / ratio_from
        if adjusted_quantity != adjusted_quantity.to_integral_value():
            raise ValueError("fractional split entitlement requires cash-in-lieu handling")
        factor = ratio_from / ratio_to
        position.quantity = int(adjusted_quantity)
        position.average_entry *= factor
        if position.mark is not None:
            position.mark *= factor
        self._applied_actions.add(action_id)
        return position.quantity, position.average_entry

    def apply_dividend(self, symbol: str, cash_per_share: Decimal, action_id: str) -> Decimal:
        if not action_id.strip():
            raise ValueError("action_id is required for idempotent dividend accounting")
        if action_id in self._applied_actions:
            return Decimal("0")
        if cash_per_share < 0:
            raise ValueError("dividend amount cannot be negative")
        position = self.positions.get(symbol)
        if position is None:
            self._applied_actions.add(action_id)
            return Decimal("0")
        cashflow = Decimal(position.quantity) * cash_per_share
        self.cash += cashflow
        self.realized_pnl += cashflow
        self._applied_actions.add(action_id)
        return cashflow

    def mark(self, symbol: str, price: Decimal) -> None:
        if price <= 0:
            raise ValueError("mark price must be positive")
        if symbol in self.positions:
            self.positions[symbol].mark = price

    @property
    def unrealized_pnl(self) -> Decimal | None:
        total = Decimal("0")
        for position in self.positions.values():
            value = position.unrealized_pnl
            if value is None:
                return None
            total += value
        return total

    @property
    def equity(self) -> Decimal | None:
        unrealized = self.unrealized_pnl
        if unrealized is None:
            return None
        market_value = sum((p.mark or p.average_entry)*p.quantity for p in self.positions.values())
        return self.cash+market_value

    def snapshot(self) -> dict:
        return {"cash":str(self.cash),"equity":str(self.equity) if self.equity is not None else None,
            "realized_pnl":str(self.realized_pnl),"unrealized_pnl":str(self.unrealized_pnl) if self.unrealized_pnl is not None else None,
            "positions":{k:v.model_dump(mode="json") for k,v in self.positions.items()}}
