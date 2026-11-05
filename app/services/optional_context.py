"""Concurrent, bounded optional context retrieval with per-agent failure isolation."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.fundamental import analyze_fundamentals
from app.agents.institutional_activity import analyze_institutional_activity
from app.data.contracts import MarketDataProvider
from app.models import AgentResult, AgentStatus


async def _load_one(
    *,
    name: str,
    symbol: str,
    exchange: str,
    fetch: Callable[[], Awaitable[Any]],
    analyze: Callable[[Any], AgentResult],
    timeout_seconds: int,
    max_freshness_seconds: int,
) -> AgentResult:
    try:
        envelope = await asyncio.wait_for(fetch(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return AgentResult(
            agent_name=name, status=AgentStatus.TIMED_OUT, symbol=symbol, exchange=exchange,
            conclusion="Optional context provider exceeded its deadline; other agents continue.",
            errors=[f"timeout after {timeout_seconds} seconds"],
        )
    except Exception as exc:
        return AgentResult(
            agent_name=name, status=AgentStatus.FAILED, symbol=symbol, exchange=exchange,
            conclusion="Optional context provider raised an exception; other agents continue.",
            errors=[f"{type(exc).__name__}: {exc}"],
        )

    if envelope.status.value == "empty":
        return AgentResult(
            agent_name=name, status=AgentStatus.SKIPPED, symbol=symbol, exchange=exchange,
            conclusion="Optional source returned no observations; no values were inferred.",
            findings={"feed_status": envelope.status.value, "source": envelope.source,
                      "warnings": envelope.warnings},
            is_mock=envelope.is_mock,
        )
    if envelope.status.value != "ok":
        return AgentResult(
            agent_name=name, status=AgentStatus.FAILED, symbol=symbol, exchange=exchange,
            conclusion="Optional source is stale or unavailable; assessment withheld.",
            findings={"feed_status": envelope.status.value, "source": envelope.source,
                      "freshness_seconds": envelope.freshness_seconds},
            errors=envelope.warnings or [envelope.error or envelope.status.value],
            is_mock=envelope.is_mock,
        )
    if envelope.payload is None:
        return AgentResult(
            agent_name=name, status=AgentStatus.FAILED, symbol=symbol, exchange=exchange,
            conclusion="Optional provider returned an OK envelope without a payload.",
            findings={"feed_status": envelope.status.value, "source": envelope.source},
            errors=["missing payload"], is_mock=envelope.is_mock,
        )
    if envelope.freshness_seconds > max_freshness_seconds:
        return AgentResult(
            agent_name=name, status=AgentStatus.SKIPPED, symbol=symbol, exchange=exchange,
            conclusion="Optional source exceeded the configured freshness limit.",
            findings={"feed_status": "stale", "source": envelope.source,
                      "freshness_seconds": envelope.freshness_seconds,
                      "max_freshness_seconds": max_freshness_seconds},
            is_mock=envelope.is_mock,
        )
    payload = envelope.payload
    if payload.symbol.upper() != symbol.upper() or payload.exchange.upper() != exchange.upper():
        return AgentResult(
            agent_name=name, status=AgentStatus.FAILED, symbol=symbol, exchange=exchange,
            conclusion="Provider payload identity does not match the requested instrument.",
            findings={"payload_symbol": payload.symbol, "payload_exchange": payload.exchange,
                      "source": envelope.source},
            errors=["symbol or exchange identity mismatch"], is_mock=envelope.is_mock,
        )
    try:
        result = analyze(payload)
    except Exception as exc:
        return AgentResult(
            agent_name=name, status=AgentStatus.FAILED, symbol=symbol, exchange=exchange,
            conclusion="Optional snapshot failed deterministic analysis; other agents continue.",
            errors=[f"{type(exc).__name__}: {exc}"], is_mock=envelope.is_mock,
        )
    result.is_mock = envelope.is_mock or payload.is_mock
    return result


async def load_optional_context(
    provider: MarketDataProvider,
    symbol: str,
    exchange: str,
    *,
    timeout_seconds: int = 15,
    max_freshness_seconds: int = 86_400,
) -> tuple[AgentResult, AgentResult]:
    """Fetch fundamental and institutional snapshots concurrently.

    Each feed has an independent deadline and status. An unavailable optional feed never
    suppresses the other feed or fabricates data.
    """
    if timeout_seconds < 1 or max_freshness_seconds < 1:
        raise ValueError("timeouts and freshness limits must be positive")
    return await asyncio.gather(
        _load_one(
            name="Fundamental Analysis Agent", symbol=symbol, exchange=exchange,
            fetch=lambda: provider.get_fundamental_snapshot(symbol, exchange),
            analyze=analyze_fundamentals, timeout_seconds=timeout_seconds,
            max_freshness_seconds=max_freshness_seconds,
        ),
        _load_one(
            name="Institutional Activity Agent", symbol=symbol, exchange=exchange,
            fetch=lambda: provider.get_institutional_activity(symbol, exchange),
            analyze=analyze_institutional_activity, timeout_seconds=timeout_seconds,
            max_freshness_seconds=max_freshness_seconds,
        ),
    )
