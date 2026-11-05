"""Bounded async fan-out with timeout, retries, telemetry and circuit breakers."""
from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class TaskTelemetry:
    name: str
    status: str = "waiting"
    attempts: int = 0
    error: str | None = None


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_timeout_seconds: float = 30) -> None:
        if failure_threshold < 1 or recovery_timeout_seconds <= 0:
            raise ValueError("invalid circuit-breaker configuration")
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.state = "closed"
        self.failures = 0
        self.opened_at: float | None = None
        self._probe_in_flight = False

    def allow_request(self) -> bool:
        if self.state == "open":
            if self.opened_at is None or time.monotonic() - self.opened_at < self.recovery_timeout_seconds:
                return False
            self.state = "half_open"
        if self.state == "half_open":
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
        return True

    def record_success(self) -> None:
        self.state = "closed"
        self.failures = 0
        self.opened_at = None
        self._probe_in_flight = False

    def record_failure(self) -> None:
        self.failures += 1
        self._probe_in_flight = False
        if self.state == "half_open" or self.failures >= self.failure_threshold:
            self.state = "open"
            self.opened_at = time.monotonic()


class AgentOrchestrator:
    def __init__(
        self, max_parallel: int = 6, timeout_seconds: float = 120, retries: int = 2,
        circuit_failure_threshold: int = 3, circuit_recovery_seconds: float = 30,
    ) -> None:
        if max_parallel < 1 or timeout_seconds <= 0 or retries < 0:
            raise ValueError("invalid orchestration limits")
        self._semaphore = asyncio.Semaphore(max_parallel)
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_recovery_seconds = circuit_recovery_seconds
        self.telemetry: dict[str, TaskTelemetry] = {}
        self.breakers: dict[str, CircuitBreaker] = {}

    def _breaker(self, name: str) -> CircuitBreaker:
        if name not in self.breakers:
            self.breakers[name] = CircuitBreaker(
                self.circuit_failure_threshold, self.circuit_recovery_seconds,
            )
        return self.breakers[name]

    async def _run_one(self, name: str, task: Callable[[], Any]) -> dict[str, Any]:
        telemetry = TaskTelemetry(name=name)
        self.telemetry[name] = telemetry
        breaker = self._breaker(name)
        async with self._semaphore:
            for attempt in range(self.retries + 1):
                if not breaker.allow_request():
                    telemetry.status = "circuit_open"
                    break
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
                    breaker.record_success()
                    telemetry.status = "succeeded"
                    return {"name": name, "status": "succeeded", "result": result}
                except asyncio.TimeoutError:
                    telemetry.error = "agent timed out"
                    telemetry.status = "timed_out"
                    breaker.record_failure()
                except asyncio.CancelledError:
                    telemetry.status = "cancelled"
                    raise
                except Exception as exc:  # isolate one agent from its peers
                    telemetry.error = f"{type(exc).__name__}: {exc}"
                    telemetry.status = "failed"
                    breaker.record_failure()
            return {"name": name, "status": telemetry.status, "error": telemetry.error}

    async def run_parallel(self, tasks: dict[str, Callable[[], Any]]) -> list[dict[str, Any]]:
        if len(tasks) != len(set(tasks)):
            raise ValueError("task names must be unique")
        return await asyncio.gather(*(self._run_one(name, fn) for name, fn in tasks.items()))
