---
name: stock-engine-architecture
description: "Analyze or change the stock intelligence engine architecture, module boundaries, data contracts, AI providers, tools, agents, workflows, persistence, or technical design."
---

# Stock Engine Architecture

Use this skill for architecture analysis, design decisions, or changes that cross
module boundaries in this repository.

## Procedure

1. Read the relevant sections of [the project plan](../../../plan.md) and inspect
   the existing code and tests before proposing a design. Do not treat planned
   components as implemented.
2. State the problem, affected use cases, constraints, and acceptance criteria.
   Preserve the minimal-local-UI, no-stock-database, no-initial-MySQL, and
   analysis/paper-only requirements. Prioritize one-process automatic operation
   over optional infrastructure and the full agent catalogue.
3. Trace current contracts and dependencies. Keep Pydantic schemas and
   provider/service interfaces canonical; keep agent-facing tools as thin adapters.
4. Compare the smallest viable options. Call out consequences for testability,
   provider independence, failure handling, operations, and future adapters.
   Do not add a framework, persistence layer, queue, or abstraction without an
   explicit requirement.
5. Define ownership, input/output contracts, error behavior, and data provenance
   at each changed boundary. Distinguish stock data from operational metadata.
   Keep the local Streamlit UI thin and share lifecycle/snapshot services with
   the CLI; prevent browser reruns or extra tabs from starting duplicate engines.
6. If implementing, make a focused change and update directly related tests and
   documentation. If asked only for design, do not edit files.
7. Verify the design against existing workflows, configuration, and tests. Report
   decisions, trade-offs, open assumptions, and validation performed.

## Invariants

- Agents must not depend on specific model providers or concrete tool implementations.
- Deterministic calculations belong in ordinary code, not prompts.
- Never store or represent mock data as real market data.
- Do not add stock-data persistence or MySQL integration without explicit future
  requirements.
- Do not promise durable execution history when using in-memory state.
