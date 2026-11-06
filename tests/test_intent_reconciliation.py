from datetime import UTC, datetime, timedelta

from app.contracts import RelationshipEdge
from app.models import Position, TradeIntent
from app.services.intent_reconciliation import (
    reconcile_intents,
    reconcile_portfolio_intents,
)


def make_intent(
    *, symbol="ABC", direction="long", confidence=0.5,
    strategy="technical", evidence_ids=None, intent_id=None,
):
    values = {
        "symbol": symbol, "direction": direction,
        "entry_price": 100, "stop_price": 95, "target_price": 110,
        "quantity": 10, "strategy": strategy, "confidence": confidence,
        "source_agent": strategy, "evidence_ids": evidence_ids or [],
    }
    if intent_id:
        values["id"] = intent_id
    if direction == "short":
        values.update(entry_price=100, stop_price=105, target_price=90)
    return TradeIntent(**values)


def test_same_direction_intents_merge_evidence_and_select_best_confidence():
    technical = make_intent(
        confidence=0.6, strategy="technical", evidence_ids=["price-1"],
    )
    news = make_intent(
        confidence=0.8, strategy="news", evidence_ids=["news-1"],
    )
    result = reconcile_intents([technical, news])
    assert len(result.accepted) == 1
    assert result.accepted[0].id == news.id
    assert result.accepted[0].evidence_ids == ["news-1", "price-1"]
    assert result.accepted[0].source_agent == "news,technical"
    assert len(result.rejected) == 1


def test_opposing_agent_intents_are_both_rejected():
    long_intent = make_intent(direction="long")
    short_intent = make_intent(direction="short", confidence=0.99)
    result = reconcile_intents([long_intent, short_intent])
    assert result.accepted == []
    assert len(result.rejected) == 2
    assert all("conflicting" in item.reason for item in result.rejected)


def test_duplicate_intent_ids_are_rejected():
    first = make_intent(intent_id="same-id")
    duplicate = make_intent(intent_id="same-id", confidence=0.9)
    result = reconcile_intents([first, duplicate])
    assert len(result.accepted) == 1
    assert result.rejected[0].reason == "duplicate intent id"



def relationship(source="ABC", target="XYZ", transmission="same", confidence=0.95,
                 valid_until=None, evidence_ids=None):
    now = datetime.now(UTC)
    return RelationshipEdge(
        source_symbol=source, target_symbol=target,
        relationship_type="documented_supply_chain",
        transmission=transmission,
        evidence_ids=["filing-1"] if evidence_ids is None else evidence_ids,
        source="verified exchange filing", valid_from=now - timedelta(days=2),
        valid_until=valid_until, confidence=confidence,
    )


def test_portfolio_reconciliation_allows_aligned_same_transmission_intents():
    first = make_intent(symbol="ABC", direction="long")
    second = make_intent(symbol="XYZ", direction="long")
    result = reconcile_portfolio_intents(
        [first, second], [relationship()], datetime.now(UTC),
    )
    assert {item.symbol for item in result.accepted} == {"ABC", "XYZ"}
    assert result.rejected == []


def test_portfolio_reconciliation_rejects_conflicting_related_intents():
    first = make_intent(symbol="ABC", direction="long")
    second = make_intent(symbol="XYZ", direction="short")
    result = reconcile_portfolio_intents(
        [first, second], [relationship()], datetime.now(UTC),
    )
    assert result.accepted == []
    assert len(result.rejected) == 2
    assert all("cross-symbol directional conflict" in item.reason
               for item in result.rejected)


def test_portfolio_reconciliation_applies_inverse_transmission():
    first = make_intent(symbol="ABC", direction="long")
    second = make_intent(symbol="XYZ", direction="short")
    result = reconcile_portfolio_intents(
        [first, second], [relationship(transmission="inverse")], datetime.now(UTC),
    )
    assert len(result.accepted) == 2
    blocked = reconcile_portfolio_intents(
        [first, make_intent(symbol="XYZ", direction="long")],
        [relationship(transmission="inverse")], datetime.now(UTC),
    )
    assert blocked.accepted == []
    assert len(blocked.rejected) == 2


def test_portfolio_reconciliation_fails_closed_for_unknown_or_weak_edges():
    first = make_intent(symbol="ABC", direction="long")
    second = make_intent(symbol="XYZ", direction="long")
    unknown = reconcile_portfolio_intents(
        [first, second], [relationship(transmission="unknown")], datetime.now(UTC),
    )
    weak = reconcile_portfolio_intents(
        [first, second], [relationship(confidence=0.4)], datetime.now(UTC),
    )
    assert unknown.accepted == []
    assert weak.accepted == []
    assert "unresolved" in unknown.rejected[0].reason
    assert "below threshold" in weak.rejected[0].reason


def test_portfolio_reconciliation_rejects_relationships_without_evidence_ids():
    first = make_intent(symbol="ABC", direction="long")
    second = make_intent(symbol="XYZ", direction="long")
    result = reconcile_portfolio_intents(
        [first, second], [relationship(evidence_ids=[" "])], datetime.now(UTC),
    )
    assert result.accepted == []
    assert len(result.rejected) == 2
    assert all("relationship evidence is missing" in item.reason
               for item in result.rejected)


def test_portfolio_reconciliation_checks_existing_related_holdings():
    candidate = make_intent(symbol="ABC", direction="long")
    holding = Position(
        intent_id="held-position", symbol="XYZ", exchange="NSE",
        direction="short", quantity=5, entry_price=100, stop_price=110,
        target_price=80, policy_version="baseline",
    )
    result = reconcile_portfolio_intents(
        [candidate], [relationship()], datetime.now(UTC),
        open_positions=[holding],
    )
    assert result.accepted == []
    assert len(result.rejected) == 1
    assert "existing holding XYZ" in result.rejected[0].reason


def test_portfolio_reconciliation_ignores_expired_relationships():
    first = make_intent(symbol="ABC", direction="long")
    second = make_intent(symbol="XYZ", direction="short")
    expired = relationship(valid_until=datetime.now(UTC) - timedelta(seconds=1))
    result = reconcile_portfolio_intents(
        [first, second], [expired], datetime.now(UTC),
    )
    assert len(result.accepted) == 2
    assert result.rejected == []


def test_portfolio_reconciliation_requires_aware_timestamp():
    import pytest

    with pytest.raises(ValueError, match="timezone-aware"):
        reconcile_portfolio_intents([], [], datetime.now())
