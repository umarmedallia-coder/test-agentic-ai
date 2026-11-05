import pytest

from app.config import Settings
from app.models import TradeIntent
from app.services.engine import TradingEngine
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
    decision = RiskManager(settings).validate(intent, 100_000, 0, 0, 100_000)
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
