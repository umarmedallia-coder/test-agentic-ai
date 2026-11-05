import asyncio

import pytest

from app.services.orchestrator import AgentOrchestrator


@pytest.mark.asyncio
async def test_parallel_agents_overlap_but_respect_concurrency_limit():
    active = 0
    peak = 0
    both_started = asyncio.Event()

    async def worker():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        await asyncio.sleep(0.01)
        active -= 1
        return "ok"

    runner = AgentOrchestrator(max_parallel=2, timeout_seconds=2, retries=0)
    results = await runner.run_parallel({str(index): worker for index in range(5)})
    assert all(result["status"] == "succeeded" for result in results)
    assert peak == 2


@pytest.mark.asyncio
async def test_orchestrator_retries_and_records_attempt_count():
    attempts = 0

    async def flaky():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient")
        return "recovered"

    runner = AgentOrchestrator(max_parallel=1, retries=1)
    result = await runner.run_parallel({"flaky": flaky})
    assert result[0]["status"] == "succeeded"
    assert runner.telemetry["flaky"].attempts == 2


@pytest.mark.asyncio
async def test_orchestrator_times_out_agent():
    async def slow():
        await asyncio.sleep(0.2)

    runner = AgentOrchestrator(max_parallel=1, timeout_seconds=0.01, retries=0)
    result = await runner.run_parallel({"slow": slow})
    assert result[0]["status"] == "timed_out"


@pytest.mark.asyncio
async def test_orchestrator_times_out_blocking_sync_agent():
    import time

    def blocking():
        time.sleep(0.2)

    runner = AgentOrchestrator(max_parallel=1, timeout_seconds=0.01, retries=0)
    result = await runner.run_parallel({"blocking": blocking})
    assert result[0]["status"] == "timed_out"


@pytest.mark.asyncio
async def test_agent_circuit_breaker_opens_and_recovers():
    calls = 0

    async def broken():
        nonlocal calls
        calls += 1
        raise RuntimeError("provider unavailable")

    runner = AgentOrchestrator(
        max_parallel=1, retries=0, circuit_failure_threshold=1,
        circuit_recovery_seconds=0.01,
    )
    first = await runner.run_parallel({"provider": broken})
    second = await runner.run_parallel({"provider": broken})
    assert first[0]["status"] == "failed"
    assert second[0]["status"] == "circuit_open"
    await asyncio.sleep(0.02)

    async def healthy():
        return "recovered"

    recovered = await runner.run_parallel({"provider": healthy})
    assert recovered[0]["status"] == "succeeded"
    assert runner.breakers["provider"].state == "closed"
