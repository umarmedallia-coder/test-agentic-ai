from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.contracts import TradeOutcome
from app.config import Settings
from app.services.engine import TradingEngine
from app.services.learning import (
    CandidateEvaluation,
    PaperPolicy,
    PaperPolicyRegistry,
    evaluate_candidate,
    chronological_split,
    evaluate_chronological,
    validate_strategy_parameter_proposal, evaluate_outcomes,
    generate_strategy_parameter_candidates,
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


def test_candidate_comparison_requires_identical_validation_timestamps():
    training = make_outcomes("train", 0, 100, Decimal("1"))
    candidate = make_outcomes("candidate", 100, 100, Decimal("2"))
    baseline = make_outcomes("baseline", 100, 100, Decimal("1"))
    baseline[50].closed_at += timedelta(days=1)
    evaluation = evaluate_candidate(
        training_outcomes=training,
        candidate_validation=candidate,
        baseline_validation=baseline,
        candidate_version="paper-v2",
        baseline_version="paper-v1",
        minimum_samples=100,
    )
    assert not evaluation.accepted
    assert "candidate and baseline validation windows do not match" in evaluation.reasons


def test_engine_policy_promotion_is_gated_persisted_and_rollbackable(tmp_path):
    engine = TradingEngine(Settings(journal_dir=tmp_path))
    engine.start()
    evaluation = CandidateEvaluation(
        accepted=True, candidate_version="paper-v2",
        baseline_version="paper-baseline-v1", training_samples=100,
        candidate_validation_samples=100, baseline_validation_samples=100,
        candidate_net_pnl=Decimal("200"), baseline_net_pnl=Decimal("100"),
    )
    promoted = engine.promote_paper_policy(
        PaperPolicy(
            version="paper-v2", parent_version="paper-baseline-v1",
            parameters={"ema_fast": 8},
        ),
        evaluation,
    )
    assert promoted.version == "paper-v2"
    engine.stop()

    recovered = TradingEngine(Settings(journal_dir=tmp_path))
    recovered.start()
    assert recovered.policy_registry.active.version == "paper-v2"
    assert recovered.rollback_paper_policy().version == "paper-baseline-v1"
    recovered.stop()


def test_engine_rejects_unvalidated_policy_promotion(tmp_path):
    engine = TradingEngine(Settings(journal_dir=tmp_path))
    engine.start()
    candidate = PaperPolicy(
        version="paper-v2", parent_version="paper-baseline-v1",
        parameters={"ema_fast": 8},
    )
    rejected = CandidateEvaluation(
        accepted=False, candidate_version="paper-v2",
        baseline_version="paper-baseline-v1", training_samples=100,
        candidate_validation_samples=100, baseline_validation_samples=100,
        candidate_net_pnl=Decimal("-10"), baseline_net_pnl=Decimal("100"),
        reasons=["candidate out-of-sample PnL is not positive"],
    )
    with pytest.raises(ValueError, match="evaluation gates"):
        engine.promote_paper_policy(candidate, rejected)
    assert engine.policy_registry.active.version == "paper-baseline-v1"
    engine.stop()


def test_paper_policy_parameters_are_deeply_immutable_and_json_serializable():
    policy = PaperPolicy(version="paper-v1", parameters={"ema_fast": 9})
    with pytest.raises(TypeError):
        policy.parameters["ema_fast"] = 10
    assert policy.model_dump(mode="json")["parameters"] == {"ema_fast": 9.0}


def test_learning_report_does_not_mix_policy_versions():
    baseline = make_outcomes("baseline", 0, 3, Decimal("1"))
    candidate = make_outcomes("candidate", 10, 2, Decimal("5"))
    for outcome in baseline:
        outcome.policy_version = "paper-v1"
        outcome.strategy = "technical"
    for outcome in candidate:
        outcome.policy_version = "paper-v2"
        outcome.strategy = "news"
    report = evaluate_outcomes(baseline + candidate, policy_version="paper-v2")
    assert report.sample_count == 2
    assert report.net_pnl == Decimal("10")
    empty = evaluate_outcomes(baseline + candidate, policy_version="paper-v3")
    assert empty.sample_count == 0



def test_candidate_generator_is_deterministic_bounded_and_strategy_only():
    current = {
        "ema_fast": 9, "ema_slow": 21, "rsi_lower": 30,
        "rsi_upper": 70, "atr_stop_multiple": 2, "reward_risk": 2,
    }
    candidates = generate_strategy_parameter_candidates(current)
    assert candidates
    assert candidates == generate_strategy_parameter_candidates(current)
    for candidate in candidates:
        changed = [key for key in current if candidate[key] != current[key]]
        assert len(changed) == 1
        assert set(candidate) == set(current)
        validate_strategy_parameter_proposal(current, {changed[0]: candidate[changed[0]]})
    assert all("max_daily_loss_pct" not in candidate for candidate in candidates)


def test_candidate_generator_rejects_invalid_baseline_and_step():
    current = {"ema_fast": 9, "ema_slow": 21}
    with pytest.raises(ValueError, match="relative_step"):
        generate_strategy_parameter_candidates(current, relative_step=0.2)
    with pytest.raises(ValueError, match="ema_fast"):
        generate_strategy_parameter_candidates({"ema_fast": 30, "ema_slow": 20})
