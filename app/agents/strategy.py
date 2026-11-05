"""Versioned source-completeness and direction policy for strategy decisions."""
from app.models import AgentResult, AgentStatus


def evaluate_strategy(*, mode: str, horizon: str, results: list[AgentResult],
                      policy_version: str = "strategy-v1") -> AgentResult:
    supported = {"technical", "news", "corporate_actions", "combined"}
    if mode not in supported or horizon not in {"intraday", "swing", "positional"}:
        raise ValueError("unsupported strategy mode or horizon")
    by_name = {result.agent_name: result for result in results}
    required = {
        "technical": ["Market Intelligence Agent", "Technical Analysis Agent", "Corporate Actions Agent"],
        "news": ["Market Intelligence Agent", "News Intelligence Agent", "Corporate Actions Agent"],
        "corporate_actions": ["Corporate Actions Agent"],
        "combined": [
            "Market Intelligence Agent", "Technical Analysis Agent",
            "News Intelligence Agent", "Corporate Actions Agent",
        ],
    }[mode]
    missing = [name for name in required if name not in by_name]
    failed = [name for name in required if name in by_name and by_name[name].status not in {AgentStatus.SUCCEEDED, AgentStatus.SKIPPED}]
    # An explicitly empty corporate-action feed is an accounted-for neutral result;
    # an empty signal feed is not evidence for a trade.
    neutral_empty_actions = [name for name in required if name == "Corporate Actions Agent"
        and name in by_name and by_name[name].status == AgentStatus.SKIPPED
        and by_name[name].findings.get("feed_status") == "empty"]
    failed = [name for name in failed if name not in neutral_empty_actions]
    skipped_signal_sources = [name for name in required if name != "Corporate Actions Agent"
        and name in by_name and by_name[name].status == AgentStatus.SKIPPED]
    failed.extend(skipped_signal_sources)
    blocked = [name for name in required if name in by_name and by_name[name].findings.get("blocked") is True]
    directions = {}
    for name in required:
        result = by_name.get(name)
        if result is None:
            continue
        direction = result.findings.get("direction") or result.findings.get("sentiment_direction")
        if name == "Technical Analysis Agent":
            direction = direction or result.findings.get("signal")
        if name == "News Intelligence Agent" and direction is None:
            sentiment = result.findings.get("sentiment")
            if isinstance(sentiment, (int, float)):
                direction = "bullish" if sentiment >= 0.2 else "bearish" if sentiment <= -0.2 else None
        if direction in {"long", "short", "bullish", "bearish"}:
            directions[name] = "long" if direction in {"long", "bullish"} else "short"
    conflict = len(set(directions.values())) > 1
    market_result = by_name.get("Market Intelligence Agent")
    market_regime = market_result.findings.get("regime") if market_result else None
    market_regime_valid = mode == "corporate_actions" or market_regime in {
        "risk_on", "risk_off", "mixed_or_unclear",
    }
    regime_conflict = (
        (market_regime == "risk_off" and "long" in directions.values())
        or (market_regime == "risk_on" and "short" in directions.values())
    )
    optional_context = {}
    optional_warnings = []
    fundamental = by_name.get("Fundamental Analysis Agent")
    if fundamental is not None and fundamental.status == AgentStatus.SUCCEEDED:
        optional_context["fundamental_quality_score"] = fundamental.findings.get("quality_score")
    institutional = by_name.get("Institutional Activity Agent")
    if institutional is not None and institutional.status == AgentStatus.SUCCEEDED:
        flow = institutional.findings.get("flow_direction")
        optional_context["institutional_flow_direction"] = flow
        if flow in {"positive", "negative"} and directions:
            expected_flow = "positive" if "long" in directions.values() else "negative"
            if flow != expected_flow:
                optional_warnings.append(
                    "Institutional flow diverges from the proposed trade direction; treat as contextual risk."
                )
    complete = not missing and not failed and not blocked and market_regime_valid
    accepted = (
        complete and not conflict and not regime_conflict
        and bool(directions) and mode != "corporate_actions"
    )
    reason = (
        "required source missing" if missing else
        "required source incomplete" if failed else
        "corporate-action restriction active" if blocked else
        "market regime unavailable" if not market_regime_valid else
        "market regime conflicts with candidate direction" if regime_conflict else
        "source directions conflict" if conflict else
        "no directional source signal" if not directions else
        "required evidence aligned"
    )
    return AgentResult(agent_name="Strategy Agent", status=AgentStatus.SUCCEEDED if complete else AgentStatus.SKIPPED,
        conclusion="Strategy policy evaluated; " + reason + ".",
        findings={"mode": mode, "horizon": horizon, "policy_version": policy_version,
            "required_sources": required, "missing_sources": missing, "incomplete_sources": failed,
            "blocked_sources": blocked, "source_directions": directions, "conflict": conflict,
            "market_regime": market_regime,
            "market_regime_alignment": "conflict" if regime_conflict else "aligned" if market_regime_valid else "unavailable",
            "optional_context": optional_context, "optional_context_warnings": optional_warnings,
            "candidate_allowed": accepted, "reason": reason,
            "note": "This policy assessment does not replace price construction or central risk validation."},
        is_mock=any(result.is_mock for result in results))
