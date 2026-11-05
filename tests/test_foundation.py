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
        findings={"signal": "bullish"},
    )
    monkeypatch.setattr(
        "app.services.engine.analyze_technical",
        lambda symbol, exchange, bars, policy=None, **kwargs: (agent, intent),
    )
    first = TradingEngine(settings)

    async def market_open(day, exchange="NSE"):
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
    news_agent = next(item for item in engine.agents if item.agent_name == "News Intelligence Agent")
    assert news_agent.status.value == "skipped"
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
        stop_price=95, target_price=110, policy_version="paper-baseline-v1",
        entry_fees=1, entry_fill_id="entry-fill-1",
    )]
    engine.marks["RELIANCE"] = 100
    engine.ledger.mark("RELIANCE", Decimal("100"))
    engine._close_triggered_positions(
        "RELIANCE", {"low": 94, "high": 111},
    )
    assert engine.positions == []
    assert len(engine.outcomes) == 1
    assert engine.outcomes[0].policy_version == "paper-baseline-v1"
    assert engine.outcomes[0].strategy == "unknown"
    assert engine.outcomes[0].entry_at is not None
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
        findings={"signal": "bullish"},
    )
    monkeypatch.setattr(
        "app.services.engine.analyze_technical",
        lambda symbol, exchange, bars, policy=None, **kwargs: (agent, intent),
    )
    engine = TradingEngine(Settings(journal_dir=tmp_path))

    async def market_closed(day, exchange="NSE"):
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
        findings={"signal": "bullish"},
    )
    monkeypatch.setattr(
        "app.services.engine.analyze_technical",
        lambda symbol, exchange, bars, policy=None, **kwargs: (agent, intent),
    )
    engine = TradingEngine(Settings(journal_dir=tmp_path))

    async def market_open(day, exchange="NSE"):
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
        findings={"atr_14": 2.0, "signal": "bullish"},
    )
    monkeypatch.setattr(
        "app.services.engine.analyze_technical",
        lambda symbol, exchange, bars, policy=None, **kwargs: (technical_agent, technical_intent),
    )

    class CombinedProvider(MockMarketDataProvider):
        async def get_trading_calendar(self, day, exchange="NSE"):
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
                    symbol=symbol, company_name="Bharat Electronics", sector="Industrials",
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

    engine = TradingEngine(Settings(initial_capital_inr=10_000, journal_dir=tmp_path))
    now = datetime.now(UTC)
    entry_fill = PaperFill(
        signal_id="entry", symbol="ABC", side="buy",
        quantity=10, price=Decimal("100"), fees=Decimal("1"),
    )
    engine.ledger.apply_buy(entry_fill)
    engine.ledger.mark("ABC", Decimal("100"))
    engine.marks["ABC"] = 100.0
    engine.positions.append(Position(
        symbol="ABC", exchange="NSE", direction="long", quantity=10,
        entry_price=100, stop_price=90, target_price=120,
        policy_version="paper-baseline-v1",
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
        symbol="ABC", conclusion="Verified corporate actions available.",
        findings={
            "actions": [
                split.model_dump(mode="json"),
                dividend.model_dump(mode="json"),
            ],
        },
    )
    engine.start()
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
    engine.stop()

    recovered = TradingEngine(Settings(
        initial_capital_inr=10_000, journal_dir=tmp_path,
    ))
    recovered.start()
    assert recovered.processed_corporate_actions == {"split-1", "dividend-1"}
    recovered._apply_due_corporate_actions(agent, "ABC", now.date())
    assert recovered.positions[0].quantity == 20
    assert recovered.ledger.cash == Decimal("9039")
    recovered.stop()


def test_risk_manager_enforces_configured_gross_exposure_cap(tmp_path):
    settings = Settings(
        journal_dir=tmp_path, initial_capital_inr=100_000,
        max_gross_exposure_pct=0.80,
    )
    intent = TradeIntent(
        symbol="ABC", entry_price=100, stop_price=90,
        target_price=120, quantity=10,
    )
    manager = RiskManager(settings)
    at_limit = manager.validate(
        intent, 100_000, 0, 0, 100_000,
        current_exposure=80_000, average_volume=100_000,
    )
    crossing_limit = manager.validate(
        intent, 100_000, 0, 0, 100_000,
        current_exposure=79_500, average_volume=100_000,
    )
    assert not at_limit.accepted
    assert any("gross exposure" in reason.lower() for reason in at_limit.reasons)
    assert not crossing_limit.accepted
    assert any("would be exceeded" in reason for reason in crossing_limit.reasons)


def test_risk_manager_rejects_non_finite_and_negative_account_inputs(tmp_path):
    manager = RiskManager(Settings(journal_dir=tmp_path))
    intent = TradeIntent(
        symbol="ABC", entry_price=100, stop_price=90,
        target_price=120, quantity=1,
    )
    non_finite = manager.validate(intent, float("nan"), 0, 0, 100_000)
    negative_cash = manager.validate(intent, 100_000, 0, 0, -1)
    assert not non_finite.accepted
    assert "finite" in non_finite.reasons[0]
    assert not negative_cash.accepted
    assert any("cannot be negative" in reason for reason in negative_cash.reasons)


def test_intent_idempotency_key_is_stable_for_the_same_completed_bar():
    from datetime import timedelta

    intent = TradeIntent(
        symbol="RELIANCE", entry_price=100, stop_price=90,
        target_price=120, quantity=1, policy_version="paper-v1",
    )
    timestamp = datetime.now(UTC)
    first = TradingEngine._stable_intent_id(intent, timestamp)
    repeated = TradingEngine._stable_intent_id(intent, timestamp)
    next_bar = TradingEngine._stable_intent_id(intent, timestamp + timedelta(minutes=1))
    assert first == repeated
    assert first != next_bar


def test_engine_fails_closed_on_stale_typed_historical_data(tmp_path):
    from app.data.mock_provider import MockMarketDataProvider

    class StaleHistoryProvider(MockMarketDataProvider):
        async def get_historical_prices(self, symbol, start, end, exchange="NSE"):
            return DataEnvelope(
                source="test-stale", as_of=datetime.now(UTC),
                status="stale", payload=[], is_mock=False,
            )

    engine = TradingEngine(Settings(journal_dir=tmp_path))
    engine.provider = StaleHistoryProvider()
    engine.start()
    engine.run_cycle()
    assert engine.positions == []
    assert engine.agents[0].status == AgentStatus.FAILED
    assert any(
        event.get("type") == "market_data_rejected"
        for event in engine.journal.read_all()
    )
    engine.stop()


def test_engine_rejects_over_age_typed_history_even_when_provider_marks_ok(tmp_path):
    from app.data.mock_provider import MockMarketDataProvider

    class OverAgeHistoryProvider(MockMarketDataProvider):
        async def get_historical_prices(self, symbol, start, end, exchange="NSE"):
            original = await super().get_historical_prices(symbol, start, end, exchange)
            return DataEnvelope(
                source=original.source, as_of=original.as_of,
                payload=original.payload, status="ok", is_mock=original.is_mock,
                freshness_seconds=900_000,
            )

    engine = TradingEngine(Settings(
        journal_dir=tmp_path, max_market_data_freshness_seconds=86_400,
    ))
    engine.provider = OverAgeHistoryProvider()
    engine.start()
    engine.run_cycle()
    assert engine.positions == []
    assert engine.agents[0].status == AgentStatus.FAILED
    assert "freshness_seconds=900000" in engine.agents[0].errors[0]
    engine.stop()


def test_risk_manager_enforces_single_symbol_concentration_cap(tmp_path):
    settings = Settings(
        journal_dir=tmp_path, initial_capital_inr=100_000,
        max_single_position_exposure_pct=0.25,
    )
    intent = TradeIntent(
        symbol="ABC", entry_price=100, stop_price=90,
        target_price=120, quantity=10,
    )
    decision = RiskManager(settings).validate(
        intent, 100_000, 0, 1, 100_000,
        current_exposure=24_500, current_symbol_exposure=24_500,
        average_volume=100_000,
    )
    assert not decision.accepted
    assert "Single-symbol concentration limit would be exceeded" in decision.reasons


def test_portfolio_intelligence_reports_concentration_and_missing_marks():
    from app.services.portfolio_intelligence import analyze_portfolio

    position = Position(
        intent_id="intent-1", symbol="ABC", exchange="NSE", direction="long",
        quantity=300, entry_price=100, stop_price=90, target_price=120,
        policy_version="paper-v1",
    )
    result = analyze_portfolio(
        [position], {"ABC": 100}, 100_000, 70_000,
        max_single_position_exposure_pct=0.25,
    )
    assert result.agent_name == "Portfolio Intelligence Agent"
    assert result.status == AgentStatus.FAILED
    assert result.findings["symbol_concentration_pct"]["ABC"] == 0.3
    assert "ABC" in result.findings["concentration_breaches"]

    missing = analyze_portfolio(
        [position], {}, 100_000, 70_000,
        max_single_position_exposure_pct=0.25,
    )
    assert missing.status == AgentStatus.FAILED
    assert missing.findings["unmarked_symbols"] == ["ABC"]


def test_engine_exposes_portfolio_intelligence_agent_each_cycle(tmp_path):
    engine = TradingEngine(Settings(journal_dir=tmp_path))
    engine.start()
    engine.run_cycle()
    agent = next(
        item for item in engine.agents
        if item.agent_name == "Portfolio Intelligence Agent"
    )
    assert agent.status in {AgentStatus.SUCCEEDED, AgentStatus.FAILED}
    assert "gross_exposure_pct" in agent.findings
    engine.stop()


def test_snapshot_keeps_missing_position_marks_unavailable(tmp_path):
    from app.models import Position

    engine = TradingEngine(Settings(journal_dir=tmp_path))
    engine.start()
    fill = PaperFill(
        fill_id="missing-mark-entry", signal_id="missing-mark-intent",
        symbol="RELIANCE", side="buy", quantity=1, price=Decimal("100"),
    )
    engine.ledger.apply_buy(fill)
    engine.ledger.positions["RELIANCE"].mark = None
    engine.positions = [Position(
        intent_id="missing-mark-intent", symbol="RELIANCE", exchange="NSE",
        direction="long", quantity=1, entry_price=100, stop_price=95,
        target_price=110, policy_version="test", entry_fill_id=fill.fill_id,
    )]
    snapshot = engine.snapshot()
    assert snapshot["equity"] is None
    assert snapshot["daily_pnl"] is None
    assert snapshot["open_trades"][0]["mark_status"] == "missing"
    assert snapshot["open_trades"][0]["unrealized_pnl"] is None
    engine.stop()


def test_on_demand_discovery_scans_a_bounded_universe_and_journals(tmp_path):
    engine = TradingEngine(Settings(journal_dir=tmp_path, discovery_max_symbols=3))
    engine.start()
    result = engine.run_stock_discovery()
    assert result.status == AgentStatus.SUCCEEDED
    assert result.findings["universe_count"] == 5
    assert result.findings["scanned_count"] == 3
    assert result.is_mock is True
    assert any(event["type"] == "stock_discovery_completed" for event in engine.journal.read_all())
    engine.stop()


def test_discovery_requires_running_engine_and_bounded_limit(tmp_path):
    engine = TradingEngine(Settings(journal_dir=tmp_path))
    with pytest.raises(RuntimeError, match="Engine must be running"):
        engine.run_stock_discovery()
    engine.start()
    with pytest.raises(ValueError, match="between 1 and 500"):
        engine.run_stock_discovery(limit=0)
    engine.stop()
