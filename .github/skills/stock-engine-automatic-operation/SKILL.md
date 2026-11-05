---
name: stock-engine-automatic-operation
description: "Implement or test one-command stock-engine operation, automatic paper trading, bounded self-healing, restart reconciliation, outcome journals, and validated learning from mistakes."
---

# Automatic Paper Operation and Recovery

Read [the project plan](../../../plan.md), especially Sections 1, 8, and 9 for
operation, self-healing, and learning requirements. This skill develops application
behavior; it does not authorize live financial transactions.

## Procedure

1. Inspect the implemented CLI, workflow, configuration, and tests. Keep one
   process and an internal async scheduler unless measured requirements demand
   more. Do not add services just to support automatic startup.
2. Wire a single start command through validation, journal reconciliation,
   scheduling, analysis, deterministic risk checks, paper simulation, outcome
   monitoring, and mistake review. Add status and clean stop behavior.
   Wire the local dashboard to the same lifecycle services. Refresh, additional
   tabs, reconnects, and repeated Start clicks must not create duplicate engines.
   Keep simulation monitoring independent of browser rendering or connection.
3. Use validated append-only operational records, single-writer locking, and
   explicit flush/error behavior. Prevent duplicate cycles and simulated fills.
   Do not mirror market datasets or real holdings into the journal.
4. Recover transient failures with bounded retries/backoff and circuit breakers.
   Preserve partial results; surface exhausted retries and journal corruption.
   Never edit code, install packages, change credentials, or bypass risk checks
   as runtime recovery.
5. Derive proposed parameter changes from completed outcomes. Evaluate them
   on chronological held-out periods without look-ahead leakage, with costs,
   a declared minimum sample size, and return/drawdown/risk gates.
6. Keep the previous policy when evidence is insufficient. Promote only
   validated paper-mode policies; version changes and test rollback. Never
   allow learning to weaken hard loss limits or enable real orders.
7. Run focused tests covering repeated cycles, recovery exhaustion, cancellation,
   restart reconciliation, duplicate prevention, corrupt journals, simulated
   P&L/cost accounting, proposal rejection, promotion, and rollback.
8. Report actual commands and results. State mock data and fill assumptions;
   mock profits validate neither expected returns nor real-world profitability.

## Boundaries

- Real-data and broker integrations require separately supplied contracts.
- Live trading requires explicit authorization and independently validated
  permissions and hard loss/exposure controls.
- Retain the simple start experience; optional agents and infrastructure must
  not delay the automatic paper MVP.
