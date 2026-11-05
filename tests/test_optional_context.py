import asyncio
from datetime import datetime, timezone

import pytest

from app.agents.contracts import FundamentalSnapshot, InstitutionalSnapshot
from app.contracts import DataEnvelope, DataStatus
from app.models import AgentStatus
from app.services.optional_context import load_optional_context


class OptionalProvider:
    def __init__(self, fundamental=None, institutional=None, delay=0):
        self.fundamental = fundamental
        self.institutional = institutional
        self.delay = delay

    async def get_fundamental_snapshot(self, symbol, exchange):
        await asyncio.sleep(self.delay)
        if isinstance(self.fundamental, Exception):
            raise self.fundamental
        return self.fundamental

    async def get_institutional_activity(self, symbol, exchange):
        await asyncio.sleep(self.delay)
        if isinstance(self.institutional, Exception):
            raise self.institutional
        return self.institutional


def envelope(payload, *, status=DataStatus.OK, freshness=0):
    return DataEnvelope(source="test-feed", is_mock=False, as_of=datetime.now(timezone.utc),
        status=status, freshness_seconds=freshness, payload=payload)


@pytest.mark.asyncio
async def test_optional_context_fetches_feeds_concurrently():
    now = datetime.now(timezone.utc)
    provider = OptionalProvider(
        envelope(FundamentalSnapshot(symbol="INFY", exchange="NSE", as_of=now,
            source="fundamental", revenue_growth_pct=10, earnings_growth_pct=12, roe_pct=15)),
        envelope(InstitutionalSnapshot(symbol="INFY", exchange="NSE", as_of=now,
            source="flows", fii_net_value=10)),
        delay=.1,
    )
    started = asyncio.get_running_loop().time()
    fundamental, institutional = await load_optional_context(provider, "INFY", "NSE")
    elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < .18
    assert fundamental.status == AgentStatus.SUCCEEDED
    assert institutional.status == AgentStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_optional_feed_failure_isolated_from_other_agent():
    provider = OptionalProvider(
        RuntimeError("fundamental source down"),
        envelope(InstitutionalSnapshot(symbol="INFY", exchange="NSE",
            as_of=datetime.now(timezone.utc), source="flows", fii_net_value=10)),
    )
    fundamental, institutional = await load_optional_context(provider, "INFY", "NSE")
    assert fundamental.status == AgentStatus.FAILED
    assert institutional.status == AgentStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_optional_feed_timeout_and_empty_are_truthful():
    provider = OptionalProvider(
        envelope(None, status=DataStatus.EMPTY),
        envelope(None, status=DataStatus.EMPTY),
        delay=.05,
    )
    fundamental, institutional = await load_optional_context(
        provider, "INFY", "NSE", timeout_seconds=1,
    )
    assert fundamental.status == AgentStatus.SKIPPED
    assert institutional.status == AgentStatus.SKIPPED

    slow = OptionalProvider(delay=.05)
    timed_out, _ = await load_optional_context(slow, "INFY", "NSE", timeout_seconds=0.01)
    assert timed_out.status == AgentStatus.TIMED_OUT


@pytest.mark.asyncio
async def test_optional_feed_rejects_wrong_instrument_and_stale_envelope():
    now = datetime.now(timezone.utc)
    wrong = envelope(FundamentalSnapshot(symbol="TCS", exchange="NSE", as_of=now,
        source="wrong", revenue_growth_pct=10, earnings_growth_pct=10, roe_pct=10))
    stale = envelope(InstitutionalSnapshot(symbol="INFY", exchange="NSE", as_of=now,
        source="flows", fii_net_value=10), freshness=1000)
    provider = OptionalProvider(wrong, stale)
    fundamental, institutional = await load_optional_context(
        provider, "INFY", "NSE", max_freshness_seconds=100,
    )
    assert fundamental.status == AgentStatus.FAILED
    assert institutional.status == AgentStatus.SKIPPED
