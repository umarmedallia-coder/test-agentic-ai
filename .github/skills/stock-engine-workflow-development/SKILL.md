---
name: stock-engine-workflow-development
description: "Design, implement, or test LangGraph workflows for stock analysis, including typed state, dependency-aware parallel agents, conditional routing, bounded retries, checkpointing, recovery, cancellation, and evidence-preserving results."
---

# Stock Engine Workflow Development

Use this skill when creating or changing a LangGraph workflow or its execution
semantics.

## Procedure

1. Read the workflow requirements and phase acceptance criteria in
   [the project plan](../../../plan.md). Inspect existing graph state, nodes,
   workflows, and tests before designing new control flow.
2. Define workflow inputs, outputs, required agents, data dependencies, branches,
   failure policy, retry limits, cancellation behavior, and evidence requirements.
   Avoid running agents that are not needed for the requested analysis.
3. Use typed shared state and validated agent-result schemas. Preserve correlation,
   execution, workflow, provider/model, data-source, freshness, and error metadata.
4. Run independent nodes concurrently through LangGraph's async execution,
   fan-out/fan-in, and dynamic `Send` dispatch where appropriate. Start nodes
   as soon as their actual inputs are ready; make joins and dependency waits
   explicit.
5. Give each parallel node an independent state field or an explicit reducer
   with deterministic merge semantics. Preserve partial results and isolate
   independent failures. Keep risk validation mandatory before any
   recommendation.
6. Enforce validated global and provider-specific agent/tool/LLM concurrency
   limits, per-agent timeouts, bounded retries, and cancellation. Track status,
   timestamps, duration, retry count, and errors; log concurrent groups and
   dependency waits. Do not execute duplicate analysis within one workflow.
7. Keep graph checkpoints in memory and use local operational journals for
   automatic paper-mode restart reconciliation. Distinguish retained decisions
   and simulated positions from unavailable full graph state. Prevent duplicate
   cycles/fills; do not mirror market data.
8. Add graph tests for the successful path and relevant branches, including
   missing/stale data, conflicting results, node/tool failure, retry exhaustion,
   concurrency limits, partial results, risk rejection, and cancellation where
   supported. Prove real overlap with timestamps or barriers, not by checking
   async API calls alone.
9. Run targeted tests and inspect structured output for traceable evidence and
   explicit status. Update workflow documentation and report test results.

## Constraints

- Do not add a public API for orchestration. The local Streamlit UI is permitted
  as a thin consumer of shared lifecycle/snapshot services, not an orchestrator.
- Do not let untrusted news or tool content alter system instructions or
  permissions.
- Do not create unbounded agent debate or retry cycles.
- Keep orchestration separate from agent business logic.
