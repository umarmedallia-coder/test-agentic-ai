"""LangGraph fan-out/fan-in workflow; strategy nodes remain independent."""
from __future__ import annotations

import asyncio
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.services.orchestrator import AgentOrchestrator


def _merge_results(left: list[dict], right: list[dict]) -> list[dict]:
    return left + right


class WorkflowState(TypedDict, total=False):
    strategies: list[str]
    tasks: dict[str, object]
    results: Annotated[list[dict], _merge_results]


async def _dispatch(state: WorkflowState):
    selected = state.get("strategies", [])
    tasks = state.get("tasks", {})
    return [Send("strategy", {"strategy": name, "task": tasks.get(name)}) for name in selected]


async def _strategy_node(state: dict) -> dict:
    task = state.get("task")
    name = state["strategy"]
    try:
        if task is None:
            return {"results": [{"name": name, "status": "skipped", "reason": "no strategy handler registered"}]}
        result = task()
        if asyncio.iscoroutine(result):
            result = await result
        return {"results": [{"name": name, "status": "succeeded", "result": result}]}
    except Exception as exc:
        return {"results": [{"name": name, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}]}


def build_strategy_graph():
    graph = StateGraph(WorkflowState)
    graph.add_node("dispatch", lambda state: {})
    graph.add_node("strategy", _strategy_node)
    graph.add_conditional_edges("dispatch", _dispatch, ["strategy"])
    graph.add_edge(START, "dispatch")
    graph.add_edge("strategy", END)
    return graph.compile()
