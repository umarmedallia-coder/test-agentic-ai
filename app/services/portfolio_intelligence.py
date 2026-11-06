"""Deterministic portfolio concentration and liquidity-context diagnostics."""
from __future__ import annotations

from app.models import AgentResult, AgentStatus, Position


def analyze_portfolio(
    positions: list[Position],
    marks: dict[str, float],
    equity: float,
    cash: float,
    *,
    max_single_position_exposure_pct: float,
) -> AgentResult:
    """Summarize gross, net, long, short, and concentration exposure from valid marks."""
    if equity <= 0 or cash < 0 or not 0 < max_single_position_exposure_pct <= 1:
        return AgentResult(
            agent_name="Portfolio Intelligence Agent", status=AgentStatus.FAILED,
            conclusion="Portfolio inputs are invalid; concentration analysis unavailable.",
            findings={},
            errors=["equity must be positive, cash non-negative, and concentration cap in (0, 1]"],
        )

    exposure_by_symbol: dict[str, float] = {}
    missing_marks: list[str] = []
    long_exposure = 0.0
    short_exposure = 0.0
    for position in positions:
        price = marks.get(position.symbol)
        if price is None or price <= 0:
            missing_marks.append(position.symbol)
            continue
        notional = price * position.quantity
        exposure_by_symbol[position.symbol] = (
            exposure_by_symbol.get(position.symbol, 0.0) + notional
        )
        if position.direction == "long":
            long_exposure += notional
        else:
            short_exposure += notional

    total_exposure = long_exposure + short_exposure
    net_exposure = long_exposure - short_exposure
    concentration = {
        symbol: value / equity for symbol, value in sorted(exposure_by_symbol.items())
    }
    breaches = {
        symbol: round(weight, 6)
        for symbol, weight in concentration.items()
        if weight > max_single_position_exposure_pct
    }
    findings = {
        "open_positions": len(positions),
        "marked_symbols": len(exposure_by_symbol),
        "unmarked_symbols": sorted(set(missing_marks)),
        "gross_exposure": round(total_exposure, 2),
        "gross_exposure_pct": round(total_exposure / equity, 6),
        "long_exposure": round(long_exposure, 2),
        "short_exposure": round(short_exposure, 2),
        "net_exposure": round(net_exposure, 2),
        "net_exposure_pct": round(net_exposure / equity, 6),
        "cash_pct": round(cash / equity, 6),
        "symbol_concentration_pct": {
            symbol: round(weight, 6) for symbol, weight in concentration.items()
        },
        "single_symbol_limit_pct": max_single_position_exposure_pct,
        "concentration_breaches": breaches,
    }
    if missing_marks:
        return AgentResult(
            agent_name="Portfolio Intelligence Agent", status=AgentStatus.FAILED,
            conclusion="One or more open positions lack a valid mark; exposure is incomplete.",
            findings=findings,
            errors=[f"Missing or invalid marks: {', '.join(sorted(set(missing_marks)))}"],
        )
    if breaches:
        return AgentResult(
            agent_name="Portfolio Intelligence Agent", status=AgentStatus.FAILED,
            conclusion="Portfolio concentration exceeds the configured per-symbol limit.",
            findings=findings,
            errors=[
                f"{symbol} exposure {weight:.2%} exceeds "
                f"{max_single_position_exposure_pct:.2%}"
                for symbol, weight in breaches.items()
            ],
        )
    return AgentResult(
        agent_name="Portfolio Intelligence Agent", status=AgentStatus.SUCCEEDED,
        conclusion="Marked portfolio exposure and per-symbol concentration are within limits.",
        findings=findings,
    )
