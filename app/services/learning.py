"""Paper-only outcome evaluation and bounded offline parameter proposals."""
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


class ChronologicalEvaluation(BaseModel):
    train: LearningReport
    test: LearningReport
    test_max_drawdown: Decimal
    passed: bool
    reason: str


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


def chronological_split(
    outcomes: list[TradeOutcome],
    *,
    train_ratio: float = 0.7,
    min_train_samples: int = 20,
    min_test_samples: int = 10,
) -> tuple[list[TradeOutcome], list[TradeOutcome]]:
    if not 0 < train_ratio < 1:
        raise ValueError("train_ratio must be strictly between zero and one")
    ordered = sorted(outcomes, key=lambda outcome: outcome.closed_at)
    split_index = int(len(ordered) * train_ratio)
    if split_index < min_train_samples or len(ordered) - split_index < min_test_samples:
        raise ValueError("insufficient outcomes for chronological train/test evaluation")
    train, test = ordered[:split_index], ordered[split_index:]
    if train[-1].closed_at >= test[0].closed_at:
        raise ValueError("chronological split contains overlapping timestamps")
    return train, test


def _max_drawdown(pnls: list[Decimal]) -> Decimal:
    cumulative = Decimal("0")
    peak = Decimal("0")
    maximum = Decimal("0")
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        maximum = max(maximum, peak - cumulative)
    return maximum


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
