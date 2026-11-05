from decimal import Decimal

import pytest

from app.config import Settings
from app.contracts import CorporateActionRecord, PaperFill
from app.models import AgentResult, AgentStatus, Position
from app.services.engine import TradingEngine
from app.services.portfolio import PortfolioLedger


def fill(fill_id: str, side: str, quantity: int, price: str, fees: str = "1") -> PaperFill:
    return PaperFill(
        fill_id=fill_id,
        signal_id=f"signal-{fill_id}",
        symbol="ABC",
        side=side,
        quantity=quantity,
        price=Decimal(price),
        fees=Decimal(fees),
    )


def test_short_position_marks_as_liability_and_cover_realizes_net_pnl():
    ledger = PortfolioLedger(Decimal("10000"))
    entry = fill("short-entry", "short", 10, "100")
    ledger.apply_short(entry)
    ledger.mark("ABC", Decimal("80"))

    assert ledger.cash == Decimal("10999")
    assert ledger.unrealized_pnl == Decimal("199")
    assert ledger.equity == Decimal("10199")

    exit_fill = fill("short-cover", "cover", 10, "80")
    assert ledger.apply_cover(exit_fill) == Decimal("198")
    assert ledger.realized_pnl == Decimal("198")
    assert ledger.cash == Decimal("10198")
    assert ledger.equity == Decimal("10198")
    assert "ABC" not in ledger.positions
    assert ledger.apply_cover(exit_fill) == Decimal("0")


def test_short_position_partial_cover_allocates_entry_fees_proportionally():
    ledger = PortfolioLedger(Decimal("10000"))
    ledger.apply_short(fill("short-entry", "short", 10, "100", "2"))

    realized = ledger.apply_cover(fill("partial-cover", "cover", 4, "90", "1"))
    assert realized == Decimal("38.2")
    position = ledger.positions["ABC"]
    assert position.direction == "short"
    assert position.quantity == 6
    assert position.entry_fees == Decimal("1.2")


def test_short_position_pays_dividend_and_split_adjusts_quantity():
    ledger = PortfolioLedger(Decimal("10000"))
    ledger.apply_short(fill("short-entry", "short", 10, "100", "1"))

    assert ledger.apply_dividend("ABC", Decimal("5"), "dividend-1") == Decimal("-50")
    assert ledger.cash == Decimal("10949")
    assert ledger.realized_pnl == Decimal("-50")

    quantity, average_entry = ledger.apply_split(
        "ABC", Decimal("1"), Decimal("2"), action_id="split-1",
    )
    assert quantity == 20
    assert average_entry == Decimal("50")
    assert ledger.positions["ABC"].direction == "short"


def test_short_position_snapshot_restores_direction_and_idempotency():
    ledger = PortfolioLedger(Decimal("10000"))
    entry = fill("short-entry", "short", 10, "100")
    ledger.apply_short(entry)
    snapshot = ledger.snapshot()

    restored = PortfolioLedger()
    restored.restore(snapshot)
    assert restored.positions["ABC"].direction == "short"
    assert restored.cash == ledger.cash
    restored.apply_short(entry)
    assert restored.positions["ABC"].quantity == 10


def test_ledger_rejects_opposite_side_addition_and_wrong_cover():
    ledger = PortfolioLedger(Decimal("10000"))
    ledger.apply_short(fill("short-entry", "short", 10, "100"))

    with pytest.raises(ValueError, match="opposite-side"):
        ledger.apply_buy(fill("long-entry", "buy", 1, "90"))
    with pytest.raises(ValueError, match="no open short"):
        ledger.apply_cover(fill("bad-cover", "cover", 1, "90"))


def test_fractional_split_requires_price_then_settles_long_cash_in_lieu():
    ledger = PortfolioLedger(Decimal("10000"))
    ledger.apply_buy(fill("long-entry", "buy", 3, "100", "0"))
    before = ledger.snapshot()

    with pytest.raises(ValueError, match="cash-in-lieu"):
        ledger.apply_split("ABC", Decimal("2"), Decimal("3"), "split-fractional")
    assert ledger.snapshot() == before

    quantity, average_entry = ledger.apply_split(
        "ABC", Decimal("2"), Decimal("3"), "split-fractional",
        cash_in_lieu_price=Decimal("60"),
    )
    assert quantity == 4
    assert average_entry == Decimal("100") * Decimal("2") / Decimal("3")
    assert ledger.cash == Decimal("9730")
    assert ledger.realized_pnl == Decimal("0.5") * (
        Decimal("60") - average_entry
    )


def test_fractional_split_cash_in_lieu_for_short_position():
    ledger = PortfolioLedger(Decimal("10000"))
    ledger.apply_short(fill("short-entry", "short", 3, "100", "0"))

    quantity, average_entry = ledger.apply_split(
        "ABC", Decimal("2"), Decimal("3"), "short-split-fractional",
        cash_in_lieu_price=Decimal("60"),
    )
    assert quantity == 4
    assert average_entry == Decimal("100") * Decimal("2") / Decimal("3")
    assert ledger.cash == Decimal("10270")
    assert ledger.realized_pnl == Decimal("0.5") * (
        average_entry - Decimal("60")
    )


def test_engine_monitors_and_covers_short_position_with_adverse_stop_first(tmp_path):
    engine = TradingEngine(Settings(journal_dir=tmp_path))
    engine.start()
    entry = fill("engine-short-entry", "short", 10, "100", "0")
    engine.ledger.apply_short(entry)
    engine.positions = [Position(
        intent_id="engine-short-intent",
        symbol="ABC",
        exchange="NSE",
        direction="short",
        quantity=10,
        entry_price=100,
        stop_price=110,
        target_price=80,
        policy_version="paper-baseline-v1",
        strategy="test",
        entry_fill_id=entry.fill_id,
    )]
    engine.marks["ABC"] = 100
    engine.ledger.mark("ABC", Decimal("100"))

    # Both levels trade inside this OHLC bar; the adverse stop must win.
    engine._close_triggered_positions("ABC", {"low": 79, "high": 111})

    assert engine.positions == []
    assert len(engine.outcomes) == 1
    outcome = engine.outcomes[0]
    assert outcome.reason == "stop_loss"
    assert outcome.exit_price > Decimal("110")
    assert outcome.gross_pnl < 0
    assert outcome.net_pnl == outcome.gross_pnl - outcome.fees
    assert engine.ledger.positions == {}
    engine.stop()


def test_fractional_split_allocates_entry_fees_to_cash_in_lieu():
    ledger = PortfolioLedger(Decimal("10000"))
    ledger.apply_buy(fill("fee-bearing-entry", "buy", 3, "100", "3"))

    quantity, average_entry = ledger.apply_split(
        "ABC", Decimal("2"), Decimal("3"), "fee-bearing-split",
        cash_in_lieu_price=Decimal("60"),
    )
    fractional_fees = Decimal("3") * Decimal("0.5") / Decimal("4.5")
    assert quantity == 4
    assert ledger.realized_pnl == (
        Decimal("0.5") * (Decimal("60") - average_entry) - fractional_fees
    )
    assert ledger.positions["ABC"].entry_fees == Decimal("3") - fractional_fees


def test_engine_closes_entire_position_when_reverse_split_is_fully_fractional(tmp_path):
    engine = TradingEngine(Settings(journal_dir=tmp_path, initial_capital_inr=10000))
    engine.start()
    entry = fill("reverse-split-entry", "buy", 1, "100", "0")
    engine.ledger.apply_buy(entry)
    engine.positions = [Position(
        intent_id="reverse-split-intent",
        symbol="ABC",
        exchange="NSE",
        direction="long",
        quantity=1,
        entry_price=100,
        stop_price=90,
        target_price=120,
        policy_version="paper-baseline-v1",
        strategy="test",
        entry_fill_id=entry.fill_id,
    )]
    now = datetime.now().astimezone()
    action = CorporateActionRecord(
        action_id="reverse-split-1",
        symbol="ABC",
        action_type="split",
        announcement_date=now,
        ex_date=now,
        source="verified-exchange-feed",
        verified=True,
        ratio_from=Decimal("2"),
        ratio_to=Decimal("1"),
        cash_in_lieu_price=Decimal("60"),
    )
    agent = AgentResult(
        agent_name="Corporate Actions Agent",
        status=AgentStatus.SUCCEEDED,
        symbol="ABC",
        conclusion="Verified reverse split and cash-in-lieu price.",
        findings={"actions": [action.model_dump(mode="json")]},
        is_mock=False,
    )

    blocked = engine._apply_due_corporate_actions(agent, "ABC", now.date())

    assert not blocked
    assert engine.positions == []
    assert engine.ledger.positions == {}
    assert engine.cash == 9930
    assert engine.realized_pnl == -70
    assert engine.daily_realized_pnl == -70
    engine.stop()
