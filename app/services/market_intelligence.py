"""Market-regime context derived only from the provider's benchmark observations."""
from __future__ import annotations

import math

from app.data.contracts import MarketDataProvider
from app.models import AgentResult, AgentStatus, Evidence


async def run_market_intelligence(
    provider: MarketDataProvider,
    *,
    max_freshness_seconds: int,
) -> AgentResult:
    """Classify broad benchmark context; never create a trade intent."""
    try:
        envelope = await provider.get_market_indices()
    except Exception as exc:
        return AgentResult(
            agent_name="Market Intelligence Agent", status=AgentStatus.FAILED,
            conclusion="Benchmark context could not be retrieved.",
            errors=[f"{type(exc).__name__}: {exc}"],
        )

    if envelope.status.value != "ok" or not envelope.payload:
        return AgentResult(
            agent_name="Market Intelligence Agent", status=AgentStatus.FAILED,
            conclusion="Benchmark data is unavailable; market regime is unknown.",
            findings={"source": envelope.source, "is_mock": envelope.is_mock},
            errors=[envelope.error or f"benchmark status: {envelope.status.value}"],
            is_mock=envelope.is_mock,
        )
    if envelope.freshness_seconds > max_freshness_seconds:
        return AgentResult(
            agent_name="Market Intelligence Agent", status=AgentStatus.FAILED,
            conclusion="Benchmark observations are too old to classify the market.",
            findings={
                "source": envelope.source,
                "freshness_seconds": envelope.freshness_seconds,
                "max_freshness_seconds": max_freshness_seconds,
            },
            errors=["Benchmark data exceeded the configured freshness limit"],
            is_mock=envelope.is_mock,
        )

    returns: dict[str, float] = {}
    for name, raw_value in envelope.payload.items():
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            returns[str(name)] = value

    if not returns:
        return AgentResult(
            agent_name="Market Intelligence Agent", status=AgentStatus.FAILED,
            conclusion="No valid numeric benchmark observations were supplied.",
            findings={},
            errors=["Benchmark payload contains no finite numeric values"],
            is_mock=envelope.is_mock,
        )

    # Inputs are provider-defined percentage-point returns, not decimal fractions.
    broad = next(
        (value for name, value in returns.items() if name.strip().upper() in {"NIFTY 50", "NIFTY"}),
        None,
    )
    bank = next(
        (value for name, value in returns.items() if "BANK" in name.strip().upper()),
        None,
    )
    observations = [value for value in (broad, bank) if value is not None]
    if len(observations) == 2 and all(value >= 0.5 for value in observations):
        regime = "risk_on"
    elif len(observations) == 2 and all(value <= -0.5 for value in observations):
        regime = "risk_off"
    else:
        regime = "mixed_or_unclear"

    observed_at = envelope.as_of
    result = AgentResult(
        agent_name="Market Intelligence Agent", status=AgentStatus.SUCCEEDED,
        conclusion=f"Benchmark context classified as {regime.replace('_', ' ')}.",
        findings={
            "benchmark_returns_pct": returns,
            "nifty_return_pct": broad,
            "bank_nifty_return_pct": bank,
            "regime": regime,
            "interpretation": (
                "Context only; benchmark returns do not predict an individual security."
            ),
        },
        evidence=[Evidence(
            source=envelope.source,
            observed_at=observed_at,
            statement="Benchmark percentage-point returns retrieved from market data provider",
            provenance="provider benchmark payload",
            limitations=[
                "Market regime is a coarse context label, not a forecast",
                "Index constituents, breadth and sector dispersion are not inferred",
            ] + (["Synthetic mock benchmark data"] if envelope.is_mock else []),
        )],
        is_mock=envelope.is_mock,
    )
    return result
