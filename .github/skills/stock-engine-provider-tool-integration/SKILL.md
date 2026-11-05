---
name: stock-engine-provider-tool-integration
description: "Add, adapt, or test stock data providers and registered tools, including future real integrations, mock implementations, Pydantic contracts, source metadata, permissions, timeouts, and retries."
---

# Stock Engine Provider and Tool Integration

Use this skill when implementing a data provider, tool adapter, mock data source,
or integration supplied for this project.

## Procedure

1. Read [the project plan](../../../plan.md), especially its database policy,
   tool architecture, canonical data contracts, and future integration rules.
2. Inspect the supplied interface, its documented inputs/outputs, and the
   repository's provider/service schemas. Do not infer undocumented endpoints,
   credentials, schema, or capabilities.
3. Keep provider/service functions as the canonical retrieval and normalization
   layer. Implement agent-facing tools as thin wrappers that apply metadata,
   permissions, validation, timeout/retry policy, and execution details.
4. Validate input and output with existing Pydantic schemas. Preserve source,
   retrieval timestamp, freshness, and mock/real identity. Never silently label
   mock or uncertain data as real.
5. Surface failures explicitly with repository-standard errors and structured
   metadata. Retries must be bounded and must not hide invalid data or exhausted
   budgets.
6. Keep integrations isolated from agent business logic. Do not add SQL,
   stock-data persistence, MySQL connections, or new dependencies unless
   explicitly required and approved by project scope.
7. Add adapter contract tests for valid data, invalid responses, missing/stale
   data, timeout, and provider failure. Mock external network calls in CI.
8. Verify registration and permissions, run targeted tests, and document
   configuration without exposing credentials.

## Completion Report

Summarize the contract implemented, registration/configuration required, tests
run, known limits, and any assumptions that still need confirmation.
