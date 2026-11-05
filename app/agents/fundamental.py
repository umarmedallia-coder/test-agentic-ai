"""Transparent fundamental-quality assessment over a supplied verified snapshot."""
from datetime import datetime, timezone
from app.agents.contracts import FundamentalSnapshot
from app.models import AgentResult, AgentStatus, Evidence


def analyze_fundamentals(snapshot: FundamentalSnapshot, *, max_age_days: int = 210) -> AgentResult:
    age = (datetime.now(timezone.utc) - snapshot.as_of).total_seconds()
    if age < 0 or age > max_age_days * 86400:
        return AgentResult(agent_name="Fundamental Analysis Agent", status=AgentStatus.SKIPPED,
            symbol=snapshot.symbol, exchange=snapshot.exchange,
            conclusion="Fundamental snapshot is future-dated or stale; no assessment issued.",
            findings={"age_days": round(age / 86400, 2), "source": snapshot.source}, is_mock=snapshot.is_mock)
    metrics = {
        "revenue_growth_pct": snapshot.revenue_growth_pct,
        "earnings_growth_pct": snapshot.earnings_growth_pct,
        "roe_pct": snapshot.roe_pct,
        "roce_pct": snapshot.roce_pct,
        "operating_margin_pct": snapshot.operating_margin_pct,
        "debt_to_equity": snapshot.debt_to_equity,
        "free_cash_flow": snapshot.free_cash_flow,
    }
    available = {key: value for key, value in metrics.items() if value is not None}
    if len(available) < 3:
        return AgentResult(agent_name="Fundamental Analysis Agent", status=AgentStatus.SKIPPED,
            symbol=snapshot.symbol, exchange=snapshot.exchange,
            conclusion="Insufficient verified fundamental fields; no score was fabricated.",
            findings={"available_fields": sorted(available), "missing_fields": sorted(set(metrics)-set(available))},
            is_mock=snapshot.is_mock)
    score = 50.0
    contributions = {}
    for key, value in available.items():
        if key in {"revenue_growth_pct", "earnings_growth_pct"}:
            points = max(-15.0, min(15.0, float(value) * 0.5))
        elif key in {"roe_pct", "roce_pct"}:
            points = max(-10.0, min(10.0, (float(value) - 12.0) * 0.5))
        elif key == "operating_margin_pct":
            points = max(-8.0, min(8.0, (float(value) - 10.0) * 0.4))
        elif key == "debt_to_equity":
            points = max(-12.0, min(8.0, 8.0 - float(value) * 8.0))
        else:
            points = 5.0 if float(value) > 0 else -5.0
        contributions[key] = round(points, 2)
    score = max(0.0, min(100.0, score + sum(contributions.values())))
    return AgentResult(agent_name="Fundamental Analysis Agent", status=AgentStatus.SUCCEEDED,
        symbol=snapshot.symbol, exchange=snapshot.exchange,
        conclusion="Fundamental quality indicators assessed; valuation is not an entry signal.",
        findings={"quality_score": round(score, 2), "contributions": contributions,
            "metrics": available, "valuation": {"pe_ratio": snapshot.pe_ratio, "pb_ratio": snapshot.pb_ratio},
            "as_of": snapshot.as_of.isoformat(), "source": snapshot.source,
            "interpretation": "heuristic score; not a calibrated probability or price target"},
        evidence=[Evidence(source=snapshot.source, observed_at=snapshot.as_of,
            statement="Fundamental metrics supplied for deterministic quality assessment.",
            provenance=snapshot.source, limitations=["Snapshot quality depends on upstream provider and accounting definitions"])],
        is_mock=snapshot.is_mock)
