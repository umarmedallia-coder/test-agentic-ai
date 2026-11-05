"""Paper-only outcome evaluation, policy gates, and bounded offline proposals."""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from statistics import mean

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts import TradeOutcome


class LearningReport(BaseModel):
    sample_count: int
    win_rate: float = Field(ge=0, le=1)
    net_pnl: Decimal
    average_net_pnl: Decimal
    recommendation: str
    policy_version: str


class ChronologicalEvaluation(BaseModel):
    train: LearningReport
    test: LearningReport
    test_max_drawdown: Decimal
    passed: bool
    reason: str


class PaperPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str
    parent_version: str | None = None
    parameters: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_hard_risk_changes(self):
        forbidden = {
            "max_daily_loss_pct", "max_risk_per_trade_pct", "max_drawdown_pct",
            "max_open_positions", "max_gross_exposure_pct", "initial_capital",
            "risk_per_trade", "max_positions",
        }
        if forbidden.intersection(self.parameters):
            raise ValueError("hard risk limits cannot be changed by paper learning")
        unsupported = set(self.parameters) - {
            "ema_fast", "ema_slow", "rsi_lower", "rsi_upper",
            "atr_stop_multiple", "reward_risk",
        }
        if unsupported:
            raise ValueError(f"unsupported policy parameters: {sorted(unsupported)}")
        for name, value in self.parameters.items():
            lower, upper = _ALLOWED_STRATEGY_PARAMETERS[name]
            if not lower <= value <= upper:
                raise ValueError(f"{name} is outside its strategy safety bounds")
        if (
            "ema_fast" in self.parameters and "ema_slow" in self.parameters
            and self.parameters["ema_fast"] >= self.parameters["ema_slow"]
        ):
            raise ValueError("ema_fast must remain below ema_slow")
        if (
            "rsi_lower" in self.parameters and "rsi_upper" in self.parameters
            and self.parameters["rsi_lower"] >= self.parameters["rsi_upper"]
        ):
            raise ValueError("rsi_lower must remain below rsi_upper")
        return self


class CandidateEvaluation(BaseModel):
    accepted: bool
    candidate_version: str
    baseline_version: str
    training_samples: int
    candidate_validation_samples: int
    baseline_validation_samples: int
    candidate_net_pnl: Decimal
    baseline_net_pnl: Decimal
    reasons: list[str] = Field(default_factory=list)


class PaperPolicyRegistry:
    """In-memory immutable policy history; promotions are paper-only and explicitly gated."""

    def __init__(self, initial: PaperPolicy) -> None:
        self._history = [initial]

    @property
    def active(self) -> PaperPolicy:
        return self._history[-1]

    @property
    def versions(self) -> tuple[str, ...]:
        return tuple(policy.version for policy in self._history)

    def snapshot(self) -> list[dict[str, Any]]:
        return [policy.model_dump(mode="json") for policy in self._history]

    @classmethod
    def from_snapshot(cls, snapshot: list[dict[str, Any]]) -> PaperPolicyRegistry:
        policies = [PaperPolicy.model_validate(item) for item in snapshot]
        if not policies:
            raise ValueError("policy snapshot cannot be empty")
        for previous, current in zip(policies, policies[1:]):
            if current.parent_version != previous.version:
                raise ValueError("policy history contains a broken parent chain")
        registry = cls(policies[0])
        registry._history = policies
        return registry

    def promote(self, candidate: PaperPolicy, evaluation: CandidateEvaluation) -> PaperPolicy:
        if not evaluation.accepted:
            raise ValueError("candidate has not passed paper evaluation gates")
        if evaluation.candidate_version != candidate.version:
            raise ValueError("evaluation does not match candidate policy version")
        if candidate.parent_version != self.active.version:
            raise ValueError("candidate parent must match the active policy")
        if evaluation.baseline_version != self.active.version:
            raise ValueError("evaluation baseline must match the active policy")
        self._history.append(candidate)
        return self.active

    def rollback(self) -> PaperPolicy:
        if len(self._history) < 2:
            raise ValueError("no previous paper policy to restore")
        self._history.pop()
        return self.active


_ALLOWED_STRATEGY_PARAMETERS: dict[str, tuple[float, float]] = {
    "ema_fast": (2, 50),
    "ema_slow": (5, 200),
    "rsi_lower": (10, 45),
    "rsi_upper": (55, 90),
    "atr_stop_multiple": (0.5, 5),
    "reward_risk": (1, 5),
}


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
        if len(pnls) < 100 else "eligible for offline chronological validation"
    )
    return LearningReport(
        sample_count=len(pnls), win_rate=wins / len(pnls),
        net_pnl=sum(pnls, Decimal("0")),
        average_net_pnl=Decimal(str(mean(pnls))),
        recommendation=recommendation, policy_version=policy_version,
    )


def _ordered(outcomes: list[TradeOutcome]) -> list[TradeOutcome]:
    for outcome in outcomes:
        if outcome.closed_at.tzinfo is None or outcome.closed_at.utcoffset() is None:
            raise ValueError("outcome timestamps must be timezone-aware")
    return sorted(outcomes, key=lambda outcome: outcome.closed_at)


def _max_drawdown(pnls: list[Decimal]) -> Decimal:
    cumulative = Decimal("0")
    peak = Decimal("0")
    maximum = Decimal("0")
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        maximum = max(maximum, peak - cumulative)
    return maximum


def evaluate_candidate(
    *,
    training_outcomes: list[TradeOutcome],
    candidate_validation: list[TradeOutcome],
    baseline_validation: list[TradeOutcome],
    candidate_version: str,
    baseline_version: str,
    minimum_samples: int = 100,
) -> CandidateEvaluation:
    training = _ordered(training_outcomes)
    candidate = _ordered(candidate_validation)
    baseline = _ordered(baseline_validation)
    reasons: list[str] = []
    if len(training) < minimum_samples:
        reasons.append("insufficient training samples")
    if len(candidate) < minimum_samples:
        reasons.append("insufficient candidate validation samples")
    if len(baseline) < minimum_samples:
        reasons.append("insufficient baseline validation samples")
    if training and candidate and training[-1].closed_at >= candidate[0].closed_at:
        reasons.append("chronological leakage between training and candidate validation")
    if training and baseline and training[-1].closed_at >= baseline[0].closed_at:
        reasons.append("chronological leakage between training and baseline validation")
    if candidate and baseline and (
        candidate[0].closed_at != baseline[0].closed_at
        or candidate[-1].closed_at != baseline[-1].closed_at
    ):
        reasons.append("candidate and baseline validation windows do not match")
    candidate_pnl = sum((item.net_pnl for item in candidate), Decimal("0"))
    baseline_pnl = sum((item.net_pnl for item in baseline), Decimal("0"))
    if candidate_pnl <= 0:
        reasons.append("candidate out-of-sample PnL is not positive")
    if candidate_pnl <= baseline_pnl:
        reasons.append("candidate does not outperform baseline out of sample")
    if _max_drawdown([item.net_pnl for item in candidate]) > _max_drawdown(
        [item.net_pnl for item in baseline]
    ):
        reasons.append("candidate drawdown exceeds baseline")
    return CandidateEvaluation(
        accepted=not reasons, candidate_version=candidate_version,
        baseline_version=baseline_version, training_samples=len(training),
        candidate_validation_samples=len(candidate),
        baseline_validation_samples=len(baseline),
        candidate_net_pnl=candidate_pnl, baseline_net_pnl=baseline_pnl,
        reasons=reasons,
    )


def chronological_split(
    outcomes: list[TradeOutcome],
    *,
    train_ratio: float = 0.7,
    min_train_samples: int = 20,
    min_test_samples: int = 10,
) -> tuple[list[TradeOutcome], list[TradeOutcome]]:
    if not 0 < train_ratio < 1:
        raise ValueError("train_ratio must be strictly between zero and one")
    ordered = _ordered(outcomes)
    split_index = int(len(ordered) * train_ratio)
    if split_index < min_train_samples or len(ordered) - split_index < min_test_samples:
        raise ValueError("insufficient outcomes for chronological train/test evaluation")
    train, test = ordered[:split_index], ordered[split_index:]
    if train[-1].closed_at >= test[0].closed_at:
        raise ValueError("chronological split contains overlapping timestamps")
    return train, test


def evaluate_chronological(
    outcomes: list[TradeOutcome],
    *,
    policy_version: str,
    min_samples: int = 34,
    train_ratio: float = 0.7,
    min_test_win_rate: float = 0.5,
    max_test_drawdown: Decimal = Decimal("100000"),
) -> ChronologicalEvaluation:
    if len(outcomes) < min_samples:
        raise ValueError(f"at least {min_samples} outcomes are required")
    train, test = chronological_split(outcomes, train_ratio=train_ratio)
    train_report = evaluate_outcomes(train, policy_version)
    test_report = evaluate_outcomes(test, policy_version)
    drawdown = _max_drawdown([outcome.net_pnl for outcome in test])
    passed = (
        test_report.net_pnl > 0
        and test_report.win_rate >= min_test_win_rate
        and drawdown <= max_test_drawdown
    )
    reason = (
        "out-of-sample paper gates passed; manual review required"
        if passed else "out-of-sample paper gates failed; keep prior policy"
    )
    return ChronologicalEvaluation(
        train=train_report, test=test_report,
        test_max_drawdown=drawdown, passed=passed, reason=reason,
    )


def validate_strategy_parameter_proposal(
    current: dict[str, float],
    proposed: dict[str, float],
    *,
    max_relative_change: float = 0.2,
) -> dict[str, float]:
    """Validate strategy-only changes; risk limits and account controls are never tunable here."""
    if not 0 < max_relative_change <= 0.2:
        raise ValueError("max_relative_change must be in (0, 0.2]")
    unknown = set(proposed) - set(_ALLOWED_STRATEGY_PARAMETERS)
    if unknown:
        raise ValueError(f"unsupported or risk-related parameters: {sorted(unknown)}")
    result = dict(current)
    for name, value in proposed.items():
        if name not in current:
            raise ValueError(f"current value required for {name}")
        lower, upper = _ALLOWED_STRATEGY_PARAMETERS[name]
        baseline = current[name]
        if not lower <= value <= upper:
            raise ValueError(f"{name} is outside its absolute safety bounds")
        allowed_delta = max(abs(baseline) * max_relative_change, 0.01)
        if abs(value - baseline) > allowed_delta:
            raise ValueError(f"{name} exceeds the bounded change limit")
        result[name] = value
    if "ema_fast" in result and "ema_slow" in result and result["ema_fast"] >= result["ema_slow"]:
        raise ValueError("ema_fast must remain below ema_slow")
    if "rsi_lower" in result and "rsi_upper" in result and result["rsi_lower"] >= result["rsi_upper"]:
        raise ValueError("rsi_lower must remain below rsi_upper")
    return result
