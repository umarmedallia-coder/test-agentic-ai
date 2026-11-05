import pytest

from app.config import Settings
from app.models import TradeIntent
from app.services.risk import RiskManager
from app.services.workflow import build_strategy_graph


def test_risk_manager_rejects_drawdown_and_liquidity(tmp_path):
    settings = Settings(journal_dir=tmp_path)
    intent = TradeIntent(symbol="ABC",entry_price=100,stop_price=95,target_price=110,quantity=10)
    risk = RiskManager(settings)
    decision = risk.validate(intent,100_000,0,0,100_000,equity_peak=120_000,
                             candidate_sector="Industrials",
                             average_volume=100,max_participation_pct=.01)
    assert not decision.accepted
    assert any("drawdown" in reason.lower() for reason in decision.reasons)
    assert any("volume" in reason.lower() for reason in decision.reasons)


@pytest.mark.asyncio
async def test_langgraph_fanout_fanin_returns_partial_results():
    async def one():
        return "first"
    async def two():
        raise RuntimeError("isolated")
    graph = build_strategy_graph()
    result = await graph.ainvoke({"strategies":["one","two"],
                                  "tasks":{"one":one,"two":two},"results":[]})
    by_name = {item["name"]:item for item in result["results"]}
    assert by_name["one"]["status"] == "succeeded"
    assert by_name["two"]["status"] == "failed"


def test_risk_manager_enforces_daily_loss_and_lot_rounding(tmp_path):
    settings = Settings(journal_dir=tmp_path)
    intent = TradeIntent(
        symbol="ABC", entry_price=100, stop_price=95,
        target_price=110, quantity=25,
    )
    manager = RiskManager(settings)
    loss = manager.validate(intent, 100_000, -3_000, 0, 100_000)
    assert not loss.accepted
    lot = manager.validate(
        intent, 100_000, 0, 0, 100_000, lot_size=10,
        candidate_sector="Industrials",
        average_volume=100_000, max_participation_pct=0.01,
    )
    assert lot.accepted
    assert lot.approved_quantity == 20


@pytest.mark.asyncio
async def test_langgraph_strategy_nodes_execute_concurrently():
    import asyncio

    started = 0
    both_started = asyncio.Event()

    async def worker():
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return "done"

    graph = build_strategy_graph()
    result = await graph.ainvoke({
        "strategies": ["one", "two"],
        "tasks": {"one": worker, "two": worker},
        "results": [],
    })
    assert started == 2
    assert len(result["results"]) == 2
    assert all(item["status"] == "succeeded" for item in result["results"])


def test_risk_manager_enforces_sector_concentration_and_classification(tmp_path):
    settings = Settings(journal_dir=tmp_path, max_sector_exposure_pct=0.40)
    intent = TradeIntent(
        symbol="ABC", entry_price=100, stop_price=95,
        target_price=110, quantity=10,
    )
    manager = RiskManager(settings)
    concentrated = manager.validate(
        intent, 100_000, 0, 1, 100_000,
        candidate_sector="Energy", current_sector_exposure=39_500,
    )
    assert not concentrated.accepted
    assert any("sector concentration" in reason.lower() for reason in concentrated.reasons)
    unknown = manager.validate(intent, 100_000, 0, 0, 100_000)
    assert not unknown.accepted
    assert any("sector classification" in reason.lower() for reason in unknown.reasons)
    unclassified = manager.validate(
        intent, 100_000, 0, 1, 100_000,
        candidate_sector="Energy", unclassified_exposure=1_000,
    )
    assert not unclassified.accepted
    assert any("unclassified sector" in reason.lower() for reason in unclassified.reasons)
