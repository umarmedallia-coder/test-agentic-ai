"""Corporate-action validation and event-risk restrictions."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class ActionType(StrEnum):
    SPLIT = "split"
    BONUS = "bonus"
    DIVIDEND = "dividend"
    RIGHTS = "rights"
    MERGER = "merger"
    OTHER = "other"


class CorporateAction(BaseModel):
    symbol: str
    exchange: str = "NSE"
    action_type: ActionType
    announcement_date: date
    ex_date: date | None = None
    record_date: date | None = None
    ratio_from: Decimal | None = Field(default=None, gt=0)
    ratio_to: Decimal | None = Field(default=None, gt=0)
    cash_amount: Decimal | None = Field(default=None, ge=0)
    source: str
    verified: bool = False

    @model_validator(mode="after")
    def validate_dates_and_ratio(self):
        if self.record_date and self.ex_date and self.record_date < self.ex_date:
            raise ValueError("record date cannot precede ex-date")
        if self.action_type in {ActionType.SPLIT, ActionType.BONUS} and (self.ratio_from is None or self.ratio_to is None):
            raise ValueError("split/bonus requires ratio_from and ratio_to")
        if self.action_type == ActionType.DIVIDEND and self.cash_amount is None:
            raise ValueError("dividend requires cash_amount")
        if not self.source.strip():
            raise ValueError("source is required")
        return self


def blocks_new_entry(action: CorporateAction, trading_day: date, buffer_days: int = 2) -> bool:
    """Conservative restriction around verified or unverified event dates."""
    event_day = action.ex_date or action.record_date
    if event_day is None:
        return True  # unknown event date: fail closed
    return abs((event_day-trading_day).days) <= buffer_days


def split_adjustment(
    quantity: int, average_cost: Decimal, action: CorporateAction
) -> tuple[int, Decimal]:
    """Adjust units and per-share cost; reject fractional entitlements until cash-in-lieu is modelled."""
    if action.action_type not in {ActionType.SPLIT, ActionType.BONUS}:
        raise ValueError("action must be a split or bonus")
    if not action.verified or action.ratio_from is None or action.ratio_to is None:
        raise ValueError("verified split/bonus ratio is required")
    if quantity <= 0 or average_cost <= 0:
        raise ValueError("quantity and average cost must be positive")
    adjusted = Decimal(quantity) * action.ratio_to / action.ratio_from
    if adjusted != adjusted.to_integral_value():
        raise ValueError("fractional entitlement requires explicit cash-in-lieu handling")
    new_quantity = int(adjusted)
    new_cost = average_cost * action.ratio_from / action.ratio_to
    return new_quantity, new_cost


def dividend_entitlement(
    quantity: int, action: CorporateAction, held_before_ex_date: bool
) -> Decimal:
    if action.action_type != ActionType.DIVIDEND:
        raise ValueError("action must be a dividend")
    if not action.verified or action.cash_amount is None:
        raise ValueError("verified dividend amount is required")
    if quantity < 0:
        raise ValueError("quantity cannot be negative")
    if not held_before_ex_date:
        return Decimal("0")
    return Decimal(quantity) * action.cash_amount
