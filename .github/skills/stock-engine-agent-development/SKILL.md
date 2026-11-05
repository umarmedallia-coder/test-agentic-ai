---
name: stock-engine-agent-development
description: "Implement, modify, or test a specialized stock-analysis agent using the engine's shared Pydantic contracts, evidence rules, provider abstractions, registered tools, and deterministic tests."
---

# Stock Engine Agent Development

Use this skill when creating or changing one of the stock intelligence agents.

## Procedure

1. Read the relevant agent definition and engineering rules in
   [the project plan](../../../plan.md). Inspect existing agent implementations,
   shared schemas, and tests before choosing a pattern.
2. Define the agent's single responsibility, required inputs, output schema,
   evidence requirements, data quality behavior, tools/permissions, and failure
   modes before implementation.
3. Reuse shared Pydantic contracts and data services. Request tools through the
   registry; do not instantiate provider clients or call concrete data adapters.
4. Keep deterministic work in typed Python services. Use an LLM only for
   interpretation or synthesis that requires it, and validate structured output.
5. Include source, timestamp/freshness, mock status, confidence semantics, and
   supporting evidence in results where applicable. Separate facts from
   interpretation and never invent unavailable data.
6. Handle missing, stale, contradictory, malformed, and failed inputs explicitly.
   Do not return an apparently successful positive result after a dependency fails.
7. Add focused unit and integration tests for expected output and failure paths.
   Ensure ordinary tests use deterministic mocks and no paid API credentials.
8. Run targeted tests and lint/type checks available in the repository. Update
   directly related documentation and report verification accurately.

## Constraints

- Keep prompts focused and separate from business logic.
- Do not embed mock stock datasets in the agent.
- Do not add direct SQL, MySQL assumptions, or stock-data storage.
- Do not bypass tool permissions or silently substitute models/providers.
