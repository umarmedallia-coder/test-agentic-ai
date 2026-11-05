from datetime import datetime, timedelta, timezone

from app.agents.contracts import DiscoveryCandidate, FundamentalSnapshot, InstitutionalSnapshot
from app.agents.critic import critique_evidence
from app.agents.fundamental import analyze_fundamentals
from app.agents.institutional_activity import analyze_institutional_activity
from app.agents.stock_discovery import discover_stocks
from app.agents.strategy import evaluate_strategy
from app.agents.synthesis import synthesize_recommendation
from app.models import AgentResult, AgentStatus, RiskDecision, TradeIntent

NOW = datetime.now(timezone.utc)


def test_fundamental_agent_scores_only_supplied_metrics():
    snapshot = FundamentalSnapshot(symbol="INFY", as_of=NOW, source="test-feed",
        revenue_growth_pct=12, earnings_growth_pct=18, roe_pct=20, debt_to_equity=0.1)
    result = analyze_fundamentals(snapshot)
    assert result.status == AgentStatus.SUCCEEDED
    assert 0 <= result.findings["quality_score"] <= 100
    assert result.findings["metrics"]["revenue_growth_pct"] == 12
    assert result.evidence


def test_fundamental_agent_skips_insufficient_or_stale_data():
    thin = FundamentalSnapshot(symbol="INFY", as_of=NOW, source="test", roe_pct=14)
    assert analyze_fundamentals(thin).status == AgentStatus.SKIPPED
    stale = FundamentalSnapshot(symbol="INFY", as_of=NOW-timedelta(days=300), source="test",
        revenue_growth_pct=10, earnings_growth_pct=10, roe_pct=15)
    assert analyze_fundamentals(stale).status == AgentStatus.SKIPPED


def test_institutional_agent_reports_context_not_trade_instruction():
    result = analyze_institutional_activity(InstitutionalSnapshot(
        symbol="BEL", as_of=NOW, source="exchange-file", fii_net_value=100,
        dii_net_value=-20, delivery_pct=55, volume_ratio=1.4))
    assert result.status == AgentStatus.SUCCEEDED
    assert result.findings["flow_direction"] == "positive"
    assert "no standalone trade instruction" in result.conclusion


def test_stock_discovery_filters_stale_and_illiquid_candidates():
    candidates = [
        DiscoveryCandidate(symbol="BEL", last_price=300, average_daily_turnover=50_000_000,
            atr_pct=2.5, trend_direction="bullish", trend_strength=.8,
            data_as_of=NOW, source="test"),
        DiscoveryCandidate(symbol="XYZ", last_price=20, average_daily_turnover=100,
            atr_pct=2, trend_direction="bullish", trend_strength=.9,
            data_as_of=NOW, source="test"),
    ]
    result = discover_stocks(candidates)
    assert result.findings["eligible_count"] == 1
    assert result.findings["candidates"][0]["symbol"] == "BEL"
    assert "insufficient_turnover" in result.findings["rejected"]["XYZ"]


def test_strategy_requires_every_selected_source_and_blocks_conflict():
    technical = AgentResult(agent_name="Technical Analysis Agent", status=AgentStatus.SUCCEEDED,
        conclusion="trend", findings={"direction": "long"})
    news = AgentResult(agent_name="News Intelligence Agent", status=AgentStatus.SUCCEEDED,
        conclusion="news", findings={"direction": "short"})
    actions = AgentResult(agent_name="Corporate Actions Agent", status=AgentStatus.SUCCEEDED,
        conclusion="clear", findings={"blocked": False})
    conflict = evaluate_strategy(mode="combined", horizon="intraday", results=[technical, news, actions])
    assert conflict.findings["conflict"] is True
    assert conflict.findings["candidate_allowed"] is False
    incomplete = evaluate_strategy(mode="combined", horizon="intraday", results=[technical, actions])
    assert incomplete.findings["missing_sources"] == ["News Intelligence Agent"]


def test_critic_and_synthesis_fail_closed():
    unsupported = AgentResult(agent_name="News Intelligence Agent", status=AgentStatus.SUCCEEDED,
        conclusion="unsubstantiated", findings={}, evidence=[])
    critic = critique_evidence([unsupported])
    assert critic.findings["review_passed"] is False
    strategy = AgentResult(agent_name="Strategy Agent", status=AgentStatus.SUCCEEDED,
        conclusion="candidate", findings={"candidate_allowed": True})
    intent = TradeIntent(symbol="BEL", entry_price=100, stop_price=95, target_price=110,
        quantity=1, direction="long")
    approved = synthesize_recommendation(strategy=strategy,
        risk=RiskDecision(accepted=True, approved_quantity=1, risk_amount=5),
        intent=intent, critic=critic)
    assert approved.status == AgentStatus.SKIPPED
    assert approved.findings["intent"] is None
    passed = synthesize_recommendation(strategy=strategy,
        risk=RiskDecision(accepted=True, approved_quantity=1, risk_amount=5), intent=intent)
    assert passed.status == AgentStatus.SUCCEEDED
