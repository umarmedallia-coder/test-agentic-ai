"""Paper-only outcome evaluation and bounded parameter proposal."""
from __future__ import annotations

from decimal import Decimal
from statistics import mean

from pydantic import BaseModel, Field

from app.contracts import TradeOutcome


class LearningReport(BaseModel):
    sample_count: int
    win_rate: float = Field(ge=0, le=1)
    net_pnl: Decimal
    average_net_pnl: Decimal
    recommendation: str
    policy_version: str


def evaluate_outcomes(outcomes: list[TradeOutcome], policy_version: str) -> LearningReport:
    if not outcomes:
        return LearningReport(sample_count=0,win_rate=0,net_pnl=Decimal("0"),
            average_net_pnl=Decimal("0"),recommendation="collect paper outcomes; no promotion",
            policy_version=policy_version)
    pnls = [o.net_pnl for o in outcomes]
    wins = sum(p > 0 for p in pnls)
    # Deliberately report only; no automatic parameter changes or policy promotion.
    recommendation = "review paper results; keep current policy" if len(pnls) < 100 else "eligible for offline chronological validation"
    return LearningReport(sample_count=len(pnls),win_rate=wins/len(pnls),
        net_pnl=sum(pnls,Decimal("0")),average_net_pnl=Decimal(str(mean(pnls))),
        recommendation=recommendation,policy_version=policy_version)
