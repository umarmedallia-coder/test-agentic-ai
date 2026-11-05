from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.contracts import OHLCVBar, PaperFill, Signal
from app.services.corporate_actions import ActionType, CorporateAction, blocks_new_entry
from app.services.execution import PaperBroker, PaperExecutionConfig
from app.services.news import NewsItem, deduplicate_news, map_news_to_symbols, score_news
from app.services.orchestrator import AgentOrchestrator
from app.services.portfolio import PortfolioLedger


def test_typed_bar_rejects_naive_timestamp_and_invalid_range():
    with pytest.raises(ValueError):
        OHLCVBar(timestamp=datetime.now(),symbol="ABC",open=Decimal(10),high=Decimal(9),
                 low=Decimal(8),close=Decimal(9),volume=100)
    with pytest.raises(ValueError):
        OHLCVBar(timestamp=datetime.now(timezone.utc),symbol="ABC",open=Decimal(10),
                 high=Decimal(7),low=Decimal(8),close=Decimal(9),volume=100)


def test_news_deduplication_and_explicit_alias_mapping():
    now=datetime.now(timezone.utc)
    a=NewsItem(headline="BEL wins major order",source="wire",published_at=now,body="Bharat Electronics")
    b=NewsItem(headline="BEL wins major order!",source="other",published_at=now,symbols=["BEL"])
    assert len(deduplicate_news([a,b])) == 1
    assert map_news_to_symbols(a,{"Bharat Electronics":"BEL"}) == ["BEL"]
    assert score_news(a).impact > 0


def test_corporate_action_unknown_event_fails_closed():
    action=CorporateAction(symbol="ABC",action_type=ActionType.OTHER,
        announcement_date=datetime.now().date(),source="exchange")
    assert blocks_new_entry(action,datetime.now().date())


def test_paper_broker_is_idempotent():
    signal=Signal(strategy="test",symbol="ABC",direction="long",entry=Decimal(100),
        stop=Decimal(95),target=Decimal(110),confidence=.8,rationale="test")
    broker=PaperBroker(PaperExecutionConfig())
    one=broker.execute(signal,10,Decimal(100))
    two=broker.execute(signal,10,Decimal(100))
    assert one.fill_id == two.fill_id
    assert one.price > Decimal(100)


def test_ledger_marks_to_market_and_prevents_duplicate_fill():
    ledger=PortfolioLedger(Decimal(10000))
    fill=PaperFill(signal_id="s1",symbol="ABC",side="buy",quantity=10,price=Decimal(100),fees=Decimal(1))
    ledger.apply_buy(fill)
    ledger.apply_buy(fill)
    ledger.mark("ABC",Decimal(110))
    assert ledger.cash == Decimal(8999)
    assert ledger.equity == Decimal(10099)


@pytest.mark.asyncio
async def test_orchestrator_isolates_failures_and_runs_peers():
    async def ok():
        return 42
    async def bad():
        raise RuntimeError("broken agent")
    runner=AgentOrchestrator(max_parallel=2,retries=0)
    result=await runner.run_parallel({"ok":ok,"bad":bad})
    assert {r["status"] for r in result} == {"succeeded","failed"}
