from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.contracts import OHLCVBar, PaperFill, Signal
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
        headline="BEL wins major order", source="wire", published_at=now,
        body="Bharat Electronics",
    )
    duplicate = NewsItem(
        headline="BEL wins major order!", source="other", published_at=now,
        symbols=["BEL"],
    )
    assert len(deduplicate_news([first, duplicate])) == 1
    assert map_news_to_symbols(first, {"Bharat Electronics": "BEL"}) == ["BEL"]
    assert score_news(first).impact > 0


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
