"""Deterministic watchlist candidate ranking from validated candidate observations."""
from datetime import datetime, timezone
from app.agents.contracts import DiscoveryCandidate
from app.models import AgentResult, AgentStatus


def discover_stocks(candidates: list[DiscoveryCandidate], *, min_turnover: float = 10_000_000,
                    max_atr_pct: float = 8.0, max_age_hours: int = 36,
                    limit: int = 20) -> AgentResult:
    if min_turnover < 0 or max_atr_pct <= 0 or max_age_hours <= 0 or limit < 1:
        raise ValueError("invalid discovery thresholds")
    now = datetime.now(timezone.utc)
    ranked = []
    rejected = {}
    for item in candidates:
        reasons = []
        age = (now - item.data_as_of).total_seconds()
        if age < 0 or age > max_age_hours * 3600: reasons.append("stale_or_future_data")
        if item.average_daily_turnover < min_turnover: reasons.append("insufficient_turnover")
        if item.atr_pct > max_atr_pct: reasons.append("volatility_above_limit")
        if item.trend_direction not in {"bullish", "bearish"}: reasons.append("no_directional_trend")
        if reasons:
            rejected[item.symbol] = reasons
            continue
        score = min(100.0, 45.0 * item.trend_strength + 25.0 * min(item.average_daily_turnover / max(min_turnover, 1), 2) / 2 + 30.0 * (1 - item.atr_pct / max_atr_pct))
        ranked.append({"symbol": item.symbol, "exchange": item.exchange, "score": round(score, 2),
            "direction": item.trend_direction, "turnover": item.average_daily_turnover,
            "atr_pct": item.atr_pct, "source": item.source, "is_mock": item.is_mock})
    ranked.sort(key=lambda row: (-row["score"], row["symbol"], row["exchange"]))
    return AgentResult(agent_name="Stock Discovery Agent", status=AgentStatus.SUCCEEDED,
        conclusion=f"Ranked {len(ranked)} eligible candidates; discovery does not authorize orders.",
        findings={"candidates": ranked[:limit], "rejected": rejected,
            "eligible_count": len(ranked), "evaluated_count": len(candidates),
            "thresholds": {"min_turnover": min_turnover, "max_atr_pct": max_atr_pct,
                           "max_age_hours": max_age_hours}},
        is_mock=any(item.is_mock for item in candidates))
