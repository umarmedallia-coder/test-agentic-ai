from app.models import TradeIntent
from app.services.intent_reconciliation import reconcile_intents


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
