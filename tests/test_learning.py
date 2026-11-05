from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.contracts import TradeOutcome
from app.services.learning import (
    PaperPolicy,
    PaperPolicyRegistry,
    evaluate_candidate,
    chronological_split,
    evaluate_chronological,
    validate_strategy_parameter_proposal,
)


def make_outcomes(prefix: str, start_day: int, count: int, pnl: Decimal):
    start = datetime(2025, 1, 1, tzinfo=UTC)
    return [
        TradeOutcome(
            fill_id=f"{prefix}-{index}", symbol="ABC",
            entry_price=Decimal("100"), exit_price=Decimal("100") + pnl,
            quantity=1, gross_pnl=pnl, fees=Decimal("0"), net_pnl=pnl,
            reason="test", closed_at=start + timedelta(days=start_day + index),
        )
        for index in range(count)
    ]


def test_chronological_candidate_evaluation_and_paper_policy_rollback():
    training = make_outcomes("train", 0, 100, Decimal("1"))
    candidate = make_outcomes("candidate", 100, 100, Decimal("2"))
    baseline = make_outcomes("baseline", 100, 100, Decimal("1"))
    evaluation = evaluate_candidate(
        training_outcomes=training,
        candidate_validation=candidate,
        baseline_validation=baseline,
        candidate_version="paper-v2",
        baseline_version="paper-v1",
        minimum_samples=100,
    )
    assert evaluation.accepted
    assert evaluation.candidate_net_pnl == Decimal("200")
    assert evaluation.baseline_net_pnl == Decimal("100")

    registry = PaperPolicyRegistry(PaperPolicy(version="paper-v1"))
    registry.promote(
        PaperPolicy(version="paper-v2", parent_version="paper-v1", parameters={"ema_fast": 8}),
        evaluation,
    )
    assert registry.active.version == "paper-v2"
    recovered = PaperPolicyRegistry.from_snapshot(registry.snapshot())
    assert recovered.active.version == "paper-v2"
    assert recovered.versions == ("paper-v1", "paper-v2")
    assert registry.rollback().version == "paper-v1"


def test_chronological_evaluation_rejects_leakage_and_insufficient_samples():
    training = make_outcomes("train", 0, 100, Decimal("1"))
    overlapping_candidate = make_outcomes("candidate", 90, 20, Decimal("3"))
    baseline = make_outcomes("baseline", 90, 20, Decimal("1"))
    evaluation = evaluate_candidate(
        training_outcomes=training,
        candidate_validation=overlapping_candidate,
        baseline_validation=baseline,
        candidate_version="paper-v2",
        baseline_version="paper-v1",
        minimum_samples=100,
    )
    assert not evaluation.accepted
    assert any("leakage" in reason for reason in evaluation.reasons)
    assert any("insufficient" in reason for reason in evaluation.reasons)


def test_policy_registry_rejects_hard_risk_limit_changes():
    with pytest.raises(ValueError, match="hard risk limits"):
        PaperPolicy(
            version="unsafe", parameters={"max_daily_loss_pct": 0.5},
        )


def test_chronological_split_and_out_of_sample_evaluation():
    outcomes = make_outcomes("paper", 0, 40, Decimal("5"))
    train, test = chronological_split(outcomes)
    assert len(train) == 28
    assert len(test) == 12
    assert train[-1].closed_at < test[0].closed_at
    evaluation = evaluate_chronological(
        outcomes, policy_version="paper-v1",
    )
    assert evaluation.passed
    assert evaluation.train.sample_count == 28
    assert evaluation.test.sample_count == 12


def test_strategy_parameter_proposals_are_bounded_and_risk_limits_are_immutable():
    current = {
        "ema_fast": 9, "ema_slow": 21, "rsi_lower": 30,
        "rsi_upper": 70, "atr_stop_multiple": 2, "reward_risk": 2,
    }
    proposed = validate_strategy_parameter_proposal(
        current, {"ema_fast": 10, "atr_stop_multiple": 2.2},
    )
    assert proposed["ema_fast"] == 10
    assert proposed["atr_stop_multiple"] == 2.2
    with pytest.raises(ValueError, match="risk-related"):
        validate_strategy_parameter_proposal(
            current, {"max_risk_per_trade_pct": 0.02},
        )
    with pytest.raises(ValueError, match="bounded change"):
        validate_strategy_parameter_proposal(current, {"ema_fast": 20})
