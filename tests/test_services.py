from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.contracts import OHLCVBar, PaperFill, RelationshipEdge, Signal
from app.services.corporate_actions import (
    ActionType,
    CorporateAction,
    blocks_new_entry,
    dividend_entitlement,
    split_adjustment,
)
from app.services.execution import PaperBroker, PaperExecutionConfig
from app.services.news import (
    NewsItem,
    build_news_signal,
    deduplicate_news,
    map_news_to_symbols,
    score_news,
    map_news_impact,
)
from app.services.orchestrator import AgentOrchestrator
from app.services.portfolio import PortfolioLedger


def test_typed_bar_rejects_naive_timestamp_and_invalid_range():
    with pytest.raises(ValueError):
        OHLCVBar(
            timestamp=datetime.now(), symbol="ABC", open=Decimal(10), high=Decimal(9),
            low=Decimal(8), close=Decimal(9), volume=100,
        )
    with pytest.raises(ValueError):
        OHLCVBar(
            timestamp=datetime.now(UTC), symbol="ABC", open=Decimal(10),
            high=Decimal(7), low=Decimal(8), close=Decimal(9), volume=100,
        )


def test_news_deduplication_and_explicit_alias_mapping():
    now = datetime.now(UTC)
    first = NewsItem(
        headline="BEL order win and profit rises", source="wire", published_at=now,
        body="Bharat Electronics",
    )
    duplicate = NewsItem(
        headline="BEL order win and profit rises!", source="other", published_at=now,
        symbols=["BEL"],
    )
    assert len(deduplicate_news([first, duplicate])) == 1
    assert map_news_to_symbols(first, {"Bharat Electronics": "BEL"}) == ["BEL"]
    scored = score_news(first)
    assert scored.impact_score > 0
    assert scored.sentiment > 0


def test_corporate_action_unknown_event_fails_closed():
    action = CorporateAction(
        symbol="ABC", action_type=ActionType.OTHER,
        announcement_date=datetime.now(UTC).date(), source="exchange",
    )
    assert blocks_new_entry(action, datetime.now(UTC).date())


def test_paper_broker_is_idempotent():
    signal = Signal(
        strategy="test", symbol="ABC", direction="long", entry=Decimal(100),
        stop=Decimal(95), target=Decimal(110), confidence=0.8, rationale="test",
    )
    broker = PaperBroker(PaperExecutionConfig())
    first = broker.execute(signal, 10, Decimal(100))
    second = broker.execute(signal, 10, Decimal(100))
    assert first.fill_id == second.fill_id
    assert first.price > Decimal(100)


def test_ledger_marks_to_market_and_prevents_duplicate_fill():
    ledger = PortfolioLedger(Decimal(10000))
    fill = PaperFill(
        signal_id="s1", symbol="ABC", side="buy", quantity=10,
        price=Decimal(100), fees=Decimal(1),
    )
    ledger.apply_buy(fill)
    ledger.apply_buy(fill)
    ledger.mark("ABC", Decimal(110))
    assert ledger.cash == Decimal(8999)
    assert ledger.equity == Decimal(10099)


@pytest.mark.asyncio
async def test_orchestrator_isolates_failures_and_runs_peers():
    async def ok():
        return 42

    async def bad():
        raise RuntimeError("broken agent")

    runner = AgentOrchestrator(max_parallel=2, retries=0)
    result = await runner.run_parallel({"ok": ok, "bad": bad})
    assert {item["status"] for item in result} == {"succeeded", "failed"}


def test_news_signal_uses_only_supplied_price_and_atr():
    now = datetime.now(UTC)
    item = NewsItem(
        headline="Company wins major order and profit rises; upgrade approval",
        source="exchange", published_at=now, symbols=["ABC"],
    )
    impact = score_news(item)
    signal = build_news_signal(impact, 100, 2)
    assert signal is not None
    assert signal.entry == Decimal("100")
    assert signal.stop == Decimal("97.0")
    assert signal.target == Decimal("105.0")


def test_verified_split_and_dividend_accounting():
    today = datetime.now(UTC).date()
    split = CorporateAction(
        symbol="ABC", action_type=ActionType.SPLIT, announcement_date=today,
        ex_date=today, source="exchange", verified=True,
        ratio_from=Decimal("1"), ratio_to=Decimal("2"),
    )
    quantity, cost = split_adjustment(10, Decimal("100"), split)
    assert quantity == 20
    assert cost == Decimal("50")
    dividend = CorporateAction(
        symbol="ABC", action_type=ActionType.DIVIDEND, announcement_date=today,
        ex_date=today, record_date=today, source="exchange", verified=True,
        cash_amount=Decimal("5"),
    )
    assert dividend_entitlement(20, dividend, True) == Decimal("100")
    assert dividend_entitlement(20, dividend, False) == Decimal("0")


def test_portfolio_ledger_applies_split_and_dividend_cashflow():
    ledger = PortfolioLedger(Decimal("10000"))
    fill = PaperFill(
        signal_id="corporate-action-position", symbol="ABC", side="buy",
        quantity=10, price=Decimal("100"), fees=Decimal("1"),
    )
    ledger.apply_buy(fill)
    quantity, average_cost = ledger.apply_split(
        "ABC", Decimal("1"), Decimal("2"), action_id="split-1",
    )
    assert quantity == 20
    assert average_cost == Decimal("50")
    assert ledger.positions["ABC"].mark == Decimal("50")
    duplicate_quantity, _ = ledger.apply_split(
        "ABC", Decimal("1"), Decimal("2"), action_id="split-1",
    )
    assert duplicate_quantity == 20
    dividend = ledger.apply_dividend("ABC", Decimal("5"), action_id="dividend-1")
    assert dividend == Decimal("100")
    assert ledger.realized_pnl == Decimal("100")
    assert ledger.apply_dividend("ABC", Decimal("5"), action_id="dividend-1") == Decimal("0")
    assert ledger.cash == Decimal("9099")


def test_news_impact_maps_only_evidenced_relationships_and_retains_conflicts():
    now = datetime.now(UTC)
    item = NewsItem(
        headline="Company wins major order, profit rises, upgrade approval",
        source="exchange", published_at=now, symbols=["BEL"],
    )
    impact = score_news(item)
    edges = [
        RelationshipEdge(
            source_symbol="BEL", target_symbol="SUPPLIER",
            relationship_type="supplier", transmission="same",
            evidence_ids=["exchange-filing-1"], source="exchange",
            valid_from=now - timedelta(days=10), confidence=0.9,
        ),
        RelationshipEdge(
            source_symbol="BEL", target_symbol="COMPETITOR",
            relationship_type="competitor", transmission="inverse",
            evidence_ids=["exchange-filing-2"], source="exchange",
            valid_from=now - timedelta(days=10), confidence=0.85,
        ),
        RelationshipEdge(
            source_symbol="BEL", target_symbol="UNKNOWN",
            relationship_type="customer", transmission="unknown",
            evidence_ids=["exchange-filing-3"], source="exchange",
            valid_from=now - timedelta(days=10), confidence=0.95,
        ),
        RelationshipEdge(
            source_symbol="BEL", target_symbol="WEAK",
            relationship_type="supplier", transmission="same",
            evidence_ids=["weak-source"], source="unverified",
            valid_from=now - timedelta(days=10), confidence=0.2,
        ),
    ]
    mapped = map_news_impact(impact, edges, as_of=now)
    by_symbol = {security.symbol: security for security in mapped.affected_securities}
    assert by_symbol["BEL"].direction == "positive"
    assert by_symbol["SUPPLIER"].direction == "positive"
    assert by_symbol["COMPETITOR"].direction == "negative"
    assert by_symbol["UNKNOWN"].direction == "uncertain"
    assert "WEAK" not in by_symbol
    assert mapped.evaluated_relationships == 3
    assert mapped.rejected_relationships == 1


def test_balanced_news_sentiment_never_creates_directional_trade():
    now = datetime.now(UTC)
    item = NewsItem(
        headline="Order win, profit rises, fraud probe announced",
        source="exchange", published_at=now, symbols=["ABC"],
    )
    impact = score_news(item)
    assert impact.impact_score >= 65
    assert impact.sentiment == 0
    assert build_news_signal(impact, 100, 2) is None


def test_news_impact_maps_same_inverse_and_mixed_relationships():
    now = datetime.now(UTC)
    item = NewsItem(
        headline="BEL wins major order, profit rises, upgrade approval",
        source="exchange", published_at=now, symbols=["BEL"],
    )
    impact = score_news(item)
    edges = [
        RelationshipEdge(
            source_symbol="BEL", target_symbol="BEML", relationship_type="supplier",
            transmission="same", evidence_ids=["r1"], source="filing",
            valid_from=now - timedelta(days=1), confidence=0.9,
        ),
        RelationshipEdge(
            source_symbol="BEL", target_symbol="XYZ", relationship_type="competitor",
            transmission="inverse", evidence_ids=["r2"], source="filing",
            valid_from=now - timedelta(days=1), confidence=0.8,
        ),
        RelationshipEdge(
            source_symbol="BEL", target_symbol="ABC", relationship_type="sector_peer",
            transmission="mixed", evidence_ids=["r3"], source="filing",
            valid_from=now - timedelta(days=1), confidence=0.9,
        ),
        RelationshipEdge(
            source_symbol="BEL", target_symbol="OLD", relationship_type="expired",
            transmission="same", evidence_ids=["r4"], source="old filing",
            valid_from=now - timedelta(days=5), valid_until=now - timedelta(days=1),
            confidence=0.99,
        ),
    ]
    result = map_news_impact(impact, edges, as_of=now)
    directions = {security.symbol: security.direction for security in result.affected_securities}
    assert directions["BEL"] == "positive"
    assert directions["BEML"] == "positive"
    assert directions["XYZ"] == "negative"
    assert directions["ABC"] == "mixed"
    assert result.rejected_relationships == 1


def test_portfolio_ledger_realizes_exit_after_entry_and_costs_once():
    ledger = PortfolioLedger(Decimal("10000"))
    entry = PaperFill(
        fill_id="entry-abc", signal_id="signal-abc", symbol="ABC", side="buy",
        quantity=10, price=Decimal("100"), fees=Decimal("1"),
    )
    ledger.apply_buy(entry)
    exit_fill = PaperFill(
        fill_id="exit-abc", signal_id="exit-signal-abc", symbol="ABC", side="short",
        quantity=10, price=Decimal("110"), fees=Decimal("1"),
    )
    realized = ledger.apply_sell(exit_fill)
    assert realized == Decimal("98")
    assert ledger.realized_pnl == Decimal("98")
    assert ledger.cash == Decimal("10098")
    assert ledger.positions == {}
    assert ledger.apply_sell(exit_fill) == Decimal("0")
