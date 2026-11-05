"""Canonical Decimal portfolio accounting with idempotent long/short fills and corporate actions."""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR

from pydantic import BaseModel, Field, model_validator

from app.contracts import PaperFill


class OpenPosition(BaseModel):
    symbol: str
    quantity: int = Field(gt=0)
    average_entry: Decimal = Field(gt=0)
    direction: str = "long"
    entry_fees: Decimal = Field(default=Decimal("0"), ge=0)
    mark: Decimal | None = None

    @model_validator(mode="after")
    def validate_direction(self):
        if self.direction not in {"long", "short"}:
            raise ValueError("position direction must be long or short")
        return self

    @property
    def unrealized_pnl(self) -> Decimal | None:
        if self.mark is None:
            return None
        movement = (
            self.mark - self.average_entry
            if self.direction == "long"
            else self.average_entry - self.mark
        )
        return movement * self.quantity - self.entry_fees


class PortfolioLedger:
    """Cash/position ledger; short-sale proceeds remain cash against a marked liability."""

    def __init__(self, starting_cash: Decimal = Decimal("1000000")) -> None:
        if starting_cash <= 0:
            raise ValueError("starting cash must be positive")
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.realized_pnl = Decimal("0")
        self.positions: dict[str, OpenPosition] = {}
        self._applied_fills: set[str] = set()
        self._applied_actions: set[str] = set()

    def _open(self, fill: PaperFill, direction: str) -> None:
        if fill.fill_id in self._applied_fills:
            return
        expected = {"long": {"buy", "long"}, "short": {"short", "sell"}}[direction]
        if fill.side.lower() not in expected:
            raise ValueError(f"{direction} opening requires side in {sorted(expected)}")
        old = self.positions.get(fill.symbol)
        if old and old.direction != direction:
            raise ValueError("cannot net an opposite-side position; close it explicitly first")
        notional = fill.price * fill.quantity
        if direction == "long":
            if notional + fill.fees > self.cash:
                raise ValueError("insufficient paper cash")
            self.cash -= notional + fill.fees
        else:
            # Proceeds are held as cash; the short market value is deducted in equity.
            self.cash += notional - fill.fees
        total_qty = fill.quantity + (old.quantity if old else 0)
        total_cost = notional + (old.average_entry * old.quantity if old else 0)
        fees = fill.fees + (old.entry_fees if old else Decimal("0"))
        self.positions[fill.symbol] = OpenPosition(
            symbol=fill.symbol, quantity=total_qty,
            average_entry=total_cost / total_qty, direction=direction,
            entry_fees=fees, mark=fill.price,
        )
        self._applied_fills.add(fill.fill_id)

    def apply_buy(self, fill: PaperFill) -> None:
        self._open(fill, "long")

    def apply_short(self, fill: PaperFill) -> None:
        """Open or add to a short position; never used as a long-position exit."""
        self._open(fill, "short")

    def _close(self, fill: PaperFill, expected_direction: str) -> Decimal:
        if fill.fill_id in self._applied_fills:
            return Decimal("0")
        expected_side = {"long": {"sell", "short"}, "short": {"buy", "cover", "long"}}[expected_direction]
        if fill.side.lower() not in expected_side:
            raise ValueError(f"{expected_direction} close requires side in {sorted(expected_side)}")
        position = self.positions.get(fill.symbol)
        if position is None or position.direction != expected_direction:
            raise ValueError(f"no open {expected_direction} position for {fill.symbol}")
        if fill.quantity > position.quantity:
            raise ValueError("close quantity exceeds the open paper position")
        allocated_entry_fees = (
            position.entry_fees * Decimal(fill.quantity) / Decimal(position.quantity)
        )
        gross = (
            (fill.price - position.average_entry) * fill.quantity
            if expected_direction == "long"
            else (position.average_entry - fill.price) * fill.quantity
        )
        net = gross - allocated_entry_fees - fill.fees
        if expected_direction == "long":
            self.cash += fill.price * fill.quantity - fill.fees
        else:
            cover_cost = fill.price * fill.quantity + fill.fees
            if cover_cost > self.cash:
                raise ValueError("insufficient paper cash to cover short position")
            self.cash -= cover_cost
        self.realized_pnl += net
        remaining_quantity = position.quantity - fill.quantity
        if remaining_quantity == 0:
            del self.positions[fill.symbol]
        else:
            position.quantity = remaining_quantity
            position.entry_fees -= allocated_entry_fees
        self._applied_fills.add(fill.fill_id)
        return net

    def apply_sell(self, fill: PaperFill) -> Decimal:
        """Close or reduce a long position; the legacy 'short' side label is accepted."""
        return self._close(fill, "long")

    def apply_cover(self, fill: PaperFill) -> Decimal:
        """Close or reduce a short position by buying shares back."""
        return self._close(fill, "short")

    def apply_split(
        self, symbol: str, ratio_from: Decimal, ratio_to: Decimal, action_id: str,
        *, cash_in_lieu_price: Decimal | None = None,
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
        whole_quantity = int(adjusted_quantity.to_integral_value(rounding=ROUND_FLOOR))
        fractional_quantity = adjusted_quantity - Decimal(whole_quantity)
        if fractional_quantity and (cash_in_lieu_price is None or cash_in_lieu_price <= 0):
            raise ValueError("fractional split entitlement requires a positive cash-in-lieu price")
        factor = ratio_from / ratio_to
        adjusted_average = position.average_entry * factor
        adjusted_mark = position.mark * factor if position.mark is not None else None
        if fractional_quantity:
            assert cash_in_lieu_price is not None
            cash_value = fractional_quantity * cash_in_lieu_price
            if position.direction == "long":
                self.cash += cash_value
                self.realized_pnl += fractional_quantity * (cash_in_lieu_price - adjusted_average)
            else:
                self.cash -= cash_value
                self.realized_pnl += fractional_quantity * (adjusted_average - cash_in_lieu_price)
        if whole_quantity == 0:
            del self.positions[symbol]
            self._applied_actions.add(action_id)
            return None
        position.quantity = whole_quantity
        position.average_entry = adjusted_average
        position.mark = adjusted_mark
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
        if position.direction == "short":
            self.cash -= cashflow
            self.realized_pnl -= cashflow
            cashflow = -cashflow
        else:
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
        if self.unrealized_pnl is None:
            return None
        long_assets = sum(
            (position.mark or position.average_entry) * position.quantity
            for position in self.positions.values() if position.direction == "long"
        )
        short_liabilities = sum(
            (position.mark or position.average_entry) * position.quantity
            for position in self.positions.values() if position.direction == "short"
        )
        return self.cash + long_assets - short_liabilities

    def snapshot(self) -> dict:
        return {
            "starting_cash": str(self.starting_cash),
            "cash": str(self.cash),
            "realized_pnl": str(self.realized_pnl),
            "positions": {
                symbol: position.model_dump(mode="json")
                for symbol, position in self.positions.items()
            },
            "applied_fills": sorted(self._applied_fills),
            "applied_actions": sorted(self._applied_actions),
        }

    def restore(self, snapshot: dict) -> None:
        self.starting_cash = Decimal(snapshot["starting_cash"])
        self.cash = Decimal(snapshot["cash"])
        self.realized_pnl = Decimal(snapshot["realized_pnl"])
        self.positions = {
            symbol: OpenPosition.model_validate(position)
            for symbol, position in snapshot.get("positions", {}).items()
        }
        self._applied_fills = set(snapshot.get("applied_fills", []))
        self._applied_actions = set(snapshot.get("applied_actions", []))
