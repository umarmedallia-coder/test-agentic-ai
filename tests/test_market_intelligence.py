from datetime import UTC, datetime

import pytest

from app.contracts import DataEnvelope
from app.data.mock_provider import MockMarketDataProvider
from app.models import AgentStatus
from app.services.market_intelligence import run_market_intelligence


class IndexProvider(MockMarketDataProvider):
    def __init__(self, payload, *, status="ok", freshness=0):
        super().__init__()
        self.payload = payload
        self.status = status
        self.freshness = freshness

    async def get_market_indices(self):
        return DataEnvelope(
            source="test-index", as_of=datetime.now(UTC),
            payload=self.payload, status=self.status,
            freshness_seconds=self.freshness, is_mock=False,
        )


@pytest.mark.asyncio
async def test_market_intelligence_classifies_risk_on_from_two_benchmarks():
    result = await run_market_intelligence(
        IndexProvider({"NIFTY 50": 0.8, "BANK NIFTY": 0.6}),
        max_freshness_seconds=60,
    )
    assert result.status == AgentStatus.SUCCEEDED
    assert result.findings["regime"] == "risk_on"
    assert result.findings["nifty_return_pct"] == 0.8
    assert result.evidence[0].source == "test-index"


@pytest.mark.asyncio
async def test_market_intelligence_classifies_risk_off_only_on_confirmed_negative_pair():
    result = await run_market_intelligence(
        IndexProvider({"NIFTY 50": -0.9, "BANK NIFTY": -0.7}),
        max_freshness_seconds=60,
    )
    assert result.findings["regime"] == "risk_off"


@pytest.mark.asyncio
async def test_market_intelligence_does_not_infer_missing_benchmark():
    result = await run_market_intelligence(
        IndexProvider({"NIFTY 50": 1.2}),
        max_freshness_seconds=60,
    )
    assert result.status == AgentStatus.SUCCEEDED
    assert result.findings["regime"] == "mixed_or_unclear"
    assert result.findings["bank_nifty_return_pct"] is None


@pytest.mark.asyncio
async def test_market_intelligence_fails_closed_on_stale_or_unavailable_data():
    stale = await run_market_intelligence(
        IndexProvider({"NIFTY 50": 1.0, "BANK NIFTY": 1.0}, freshness=61),
        max_freshness_seconds=60,
    )
    unavailable = await run_market_intelligence(
        IndexProvider({}, status="empty"),
        max_freshness_seconds=60,
    )
    assert stale.status == AgentStatus.FAILED
    assert unavailable.status == AgentStatus.FAILED


@pytest.mark.asyncio
async def test_market_intelligence_ignores_non_finite_benchmark_values():
    result = await run_market_intelligence(
        IndexProvider({"NIFTY 50": float("nan"), "BANK NIFTY": float("inf")}),
        max_freshness_seconds=60,
    )
    assert result.status == AgentStatus.FAILED
    assert result.findings == {}


@pytest.mark.asyncio
async def test_engine_cycle_publishes_market_intelligence_agent(tmp_path):
    from app.config import Settings
    from app.services.engine import TradingEngine

    engine = TradingEngine(Settings(journal_dir=tmp_path))
    engine.start()
    import asyncio
    await asyncio.to_thread(engine.run_cycle)
    market_agent = next(
        item for item in engine.agents
        if item.agent_name == "Market Intelligence Agent"
    )
    assert market_agent.status in {AgentStatus.SUCCEEDED, AgentStatus.FAILED}
    assert "regime" in market_agent.findings
    agents = {item.agent_name: item for item in engine.agents}
    assert agents["Fundamental Analysis Agent"].status == AgentStatus.SKIPPED
    assert agents["Institutional Activity Agent"].status == AgentStatus.SKIPPED
    assert agents["Stock Discovery Agent"].status == AgentStatus.SUCCEEDED
    assert agents["Strategy Agent"].status == AgentStatus.SUCCEEDED
    assert agents["News Intelligence Agent"].status == AgentStatus.SKIPPED
    assert agents["News-to-Stock Impact Mapping Agent"].status == AgentStatus.SKIPPED
    expected_agents = {
        "Market Intelligence Agent", "Technical Analysis Agent", "Fundamental Analysis Agent",
        "News Intelligence Agent", "Corporate Actions Agent", "Institutional Activity Agent",
        "Risk Management Agent", "Stock Discovery Agent", "Strategy Agent",
        "Portfolio Intelligence Agent", "Debate/Critic Agent",
        "Recommendation Synthesis Agent", "News-to-Stock Impact Mapping Agent",
    }
    assert expected_agents.issubset(agents)
    engine.stop()
