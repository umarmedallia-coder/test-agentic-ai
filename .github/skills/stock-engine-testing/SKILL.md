---
name: stock-engine-testing
description: "Design, add, or run stock engine tests, including pytest unit, contract, integration, end-to-end, deterministic mock, provider, agent, scoring, risk, LangGraph workflow, parallel execution, and concurrency-limit tests."
---

# Stock Engine Testing

Use this skill when creating a test strategy, adding tests, investigating a test
failure, or validating a change in this repository.

## Procedure

1. Read the relevant requirements and acceptance criteria in
   [the project plan](../../../plan.md), then inspect the implementation and
   nearby tests to follow established fixtures and conventions.
2. Identify the behavior under test and the narrowest applicable layer:
   - Unit: deterministic calculations, schemas, routing, and pure business logic.
   - Contract: provider/service and tool input/output validation.
   - Integration: adapters, registries, and graph composition with controlled
     dependencies.
   - End-to-end: complete CLI/workflow behavior using deterministic mock data.
3. Cover success and relevant failure paths: invalid input, missing/stale data,
   provider/tool errors, timeout, retry/fallback, conflicting findings, budget
   exhaustion, concurrency limits, partial results, and risk rejection as
   applicable. For parallel workflows, verify dependencies and merge behavior,
   and prove actual overlap using synchronized starts or recorded start/end
   timestamps; an async API invocation assertion is insufficient.
4. Keep tests deterministic. Mock remote services; use a controlled local test
   server only when it verifies transport behavior. Never make paid AI calls in
   ordinary tests or depend on live market data.
5. Assert meaningful outcomes, not implementation details. Verify provenance,
   evidence traceability, explicit failures, and that absent data is not treated
   as positive evidence.
   For automatic operation, test start/status/stop, repeated cycles, recovery
   exhaustion, journal corruption/restart, duplicate prevention, cost-aware
   simulated outcomes, and paper-only policy rejection/promotion/rollback.
   Verify learning cannot bypass risk limits and does not leak future outcomes.
6. Run the smallest relevant test selection first, then the required checks for
   the changed scope. Use repository-defined commands if present; otherwise use
   `pytest` with the narrow test path and `ruff check` on changed Python files.
7. Report exact commands and results. Distinguish tests run from tests not run;
   never claim coverage or a passing suite without evidence.

## Quality Bar

- Tests should fail for the regression they are intended to prevent.
- Use fixtures for deterministic market scenarios rather than inline agent data.
- Avoid sleeps, live credentials, time-sensitive assumptions, and flaky ordering.
- Add regression tests for fixed defects and update tests when observable
  requirements intentionally change.
