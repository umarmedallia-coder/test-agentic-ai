"""Bounded deterministic critic for missing evidence and cross-source contradictions."""
from typing import Any

from app.models import AgentResult, AgentStatus


def critique_evidence(results: list[AgentResult], *, max_findings: int = 20) -> AgentResult:
    if max_findings < 1 or max_findings > 100:
        raise ValueError("max_findings must be between 1 and 100")
    issues: list[dict[str, Any]] = []
    for result in results:
        if result.status in {AgentStatus.FAILED, AgentStatus.TIMED_OUT, AgentStatus.CANCELLED}:
            issues.append({"agent": result.agent_name, "issue": "source_execution_incomplete"})
        if result.status == AgentStatus.SUCCEEDED and not result.evidence:
            issues.append({"agent": result.agent_name, "issue": "no_evidence_attached"})
        if result.findings.get("unresolved_symbols"):
            issues.append({"agent": result.agent_name, "issue": "unresolved_entities",
                           "entities": result.findings["unresolved_symbols"]})
        if result.findings.get("rejected_relationships"):
            issues.append({"agent": result.agent_name, "issue": "relationship_evidence_rejected",
                           "count": len(result.findings["rejected_relationships"])})
    directions = {}
    for result in results:
        direction = result.findings.get("direction") or result.findings.get("sentiment_direction")
        if direction in {"long", "short", "bullish", "bearish"}:
            directions[result.agent_name] = "long" if direction in {"long", "bullish"} else "short"
    if len(set(directions.values())) > 1:
        issues.append({"issue": "cross_agent_direction_conflict", "directions": directions})
    issues = issues[:max_findings]
    return AgentResult(agent_name="Debate/Critic Agent", status=AgentStatus.SUCCEEDED,
        conclusion=f"Evidence review identified {len(issues)} review item(s).",
        findings={"issues": issues, "review_passed": not issues,
                  "scope": "deterministic checks only; no external fact verification"},
        is_mock=any(result.is_mock for result in results))
