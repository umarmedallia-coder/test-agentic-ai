from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.config import Settings
from app.contracts import CompanyProfile, CorporateActionRecord, DataEnvelope, NewsRecord, PaperFill
from app.models import AgentResult, AgentStatus, Position, TradeIntent
from app.services.engine import TradingEngine
from app.services.learning import CandidateEvaluation, PaperPolicy
from app.services.journal import JournalError, JsonlJournal
from app.services.risk import RiskManager


def test_trade_intent_validates_direction():
    with pytest.raises(ValueError):
        TradeIntent(symbol="ABC", entry_price=100, stop_price=101,
                    target_price=110, quantity=1)


def test_journal_exclusive_lock_and_corruption(tmp_path):
    one, two = JsonlJournal(tmp_path), JsonlJournal(tmp_path)
    one.acquire()
    with pytest.raises(JournalError):
        two.acquire()
    one.release()
    one.path.write_text('{"valid":true}\nnot-json\n', encoding="utf-8")
    with pytest.raises(JournalError, match="line 2"):
        one.read_all()


def test_risk_manager_rejects_oversized_unit(tmp_path):
    settings = Settings(journal_dir=tmp_path, initial_capital_inr=100_000)
    intent = TradeIntent(symbol="ABC", entry_price=1000, stop_price=900,
                         target_price=1200, quantity=10)
    decision = RiskManager(settings).validate(intent, 100_000, 0, 0, 5_000)
    assert not decision.accepted


def test_engine_start_stop_and_cycle(tmp_path):
    engine = TradingEngine(Settings(journal_dir=tmp_path))
    engine.start()
    engine.start()
    engine.run_cycle()
    assert engine.last_cycle_at is not None
    assert engine.journal.read_all()[0]["type"] == "engine_started"
    engine.stop()
    assert engine.state == "stopped"


def test_engine_restores_open_positions_after_restart(tmp_path, monkeypatch):
    settings = Settings(journal_dir=tmp_path)
    intent = TradeIntent(
        symbol="RELIANCE", entry_price=100, stop_price=90,
        target_price=120, quantity=1,
    )
    agent = AgentResult(
        agent_name="Technical Analysis Agent", status=AgentStatus.SUCCEEDED,
        symbol="RELIANCE", conclusion="test signal",
    )
    monkeypatch.setattr(
        "app.services.engine.analyze_technical",
        lambda symbol, exchange, bars: (agent, intent),
    )
    first = TradingEngine(settings)

    async def market_open(day):
        return DataEnvelope(
            source="test", as_of=datetime.now(UTC), payload={"is_open": True},
        )

    monkeypatch.setattr(first.provider, "get_trading_calendar", market_open)
    first.policy_registry.promote(
        PaperPolicy(
            version="paper-v2", parent_version="paper-baseline-v1",
            parameters={"ema_fast": 8},
        ),
        CandidateEvaluation(
            accepted=True, candidate_version="paper-v2",
            baseline_version="paper-baseline-v1", training_samples=100,
            candidate_validation_samples=100, baseline_validation_samples=100,
            candidate_net_pnl=Decimal("200"), baseline_net_pnl=Decimal("100"),
        ),
    )
    first.start()
    first.run_cycle()
    assert len(first.positions) == 1
    saved_cash = first.cash
    first.stop()

    second = TradingEngine(settings)
    second.start()
    assert len(second.positions) == 1
    assert second.cash == saved_cash
    second.stop()


def test_news_mode_skips_when_mock_feed_is_empty(tmp_path):
    engine = TradingEngine(Settings(journal_dir=tmp_path, strategy_mode="news"))
    engine.start()
    engine.run_cycle()
    assert engine.agents[1].status.value == "skipped"
    assert engine.positions == []
    engine.stop()


def test_automatic_scheduler_runs_and_drains_on_stop(tmp_path, monkeypatch):
    from threading import Event

    engine = TradingEngine(Settings(journal_dir=tmp_path, cycle_interval_seconds=5))
    cycle_ran = Event()

    def fake_cycle(symbol="RELIANCE", exchange="NSE"):
        cycle_ran.set()

    monkeypatch.setattr(engine, "run_cycle", fake_cycle)
    engine.start(automatic=True)
    assert cycle_ran.wait(timeout=2)
    engine.stop()
    assert not engine.snapshot()["scheduler_active"]


def test_stop_first_exit_persists_closed_portfolio(tmp_path):
    from app.models import Position

    engine = TradingEngine(Settings(journal_dir=tmp_path))
    engine.start()
    engine.cash = 10_000
    engine.ledger.apply_buy(PaperFill(
        fill_id="entry-fill-1", signal_id="intent-1", symbol="RELIANCE",
        side="buy", quantity=10, price=Decimal("100"), fees=Decimal("1"),
    ))
    engine.positions = [Position(
        intent_id="intent-1", symbol="RELIANCE", exchange="NSE",
        direction="long", quantity=10, entry_price=100,
        stop_price=95, target_price=110, policy_version="test",
        entry_fees=1, entry_fill_id="entry-fill-1",
    )]
    engine.marks["RELIANCE"] = 100
    engine.ledger.mark("RELIANCE", Decimal("100"))
    engine._close_triggered_positions(
        "RELIANCE", {"low": 94, "high": 111},
    )
    assert engine.positions == []
    assert len(engine.outcomes) == 1
    events = engine.journal.read_all()
    snapshots = [event for event in events if event["type"] == "portfolio_snapshot"]
    assert snapshots[-1]["positions"] == []
    closed = [event for event in events if event["type"] == "position_closed"]
    assert closed[-1]["reason"] == "stop_loss"
    engine.stop()

    recovered = TradingEngine(Settings(journal_dir=tmp_path))
    recovered.start()
    assert len(recovered.outcomes) == 1
    assert recovered.learning_report().sample_count == 1
    recovered.stop()


def test_closed_market_calendar_blocks_new_entries(tmp_path, monkeypatch):
    intent = TradeIntent(
        symbol="RELIANCE", entry_price=100, stop_price=90,
        target_price=120, quantity=1,
    )
    agent = AgentResult(
        agent_name="Technical Analysis Agent", status=AgentStatus.SUCCEEDED,
        symbol="RELIANCE", conclusion="test signal",
    )
    monkeypatch.setattr(
        "app.services.engine.analyze_technical",
        lambda symbol, exchange, bars: (agent, intent),
    )
    engine = TradingEngine(Settings(journal_dir=tmp_path))

    async def market_closed(day):
        return DataEnvelope(
            source="test", as_of=datetime.now(UTC), payload={"is_open": False},
        )

    monkeypatch.setattr(engine.provider, "get_trading_calendar", market_closed)
    engine.start()
    engine.run_cycle()
    assert engine.positions == []
    assert any(
        event.get("reason") == "market calendar is closed or unavailable"
        for event in engine.journal.read_all()
    )
    engine.stop()


def test_corporate_action_restriction_blocks_technical_entry(tmp_path, monkeypatch):
    intent = TradeIntent(
        symbol="RELIANCE", entry_price=100, stop_price=90,
        target_price=120, quantity=1,
    )
    agent = AgentResult(
        agent_name="Technical Analysis Agent", status=AgentStatus.SUCCEEDED,
        symbol="RELIANCE", conclusion="test signal",
    )
    monkeypatch.setattr(
        "app.services.engine.analyze_technical",
        lambda symbol, exchange, bars: (agent, intent),
    )
    engine = TradingEngine(Settings(journal_dir=tmp_path))

    async def market_open(day):
        return DataEnvelope(
            source="test", as_of=datetime.now(UTC), payload={"is_open": True},
        )

    async def action_feed(symbol):
        now = datetime.now(UTC)
        action = CorporateActionRecord(
            action_id="action-1", symbol=symbol, action_type="dividend",
            announcement_date=now, ex_date=now, source="exchange",
            verified=True, cash_amount=Decimal("2"),
        )
        return DataEnvelope(source="test", as_of=now, payload=[action])

    monkeypatch.setattr(engine.provider, "get_trading_calendar", market_open)
    monkeypatch.setattr(engine.provider, "get_corporate_actions", action_feed)
    engine.start()
    engine.run_cycle()
    assert engine.positions == []
    assert any(
        event.get("reason") == "corporate_action"
        for event in engine.journal.read_all()
    )
    engine.stop()


def test_combined_mode_runs_parallel_evidence_and_reconciles_intents(tmp_path, monkeypatch):
    from datetime import timedelta

    from app.data.mock_provider import MockMarketDataProvider

    now = datetime.now(UTC)
    technical_intent = TradeIntent(
        symbol="BEL", entry_price=100, stop_price=95,
        target_price=110, quantity=1, confidence=0.5,
        source_agent="Technical Analysis Agent",
    )
    technical_agent = AgentResult(
        agent_name="Technical Analysis Agent", status=AgentStatus.SUCCEEDED,
        symbol="BEL", conclusion="deterministic technical signal",
        findings={"atr_14": 2.0},
    )
    monkeypatch.setattr(
        "app.services.engine.analyze_technical",
        lambda symbol, exchange, bars: (technical_agent, technical_intent),
    )

    class CombinedProvider(MockMarketDataProvider):
        async def get_trading_calendar(self, day):
            return DataEnvelope(
                source="test", as_of=now, payload={"is_open": True},
            )

        async def get_stock_news(self, symbol, since=None):
            return DataEnvelope(
                source="test", as_of=now,
                payload=[NewsRecord(
                    news_id="news-1",
                    headline="BEL profit rises, upgrade approval, order win",
                    body="Bharat Electronics",
                    source="exchange", published_at=now, symbols=[],
                )],
            )

        async def get_company_profile(self, symbol):
            return DataEnvelope(
                source="test", as_of=now,
                payload=CompanyProfile(
                    symbol=symbol, company_name="Bharat Electronics",
                    exchange="NSE", source="exchange",
                ),
            )

        async def get_corporate_actions(self, symbol):
            return DataEnvelope(
                source="test", as_of=now,
                payload=[CorporateActionRecord(
                    action_id="future-dividend", symbol=symbol,
                    action_type="dividend", announcement_date=now,
                    ex_date=now + timedelta(days=10), source="exchange",
                    verified=True, cash_amount=Decimal("1"),
                )],
            )

    engine = TradingEngine(Settings(
        strategy_mode="combined", journal_dir=tmp_path,
    ))
    engine.provider = CombinedProvider()
    engine.start()
    engine.run_cycle(symbol="BEL")

    assert len(engine.positions) == 1, {
        "agents": [agent.model_dump(mode="json") for agent in engine.agents],
        "errors": engine.errors,
        "events": engine.journal.read_all(),
    }
    assert engine.positions[0].symbol == "BEL"
    assert engine.positions[0].policy_version == "paper-baseline-v1"
    assert {agent.agent_name for agent in engine.agents} >= {
        "Technical Analysis Agent", "News Intelligence Agent",
        "News-to-Stock Impact Mapping Agent", "Corporate Actions Agent",
        "Risk Management Agent",
    }
    assert engine.positions[0].entry_price > 100
    engine.stop()


def test_engine_applies_split_and_dividend_actions_once(tmp_path):
    from datetime import timedelta

    from app.contracts import PaperFill

    engine = TradingEngine(Settings(journal_dir=tmp_path))
    now = datetime.now(UTC)
    entry_fill = PaperFill(
        signal_id="entry", symbol="ABC", side="buy",
        quantity=10, price=Decimal("100"), fees=Decimal("1"),
    )
    engine.ledger.apply_buy(entry_fill)
    engine.ledger.mark("ABC", Decimal("100"))
    engine.marks["ABC"] = 100.0
    engine.positions.append(Position(
        symbol="ABC", quantity=10, entry_price=100,
        stop_price=90, target_price=120, mark=100,
        opened_at=now - timedelta(days=2),
        entry_fees=1, entry_fill_id=entry_fill.fill_id,
        intent_id="entry-intent",
    ))
    split = CorporateActionRecord(
        action_id="split-1", symbol="ABC", action_type="split",
        announcement_date=now - timedelta(days=5), ex_date=now,
        source="exchange", verified=True,
        ratio_from=Decimal("1"), ratio_to=Decimal("2"),
    )
    dividend = CorporateActionRecord(
        action_id="dividend-1", symbol="ABC", action_type="dividend",
        announcement_date=now - timedelta(days=5), ex_date=now,
        source="exchange", verified=True, cash_amount=Decimal("2"),
    )
    agent = AgentResult(
        agent_name="Corporate Actions Agent", status=AgentStatus.SUCCEEDED,
        symbol="ABC", findings={
            "actions": [
                split.model_dump(mode="json"),
                dividend.model_dump(mode="json"),
            ],
        },
    )
    assert not engine._apply_due_corporate_actions(agent, "ABC", now.date())
    assert engine.positions[0].quantity == 20
    assert engine.positions[0].entry_price == 50
    assert engine.positions[0].stop_price == 45
    assert engine.positions[0].target_price == 60
    assert engine.ledger.positions["ABC"].quantity == 20
    assert engine.ledger.cash == Decimal("9039")
    assert engine.realized_pnl == 40
    assert engine.processed_corporate_actions == {"split-1", "dividend-1"}

    # Reprocessing the same source records must not adjust shares or cash twice.
    engine._apply_due_corporate_actions(agent, "ABC", now.date())
    assert engine.positions[0].quantity == 20
    assert engine.ledger.cash == Decimal("9039")
