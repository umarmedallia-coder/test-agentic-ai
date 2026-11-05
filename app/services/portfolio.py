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
