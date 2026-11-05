"""LangGraph fan-out/fan-in workflow; strategy nodes remain independent."""
from __future__ import annotations

import asyncio
import inspect
from uuid import uuid4
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.services.retry import is_retryable_error


def _merge_results(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return left + right


class WorkflowState(TypedDict, total=False):
    strategies: list[str]
    tasks: dict[str, Callable[[], Any]]
    timeout_seconds: int
    max_retries: int
    results: Annotated[list[dict[str, Any]], _merge_results]


def _dispatch(state: WorkflowState) -> list[Send]:
    selected = state.get("strategies", [])
    tasks = state.get("tasks", {})
    return [
        Send("strategy", {
            "strategy": name, "task": tasks.get(name), "task_id": str(uuid4()),
            "timeout_seconds": state.get("timeout_seconds", 120),
            "max_retries": state.get("max_retries", 0),
        })
        for name in selected
    ]


async def _strategy_node(state: dict[str, Any]) -> dict[str, Any]:
    task = state.get("task")
    name = state["strategy"]
    task_id = state.get("task_id", str(uuid4()))
    if task is None:
        return {"results": [{"name": name, "task_id": task_id, "status": "skipped",
                             "reason": "no strategy handler registered"}]}
    timeout = max(1, int(state.get("timeout_seconds", 120)))
    retries = max(0, int(state.get("max_retries", 0)))
    last_error: Exception | None = None
    attempts = 0
    for attempt in range(retries + 1):
        attempts = attempt + 1
        worker: asyncio.Task[Any] | None = None
        try:
            if inspect.iscoroutinefunction(task):
                result = await asyncio.wait_for(task(), timeout=timeout)
            else:
                worker = asyncio.create_task(asyncio.to_thread(task))
                try:
                    result = await asyncio.wait_for(asyncio.shield(worker), timeout=timeout)
                except asyncio.TimeoutError:
                    if worker.done():
                        raise
                    last_error = TimeoutError(
                        "synchronous worker timed out and cannot be force-cancelled"
                    )
                    break
                if inspect.isawaitable(result):
                    result = await asyncio.wait_for(result, timeout=timeout)
            return {"results": [{
                "name": name, "task_id": task_id, "status": "succeeded",
                "attempts": attempts, "result": result,
            }]}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_error = exc
            if not is_retryable_error(exc):
                break
    return {"results": [{
        "name": name, "task_id": task_id, "status": "failed",
        "attempts": attempts,
        "error": f"{type(last_error).__name__}: {last_error}",
    }]}


def build_strategy_graph():
    graph = StateGraph(WorkflowState)
    graph.add_node("dispatch", lambda state: {})
    graph.add_node("strategy", _strategy_node)
    graph.add_conditional_edges("dispatch", _dispatch, ["strategy"])
    graph.add_edge(START, "dispatch")
    graph.add_edge("strategy", END)
    return graph.compile()
