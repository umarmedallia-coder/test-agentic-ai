from datetime import UTC, datetime
from decimal import Decimal

from app.config import Settings
from app.contracts import PaperFill, TradeOutcome
from app.models import Position
from app.services.engine import TradingEngine


def test_recovery_replays_uncommitted_entry_and_exit_write_ahead_events(tmp_path):
    settings = Settings(journal_dir=tmp_path, initial_capital_inr=10_000)
    crashed = TradingEngine(settings)
    crashed.start()

    opened_at = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    closed_at = datetime(2026, 11, 5, 11, 0, tzinfo=UTC)
    entry = PaperFill(
        fill_id="replay-entry-fill", signal_id="replay-entry",
        symbol="ABC", side="buy", quantity=10,
        price=Decimal("100"), fees=Decimal("1"), filled_at=opened_at,
    )
    position = Position(
        intent_id="replay-entry", symbol="ABC", exchange="NSE",
        direction="long", quantity=10, entry_price=100,
        stop_price=95, target_price=110, policy_version="paper-baseline-v1",
        strategy="technical", opened_at=opened_at, entry_fees=1,
        entry_fill_id=entry.fill_id,
    )
    crashed.journal.append({
        "type": "paper_fill", "fill": entry.model_dump(mode="json"),
        "position": position.model_dump(mode="json"),
        "intent_id": position.intent_id,
    })

    exit_fill = PaperFill(
        fill_id="replay-exit-fill", signal_id="replay-exit",
        symbol="ABC", side="short", quantity=10,
        price=Decimal("110"), fees=Decimal("1"), filled_at=closed_at,
    )
    outcome = TradeOutcome(
        fill_id=entry.fill_id, entry_fill_id=entry.fill_id,
        exit_fill_id=exit_fill.fill_id, symbol="ABC",
        entry_price=Decimal("100"), exit_price=Decimal("110"),
        quantity=10, gross_pnl=Decimal("100"), fees=Decimal("2"),
        net_pnl=Decimal("98"), reason="take_profit",
        policy_version="paper-baseline-v1", strategy="technical",
        entry_at=opened_at, closed_at=closed_at,
    )
    crashed.journal.append({
        "type": "position_closed", "intent_id": position.intent_id,
        "exit_fill": exit_fill.model_dump(mode="json"),
        "outcome": outcome.model_dump(mode="json"),
        "reason": "take_profit", "net_pnl": 98,
        "at": closed_at.isoformat(),
    })

    # Simulate process death before either portfolio snapshot is written.
    crashed.journal.release()

    recovered = TradingEngine(settings)
    recovered.start()
    assert recovered.positions == []
    assert recovered.ledger.positions == {}
    assert recovered.cash == 10_098
    assert recovered.realized_pnl == 98
    assert recovered.daily_realized_pnl == 98
    assert recovered.fees_paid == 2
    assert len(recovered.outcomes) == 1
    assert recovered.outcomes[0].exit_fill_id == exit_fill.fill_id
    recovered.stop()

    # A second restart must not replay either fill twice.
    restarted = TradingEngine(settings)
    restarted.start()
    assert restarted.positions == []
    assert restarted.cash == 10_098
    assert restarted.realized_pnl == 98
    assert len(restarted.outcomes) == 1
    restarted.stop()
