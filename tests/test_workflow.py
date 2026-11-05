import asyncio

import pytest

from app.services.workflow import build_strategy_graph


@pytest.mark.asyncio
async def test_strategy_graph_retries_and_returns_stable_task_telemetry():
    calls = 0

    def flaky_task():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("temporary provider failure")
        return {"value": 42}

    graph = build_strategy_graph()
    result = await graph.ainvoke({
        "strategies": ["news"],
        "tasks": {"news": flaky_task},
        "timeout_seconds": 2,
        "max_retries": 1,
        "results": [],
    })
    item = result["results"][0]
    assert item["status"] == "succeeded"
    assert item["attempts"] == 2
    assert item["task_id"]
    assert item["result"] == {"value": 42}


@pytest.mark.asyncio
async def test_strategy_graph_isolates_timeout_and_exhausted_retries():
    async def slow_task():
        await asyncio.sleep(2)
        return "late"

    graph = build_strategy_graph()
    result = await graph.ainvoke({
        "strategies": ["slow"],
        "tasks": {"slow": slow_task},
        "timeout_seconds": 1,
        "max_retries": 1,
        "results": [],
    })
    item = result["results"][0]
    assert item["status"] == "failed"
    assert item["attempts"] == 2
    assert "TimeoutError" in item["error"]


@pytest.mark.asyncio
async def test_strategy_graph_marks_missing_handler_as_skipped():
    graph = build_strategy_graph()
    result = await graph.ainvoke({
        "strategies": ["not_configured"],
        "tasks": {},
        "results": [],
    })
    assert result["results"][0]["status"] == "skipped"
    assert result["results"][0]["reason"] == "no strategy handler registered"


@pytest.mark.asyncio
async def test_strategy_graph_does_not_retry_permanent_errors():
    calls = 0

    def invalid_task():
        nonlocal calls
        calls += 1
        raise ValueError("invalid input")

    result = await build_strategy_graph().ainvoke({
        "strategies": ["invalid"], "tasks": {"invalid": invalid_task},
        "timeout_seconds": 2, "max_retries": 3, "results": [],
    })
    assert calls == 1
    assert result["results"][0]["attempts"] == 1
    assert "ValueError" in result["results"][0]["error"]


@pytest.mark.asyncio
async def test_strategy_graph_runs_independent_branches_concurrently():
    active = 0
    peak = 0

    async def worker(value):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        return value

    graph = build_strategy_graph()
    result = await graph.ainvoke({
        "strategies": ["technical", "news"],
        "tasks": {
            "technical": lambda: worker("technical"),
            "news": lambda: worker("news"),
        },
        "timeout_seconds": 2,
        "max_retries": 0,
        "results": [],
    }, config={"max_concurrency": 2})
    assert peak == 2
    assert {item["status"] for item in result["results"]} == {"succeeded"}
    assert {item["result"] for item in result["results"]} == {"technical", "news"}
