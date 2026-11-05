"""Versioned source-completeness and direction policy for strategy decisions."""
from app.models import AgentResult, AgentStatus


def evaluate_strategy(*, mode: str, horizon: str, results: list[AgentResult],
                      policy_version: str = "strategy-v1") -> AgentResult:
    supported = {"technical", "news", "corporate_actions", "combined"}
    if mode not in supported or horizon not in {"intraday", "swing", "positional"}:
        raise ValueError("unsupported strategy mode or horizon")
    by_name = {result.agent_name: result for result in results}
    required = {
        "technical": ["Technical Analysis Agent", "Corporate Actions Agent"],
        "news": ["News Intelligence Agent", "Corporate Actions Agent"],
        "corporate_actions": ["Corporate Actions Agent"],
        "combined": ["Technical Analysis Agent", "News Intelligence Agent", "Corporate Actions Agent"],
    }[mode]
    missing = [name for name in required if name not in by_name]
    failed = [name for name in required if name in by_name and by_name[name].status != AgentStatus.SUCCEEDED]
    blocked = [name for name in required if name in by_name and by_name[name].findings.get("blocked") is True]
    directions = {}
    for name in required:
        result = by_name.get(name)
        if result is None: continue
        direction = result.findings.get("direction") or result.findings.get("sentiment_direction")
        if direction in {"long", "short", "bullish", "bearish"}:
            directions[name] = "long" if direction in {"long", "bullish"} else "short"
    conflict = len(set(directions.values())) > 1
    complete = not missing and not failed and not blocked
    accepted = complete and not conflict and bool(directions) and mode != "corporate_actions"
    reason = ("required source missing" if missing else "required source incomplete" if failed else
              "corporate-action restriction active" if blocked else "source directions conflict" if conflict else
              "no directional source signal" if not directions else "required evidence aligned")
    return AgentResult(agent_name="Strategy Agent", status=AgentStatus.SUCCEEDED if complete else AgentStatus.SKIPPED,
        conclusion="Strategy policy evaluated; " + reason + ".",
        findings={"mode": mode, "horizon": horizon, "policy_version": policy_version,
            "required_sources": required, "missing_sources": missing, "incomplete_sources": failed,
            "blocked_sources": blocked, "source_directions": directions, "conflict": conflict,
            "candidate_allowed": accepted, "reason": reason,
            "note": "This policy assessment does not replace price construction or central risk validation."},
        is_mock=any(result.is_mock for result in results))
