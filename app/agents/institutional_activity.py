"""Institutional activity assessment; consumes supplied, sourced exchange data only."""
from datetime import datetime, timezone
from app.agents.contracts import InstitutionalSnapshot
from app.models import AgentResult, AgentStatus, Evidence


def analyze_institutional_activity(snapshot: InstitutionalSnapshot, *, max_age_days: int = 7) -> AgentResult:
    age = (datetime.now(timezone.utc) - snapshot.as_of).total_seconds()
    if age < 0 or age > max_age_days * 86400:
        return AgentResult(agent_name="Institutional Activity Agent", status=AgentStatus.SKIPPED,
            symbol=snapshot.symbol, exchange=snapshot.exchange,
            conclusion="Institutional-flow evidence is stale or future-dated.",
            findings={"age_days": round(age / 86400, 2)}, is_mock=snapshot.is_mock)
    values = [snapshot.fii_net_value, snapshot.dii_net_value]
    if all(value is None for value in values):
        return AgentResult(agent_name="Institutional Activity Agent", status=AgentStatus.SKIPPED,
            symbol=snapshot.symbol, exchange=snapshot.exchange,
            conclusion="No FII/DII flow observations supplied.", is_mock=snapshot.is_mock)
    net = sum(value or 0.0 for value in values)
    direction = "positive" if net > 0 else "negative" if net < 0 else "neutral"
    findings = {"fii_net_value": snapshot.fii_net_value, "dii_net_value": snapshot.dii_net_value,
        "combined_net_value": net, "flow_direction": direction,
        "delivery_pct": snapshot.delivery_pct, "volume_ratio": snapshot.volume_ratio,
        "as_of": snapshot.as_of.isoformat(), "source": snapshot.source,
        "limitations": ["Institutional flow is contextual evidence, not proof of future price direction"]}
    return AgentResult(agent_name="Institutional Activity Agent", status=AgentStatus.SUCCEEDED,
        symbol=snapshot.symbol, exchange=snapshot.exchange,
        conclusion=f"Institutional flow is {direction}; no standalone trade instruction generated.",
        findings=findings, evidence=[Evidence(source=snapshot.source, observed_at=snapshot.as_of,
            statement=f"Reported combined institutional net flow: {net}.", provenance=snapshot.source,
            limitations=findings["limitations"])], is_mock=snapshot.is_mock)
