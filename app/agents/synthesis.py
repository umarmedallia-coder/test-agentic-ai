"""Final recommendation synthesis that cannot bypass the deterministic risk gate."""
from app.models import AgentResult, AgentStatus, RiskDecision, TradeIntent


def synthesize_recommendation(*, strategy: AgentResult, risk: RiskDecision | None,
                              intent: TradeIntent | None, critic: AgentResult | None = None) -> AgentResult:
    reasons = []
    if strategy.status != AgentStatus.SUCCEEDED or not strategy.findings.get("candidate_allowed"):
        reasons.append("strategy policy did not authorize a candidate")
    if intent is None:
        reasons.append("no validated trade intent supplied")
    if risk is None or not risk.accepted:
        reasons.extend(risk.reasons if risk else ["risk decision missing"])
    if critic is not None and critic.findings.get("review_passed") is False:
        reasons.append("critic review has unresolved evidence issues")
    accepted = not reasons
    findings = {"decision": "paper_candidate_accepted" if accepted else "rejected_or_incomplete",
        "reasons": reasons, "strategy_policy": strategy.findings,
        "risk_approved_quantity": risk.approved_quantity if risk else 0,
        "intent_id": intent.id if intent else None,
        "intent": intent.model_dump(mode="json") if intent and accepted else None,
        "risk_amount": risk.risk_amount if risk else 0,
        "hard_rule": "No order may execute without a separate central risk acceptance."}
    return AgentResult(agent_name="Recommendation Synthesis Agent",
        status=AgentStatus.SUCCEEDED if accepted else AgentStatus.SKIPPED,
        symbol=intent.symbol if intent else None, exchange=intent.exchange if intent else None,
        conclusion="Paper candidate synthesized." if accepted else "No actionable recommendation: " + "; ".join(reasons),
        findings=findings, is_mock=strategy.is_mock or (critic.is_mock if critic else False))
