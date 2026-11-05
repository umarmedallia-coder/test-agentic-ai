"""Paper-only outcome reporting and leakage-safe chronological policy evaluation."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from statistics import mean

from pydantic import BaseModel, Field, model_validator

from app.contracts import TradeOutcome


class LearningReport(BaseModel):
    sample_count: int
    win_rate: float = Field(ge=0, le=1)
    net_pnl: Decimal
    average_net_pnl: Decimal
    recommendation: str
    policy_version: str


class PolicyEvaluation(BaseModel):
    candidate_version: str
    baseline_version: str
    training_samples: int
    candidate_validation_samples: int
    baseline_validation_samples: int
    candidate_net_pnl: Decimal
    baseline_net_pnl: Decimal
    candidate_max_drawdown: float = Field(ge=0, le=1)
    accepted: bool
    reasons: list[str]
    training_end: datetime | None = None
    validation_start: datetime | None = None
    validation_end: datetime | None = None


class PaperPolicy(BaseModel):
    version: str
    parameters: dict[str, float] = Field(default_factory=dict)
    parent_version: str | None = None

    @model_validator(mode="after")
    def reject_hard_risk_overrides(self):
        protected = {
            "max_risk_per_trade_pct", "max_daily_loss_pct", "max_drawdown_pct",
            "max_open_positions", "max_gross_exposure_pct",
        }
        forbidden = protected.intersection(self.parameters)
        if forbidden:
            raise ValueError(f"policy cannot modify hard risk limits: {sorted(forbidden)}")
        return self


def evaluate_outcomes(outcomes: list[TradeOutcome], policy_version: str) -> LearningReport:
    if not outcomes:
        return LearningReport(
            sample_count=0, win_rate=0, net_pnl=Decimal("0"),
            average_net_pnl=Decimal("0"),
            recommendation="collect paper outcomes; no promotion",
            policy_version=policy_version,
        )
    pnls = [outcome.net_pnl for outcome in outcomes]
    wins = sum(pnl > 0 for pnl in pnls)
    recommendation = (
        "review paper results; keep current policy"
        if len(pnls) < 100
        else "eligible for separate chronological validation; no automatic promotion"
    )
    return LearningReport(
        sample_count=len(pnls), win_rate=wins / len(pnls),
        net_pnl=sum(pnls, Decimal("0")),
        average_net_pnl=Decimal(str(mean(pnls))),
        recommendation=recommendation, policy_version=policy_version,
    )


def _max_drawdown(outcomes: list[TradeOutcome], initial_equity: Decimal) -> float:
    equity = initial_equity
    peak = initial_equity
    maximum = Decimal("0")
    for outcome in sorted(outcomes, key=lambda item: item.closed_at):
        equity += outcome.net_pnl
        peak = max(peak, equity)
        if peak > 0:
            maximum = max(maximum, (peak - equity) / peak)
    return float(maximum)


def evaluate_candidate(
    *,
    training_outcomes: list[TradeOutcome],
    candidate_validation: list[TradeOutcome],
    baseline_validation: list[TradeOutcome],
    candidate_version: str,
    baseline_version: str,
    minimum_samples: int = 100,
    maximum_drawdown: float = 0.10,
    initial_equity: Decimal = Decimal("1000000"),
) -> PolicyEvaluation:
    """Evaluate only on later outcomes; rejects overlap and insufficient evidence."""
    if minimum_samples < 1 or not 0 < maximum_drawdown <= 1 or initial_equity <= 0:
        raise ValueError("invalid evaluation gate configuration")
    reasons: list[str] = []
    training = sorted(training_outcomes, key=lambda item: item.closed_at)
    candidate = sorted(candidate_validation, key=lambda item: item.closed_at)
    baseline = sorted(baseline_validation, key=lambda item: item.closed_at)
    training_end = training[-1].closed_at if training else None
    validation_start = min(
        (item.closed_at for item in candidate + baseline), default=None,
    )
    validation_end = max(
        (item.closed_at for item in candidate + baseline), default=None,
    )

    if len(training) < minimum_samples:
        reasons.append("insufficient chronological training samples")
    if len(candidate) < minimum_samples or len(baseline) < minimum_samples:
        reasons.append("insufficient candidate or baseline validation samples")
    if training_end is not None and validation_start is not None and training_end >= validation_start:
        reasons.append("chronological leakage: training outcomes overlap validation period")
    if not candidate or not baseline:
        reasons.append("candidate and baseline validation outcomes are required")

    candidate_net = sum((item.net_pnl for item in candidate), Decimal("0"))
    baseline_net = sum((item.net_pnl for item in baseline), Decimal("0"))
    drawdown = _max_drawdown(candidate, initial_equity) if candidate else 0.0
    if candidate_net <= baseline_net:
        reasons.append("candidate does not outperform the baseline after costs")
    if drawdown > maximum_drawdown:
        reasons.append("candidate exceeds the maximum validation drawdown")

    return PolicyEvaluation(
        candidate_version=candidate_version, baseline_version=baseline_version,
        training_samples=len(training), candidate_validation_samples=len(candidate),
        baseline_validation_samples=len(baseline), candidate_net_pnl=candidate_net,
        baseline_net_pnl=baseline_net, candidate_max_drawdown=drawdown,
        accepted=not reasons, reasons=reasons, training_end=training_end,
        validation_start=validation_start, validation_end=validation_end,
    )


class PaperPolicyRegistry:
    """Versioned paper-only promotion and rollback; hard risk limits are immutable."""

    def __init__(self, initial_policy: PaperPolicy) -> None:
        self.active = initial_policy
        self._history: list[PaperPolicy] = []

    def promote(self, candidate: PaperPolicy, evaluation: PolicyEvaluation) -> None:
        if not evaluation.accepted:
            raise ValueError("policy evaluation did not pass promotion gates")
        if candidate.parent_version != self.active.version:
            raise ValueError("candidate parent does not match the active policy version")
        if candidate.version in {self.active.version, *(policy.version for policy in self._history)}:
            raise ValueError("policy version already exists")
        if candidate.version != evaluation.candidate_version:
            raise ValueError("candidate version does not match evaluated version")
        self._history.append(self.active)
        self.active = candidate

    def rollback(self) -> PaperPolicy:
        if not self._history:
            raise ValueError("no prior paper policy is available for rollback")
        self.active = self._history.pop()
        return self.active
