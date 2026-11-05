"""Bounded async fan-out with failure isolation, timeout and capped retries."""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class TaskTelemetry:
    name: str
    status: str = "waiting"
    attempts: int = 0
    error: str | None = None


class AgentOrchestrator:
    def __init__(self, max_parallel: int = 6, timeout_seconds: float = 120, retries: int = 2) -> None:
        if max_parallel < 1 or timeout_seconds <= 0 or retries < 0:
            raise ValueError("invalid orchestration limits")
        self._semaphore = asyncio.Semaphore(max_parallel)
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.telemetry: dict[str, TaskTelemetry] = {}

    async def _run_one(self, name: str, task: Callable[[], Any]) -> dict[str, Any]:
        telemetry = TaskTelemetry(name=name)
        self.telemetry[name] = telemetry
        async with self._semaphore:
            for attempt in range(self.retries + 1):
                telemetry.status = "running"
                telemetry.attempts = attempt + 1
                try:
                    if inspect.iscoroutinefunction(task):
                        result = await asyncio.wait_for(
                            task(), timeout=self.timeout_seconds,
                        )
                    else:
                        result = await asyncio.wait_for(
                            asyncio.to_thread(task), timeout=self.timeout_seconds,
                        )
                        if inspect.isawaitable(result):
                            result = await asyncio.wait_for(
                                result, timeout=self.timeout_seconds,
                            )
                    telemetry.status = "succeeded"
                    return {"name": name, "status": "succeeded", "result": result}
                except asyncio.TimeoutError:
                    telemetry.error = "agent timed out"
                    telemetry.status = "timed_out"
                except asyncio.CancelledError:
                    telemetry.status = "cancelled"
                    raise
                except Exception as exc:  # isolate one agent from its peers
                    telemetry.error = f"{type(exc).__name__}: {exc}"
                    telemetry.status = "failed"
            return {"name": name, "status": telemetry.status, "error": telemetry.error}

    async def run_parallel(self, tasks: dict[str, Callable[[], Any]]) -> list[dict[str, Any]]:
        if len(tasks) != len(set(tasks)):
            raise ValueError("task names must be unique")
        return await asyncio.gather(*(self._run_one(name, fn) for name, fn in tasks.items()))
