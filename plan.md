# Stock Trading Engine - Focused Implementation Plan

This document defines planned functionality, not an implemented trading system.
Build the smallest complete application matching the requirements below.

## 1. Product and Automatic Operation

Build a local Python application for NSE/BSE stocks, with:

- Technical, News, and Corporate Actions strategies, separately or combined.
- One-click Start from a minimal local dashboard.
- Automatic analysis, paper execution, position monitoring, and outcome review.
- Shared risk controls, bounded self-healing, and evaluated learning from mistakes.
- An animated page showing what each agent is actually doing.

After documented installation, `python -m app.cli ui` launches the dashboard
and prints its local URL. It opens idle; clicking Start validates configuration,
reconciles journal state, and starts exactly one engine. A headless
`python -m app.cli start --mode paper` path remains available.

The operating loop is:

1. Validate data freshness, market calendar, and required inputs.
2. Run the selected signal pipelines and necessary supporting agents.
3. Reconcile signals and apply deterministic risk checks.
4. Simulate accepted orders and monitor existing positions.
5. Journal decisions, fills, outcomes, failures, and policy versions.
6. Evaluate mistakes and proposed improvements.

Pause New Entries blocks new entries but keeps position monitoring active.
Stop prevents new work, safely cancels/drains in-flight work, flushes records,
and preserves open paper positions for restart; it does not invent exits.
Browser disconnects, refreshes, repeated clicks, and extra tabs must not duplicate
engines or stop monitoring. Reject a second engine process for the same journal.

Start with deterministic mock data and paper trading. Mock profits demonstrate
neither strategy profitability nor expected real-world returns. Live execution
is a separate future integration requiring supplied data/broker contracts,
explicit authorization, and independently validated permissions and loss limits.

## 2. Strategy Modes

Support `technical`, `news`, `corporate_actions`, and `combined`. Also support
running selected independent strategies concurrently under one controller.
Trading source and horizon (intraday, swing, positional) are separate settings.
Implement narrow, versioned rules rather than every possible indicator/strategy.

| Mode | Signal pipeline |
|---|---|
| Technical | Deterministic price/volume indicators -> Technical Analysis |
| News | News Intelligence -> News-to-Stock Impact Mapping |
| Corporate Actions | Validated announcements/dates -> Corporate Actions |
| Combined | Selected source results -> Strategy policy -> Synthesis |

All modes use current validated prices, liquidity/calendar checks, account-wide
risk controls, and shared execution/outcome services. Standalone modes do not
require other signal sources or fundamental analysis.

Combined mode must explain each source's evidence, contribution, freshness,
horizon, and conflict. Define thresholds and conflict rules before implementation;
do not introduce universal scoring weights requiring optional agents.
Missing required evidence or incompatible signals default to no new entry,
with an explicit reason, not silent source removal.

Reconcile overlapping intents by symbol/exchange before execution. Prevent
duplicate fills and unintended offsetting positions across strategies. Attribute
trades and costs to strategies; per-strategy results must reconcile to the
account total without double counting.

Select modes before Start and freeze them for that run. Changing modes requires
Stop and restart, retaining open positions' original exit policy, attribution,
loss history, and risk budgets.

### Source-specific correctness

- Technical indicators and entry/exit rules are deterministic Python code.
  LLMs may interpret results, not invent prices or perform critical calculations.
- News processing deduplicates events, separates facts from interpretation, and
  distinguishes news sentiment from business/stock impact.
- News mapping validates NSE/BSE symbols and resolves aliases, direct mentions,
  and evidence-backed supplier/customer, competitor, parent/subsidiary,
  commodity, policy, and geographic exposure. Do not infer relationships solely
  from sector membership or an LLM explanation.
- Mapping retains unresolved entities, conflicting exposures, source references,
  and freshness; deduplicate by symbol/exchange while retaining multiple reasons.
  Direction may be positive, negative, mixed, neutral, or uncertain.
- Corporate actions use confirmed announcements, ex-dates, and record dates.
  Splits, bonuses, and dividends are not automatic buy signals or free profit.
  Keep adjusted/unadjusted prices consistent and model position adjustments,
  entitlement, and cash-flow timing without double counting.

## 3. Minimal Technology and Structure

Use Python 3.12+, LangGraph, Streamlit, Pydantic/Pydantic Settings, Pytest,
Ruff, and MyPy. Use Pandas/NumPy where calculations need them.
Use one process, an internal async scheduler, and local operational journals.

Add a small LangChain-compatible Ollama or OpenRouter adapter only where LLM
interpretation is needed. All requests use a shared provider interface with
validated structured output, timeouts, usage/cost tracking, and explicit errors.
Support configured provider/per-agent model selection without an intelligent
model-routing subsystem or silently changing models. Tests use deterministic
adapters; ordinary CI requires neither model downloads nor paid calls.

Keep clear boundaries without prescribing dozens of directories:

```text
app/
  cli/           # Dashboard launch and headless lifecycle commands
  ui/            # Overview and Agent Activity
  agents/        # Implemented analytical roles and focused prompts
  workflows/     # LangGraph state, routing, and execution
  data/          # Schemas, services, mock/real adapters
  services/      # Risk, paper execution, journal, recovery, learning
  core/          # Validated configuration and logging
tests/
  fixtures/
pyproject.toml
.env.example
README.md
```

Create modules only when needed. Preserve existing repository history and files;
do not reinitialize Git or integrate an unrelated existing application.

**Not required:** Redis, Celery/Beat, graph databases, PostgreSQL/pgvector,
React/Next.js, REST/GraphQL APIs, separate workers, paid tracing, Kubernetes,
production deployment pipelines, or a large documentation catalogue.
Docker and additional providers are optional later requests, not release gates.

## 4. Data, Tools, and Operational Records

Canonical Pydantic schemas and service interfaces own data retrieval and
normalization. Registered agent-facing tools are thin permission-checked adapters
over those services, not a second retrieval/validation architecture.

Implement only contracts needed by selected modes:

- Quotes, historical OHLCV, and market/calendar inputs.
- News events and corporate announcements/actions.
- Stock universe, entity resolution, company profile, and relationship/exposure
  lookup for news mapping.

Prefer one relationship service with typed relationships over separate mandatory
tools for every relationship category. Add specialized contracts only when a
supplied integration requires them. No mandatory graph database.

Every response includes source identity, `is_mock`, timestamps, freshness,
validated payload, and explicit errors. Fixtures cover bullish/bearish/sideways
conditions, event scenarios, missing/stale data, conflicting evidence, and failure.
Keep fixtures out of agents. Mixed mock/real adapters preserve provenance.

Do not connect to MySQL initially, create stock-data tables/migrations, or mirror
external market datasets/real holdings. When schema and tools are supplied later,
add read-only adapters without rewriting agents or modifying the external database.

Graph checkpoints are in memory. Append-only local JSONL journals retain
operational decisions, paper positions/fills, costs, outcomes, execution status,
policy versions, and evidence references - not copies of market datasets.
Use validated records, single-writer locking, explicit flush semantics, retention,
redaction, and restart reconciliation. Corruption or write failure must surface
diagnostics and halt affected execution, never silently reset balances/history.
Do not promise full graph replay from journal records.

### Initial tool contracts

Preserve these logical interfaces as the implementation contract. Exact argument
types live in shared Pydantic input models, not ad-hoc dictionaries:

| Contract | Inputs | Validated result |
|---|---|---|
| `get_stock_quote` | symbol, exchange | price, market timestamp, volume/liquidity metadata |
| `get_historical_prices` | symbol, exchange, timeframe, start/end | ordered OHLCV, adjustment convention, coverage |
| `get_market_indices` | as-of | index observations for enabled regime filters |
| `get_trading_calendar` | exchange, date range | timezone-aware sessions, holidays, exceptional sessions |
| `get_stock_news` | symbols/filter, since, cursor | identified news events, publication/retrieval times, sources |
| `get_news_details` | news ID | original source reference, event content, verification metadata |
| `get_company_announcements` | symbol, exchange, since | dated announcements and source references |
| `get_corporate_actions` | symbol, exchange, date range | action type, status, relevant dates, ratios/amounts |
| `get_stock_universe` | exchanges | canonical symbols, exchanges, names, aliases |
| `resolve_company_entity` | entity name, optional exchange | resolved candidates, ambiguity, unresolved status |
| `validate_stock_symbol` | symbol, exchange | validity and canonical security identity |
| `get_company_profile` | symbol, exchange | sector, business segments, known exposure |
| `get_company_relationships` | symbol, exchange, optional types | typed relationship edges and evidence |

A relationship edge includes subject/object identity, type, source, validity
dates, and evidence quality. Support supplier/customer, competitor,
parent/subsidiary, commodity, sector, policy/regulatory, and geographic exposure.
Sector lookup is candidate discovery, not proof of impact. More specialized
supplier, subsidiary, or commodity tools may wrap this canonical service when
needed; do not require redundant integrations.

Each registered tool defines a unique name, description, input/output schema,
execution method, timeout/retry policy, permissions, and metadata. Expose only
permitted tools to each agent. The executor validates input/output, records
attempts, and returns typed failures; it must not silently substitute empty data.
Tests exercise adapter replacement and mixed providers without changing agents.

### Shared structured models

- **DataEnvelope:** payload, source references, `is_mock`, observed/as-of and
  retrieved timestamps, freshness/quality status, missing fields, typed errors.
- **Evidence:** stable ID, source/event identity, timestamp, fact or supported
  inference, relationship reference where applicable, provenance and limitations.
- **AgentResult:** agent/task/workflow/execution IDs, symbol/exchange or event,
  strategy source and horizon, status, conclusion, findings, evidence IDs,
  risks, quality, score/confidence where meaningful, and optional model usage.
- **NewsImpactResult:** news ID/type/summary, unresolved entities, evaluated
  counts, and deduplicated affected securities. Each security retains all
  direct/indirect exposures, direction, horizon, reasoning, evidence, and risks.
- **TradeIntent / RiskDecision:** strategy/policy identity, security, direction,
  proposed entry/stop/target/quantity, evidence, acceptance/rejection reasons,
  and applicable account limits.
- **PaperFill / Position / Outcome:** stable IDs, intent linkage, quantities,
  entry/exit/mark times and prices, fees/slippage, policy attribution, realized
  and unrealized metrics, exit reason, and simulation assumptions.
- **ExecutionSnapshot:** lifecycle and per-task status, timestamps, durations,
  retry/error details, dependency waits, active task count, and snapshot freshness.

Use explicit enums, timezone-aware timestamps, validated numeric bounds, and
stable IDs. Monetary arithmetic must have an explicit rounding/precision policy.
Impact score is 0-100; confidence is 0-1, not a calibrated probability.
Reject schema violations visibly; no primary free-form inter-agent contract.

## 5. Shared Risk, Execution, and Parallel Workflow

Risk calculations, execution/position management, and outcome evaluation are
shared deterministic services, not additional LLM agents.

Before any simulated entry, validate account equity, per-trade risk, entry/stop
prices, direction, quantity/lot constraints, liquidity, and event restrictions.
Enforce configured maximum daily loss, drawdown, exposure, and position limits
across all strategies. Missing/invalid inputs return an explicit rejection or
"cannot size" result. AI, recovery, and learning cannot relax hard limits.

Paper fills model fees, slippage, liquidity, and uncertain execution. Use only
prices available at the decision/fill time; define fill timing and ambiguous
stop/target handling before implementation. Missing marks are unavailable,
not zero-valued positions or zero P&L.

### LangGraph parallel execution

- Use async fan-out/fan-in and dynamic `Send` for runtime-selected stocks.
- Parallelize independent work; route dependents only after required inputs
  are available. Respect the installed LangGraph scheduler semantics.
- Use independent state fields or explicit deterministic reducers; never
  overwrite other agent/stock results.
- Enforce global agent/tool/LLM limits and provider-specific LLM caps.
- Bound per-agent timeout, retries, cancellation, and total workflow budgets.
  Preserve partial results and isolate independent failures.
- Final synthesis requires successful risk validation and all mandatory
  analytical inputs. Missing dependencies produce incomplete/rejected results,
  not success-shaped recommendations.
- Identify work by workflow, task, symbol/event, and attempt to prevent duplicate
  analysis/fills while preserving deliberate retries.
- Track status, start/end times, duration, retries, errors, and dependency waits.
  Expose these validated snapshots to the UI.

Keep the requested initial settings, validated centrally:

```text
ENABLE_PARALLEL_EXECUTION=true
MAX_PARALLEL_AGENTS=6
MAX_CONCURRENT_TOOL_CALLS=10
MAX_LLM_CONCURRENCY=4
AGENT_TIMEOUT_SECONDS=120
AGENT_MAX_RETRIES=2
```

Limits/timeouts must be positive; retry counts non-negative and bounded by the
workflow budget. Parallel-disabled execution retains the same contracts and
dependency/risk behavior. Capacity is configurable, not assumed suitable for
every local machine.

### Workflow dependencies

1. Capture a consistent cycle context: as-of time, mode/horizon, policy version,
   data quality, and account snapshot.
2. Fan out only selected sources. Technical and Corporate Actions can analyze
   independently; News Mapping waits for News Intelligence's validated event.
3. Strategy policy reconciles completed source findings. In combined mode, all
   required selected sources must be accounted for; failed required branches
   block entry. Optional support is explicitly marked optional.
4. Invoke Market Intelligence or Debate/Critic only when configured conditions
   require them. Bound critic requests; a critic cannot grant risk exemptions.
5. Form a candidate intent, apply account-wide risk validation, and synthesize
   the final decision. If synthesis changes executable prices/quantity or other
   risk-relevant fields, revalidate before accepting the intent.
6. Serialize account reservation/fill mutations across concurrent strategies.
   Reject stale/conflicting intents rather than allowing races past risk limits.
7. Monitor positions and record outcomes independently of new-entry generation.
   Pause of one source must not stop unrelated valid position monitoring.

Define daily-loss reset boundaries using the configured exchange/session
timezone. Session boundaries, restarts, or strategy changes cannot erase
historical drawdown or previously consumed exposure without recorded transitions.

## 6. Agent Catalogue and Supporting Roles

Retain all 13 names for the activity page and future supporting capabilities.
Do not implement or run every agent simply to populate the page.

| # | Exact name | Use |
|---|---|---|
| 1 | Market Intelligence Agent | Optional configured market-regime filter |
| 2 | Technical Analysis Agent | Technical signal source |
| 3 | Fundamental Analysis Agent | Optional on-demand fundamentals; not a trading prerequisite |
| 4 | News Intelligence Agent | News extraction/classification |
| 5 | Corporate Actions Agent | Corporate-action signal source |
| 6 | Institutional Activity Agent | Optional institutional evidence |
| 7 | Risk Management Agent | Risk findings backed by mandatory deterministic controls |
| 8 | Stock Discovery Agent | Optional candidate discovery |
| 9 | Strategy Agent | Versioned strategy/horizon alignment |
| 10 | Portfolio Intelligence Agent | Optional concentration/portfolio analysis |
| 11 | Debate/Critic Agent | Configured contradiction/weak-evidence review |
| 12 | Recommendation Synthesis Agent | Final evidence-backed decision |
| 13 | News-to-Stock Impact Mapping Agent | Direct/indirect company exposure from news |

Agents use shared validated result contracts: task/workflow identity, stock/event,
strategy/horizon, findings, evidence references, timestamps, data quality,
provenance, outcome/error, and model metadata when an LLM was used.
Impact scores are 0-100 and confidence 0-1 assessments, not calibrated return
probabilities. Decisions include risks and invalidation/exit conditions.
Keep prompts focused and separate from deterministic business rules.

### Responsibilities and required outputs

| Agent | Responsibility and output detail |
|---|---|
| Technical Analysis | Configured EMA/SMA, RSI, MACD, ATR, volume, trend, breakout/support-resistance rules as needed; emits computed values, rule triggers, entry/exit conditions, evidence and insufficient-history flags. Do not implement every indicator before a strategy needs it. |
| News Intelligence | Extract entities/events, classify category and sentiment, detect duplicates, assess freshness/significance and horizon; emits verified facts separately from interpretation. |
| Corporate Actions | Validate announcements, ex/record dates, splits, bonuses, dividends and configured other actions; emits event-specific exposure, adjustment/entitlement implications and uncertainty. |
| News-to-Stock Impact Mapping | Resolve aliases/security identity and defensible direct/indirect exposure; emits affected stocks, typed relationships, positive/negative/mixed/neutral/uncertain direction, evidence, contradictory factors and unresolved entities. Never manufacture a company relationship. |
| Market Intelligence | When enabled, classify market regime/volatility and relevant sector context from available inputs; emit filter decision and evidence, not a mandatory full global-market report. |
| Risk Management | Present deterministic sizing, stop distance, reward/risk, liquidity/event and account constraints; emit rejection reasons or accepted constraints. LLM commentary cannot override the risk service. |
| Strategy | Apply source/horizon-specific versioned rules and conflict/missing-evidence handling; emit explainable contributions and candidate policy decisions. |
| Recommendation Synthesis | Emit actionable or rejected/incomplete assessment with evidence, source contributions, horizon, risks, invalidation and exit conditions; no unsupported certainty. |
| Debate/Critic | Challenge unsupported facts/relationships and contradictions when routed; emit specific issues and bounded reanalysis requests, not manufactured debate. |
| Stock Discovery | On demand, return candidates matching configured technical/event filters with reasons; no duplicate full analysis pipeline. |
| Fundamental Analysis | On demand, assess supplied financial ratios/statements; unavailable data remains unavailable. No mandatory fundamental score in the requested trading modes. |
| Institutional Activity | On demand, assess supplied FII/DII, deals/ownership or volume evidence; distinguish observations from accumulation/distribution inference. |
| Portfolio Intelligence | On demand, report supplied concentration, diversification and portfolio risk; not a prerequisite for paper position accounting. |

## 7. Two-Page Local UI

Use Streamlit directly with shared Python lifecycle/snapshot services.
Bind to loopback by default; no public hosting or separate API service.

### Overview

- Start/Stop, Pause New Entries/Resume, selected strategies, and engine status.
- Persistent Paper and Mock/Real Data labels, data-as-of/freshness, last/next cycle.
- INR initial capital, cash, equity, realized/unrealized/net P&L, fees, drawdown,
  reporting period, and fill/cost assumptions.
- Open trades: symbol/exchange, strategy, direction, quantity, entry time/price,
  latest valid mark/time, unrealized P&L, stop, target, and status.
- Completed trades: entry/exit, quantity, net P&L, exit reason, symbol/date filter.
- Compact errors/recovery, risk rejections, policy version, and learning outcomes.

### Agent Activity

Show all 13 named agents in lightweight animated role-specific cards. Each shows
its responsibility, real status/task, stock/event, elapsed time, retries, and
sanitized result/error. Expand execution IDs, timestamps, dependency waits,
and per-stock concurrent task details on demand.

Animate only genuinely running agents. Clearly label waiting, idle, skipped,
disabled, unimplemented, succeeded, failed, timed-out, and cancelled states.
Show telemetry freshness; stale data must not suggest ongoing live activity.
No fabricated progress percentages or private model reasoning.
Provide text/icon status as well as color, reduced-motion support, and an
animations-off toggle. Use local CSS/SVG assets without flashing effects.

UI rendering and refresh consume snapshots only. Use one application-scoped
controller; UI navigation, reconnects, multiple tabs, and repeated clicks must
not resubmit work. Do not expose credentials, raw sensitive prompts, untrusted
HTML, risk-limit overrides, or brokerage actions. Remote access needs a separate
authentication/access-control design.

## 8. Bounded Self-Healing

Recover transient errors with capped backoff/retries, timeouts, configured
observable fallback, circuit breakers, and per-cycle budgets. Preserve completed
independent work; after exhaustion, pause affected decisions and show an
actionable error. Stale/missing data is not repaired by inventing values.

Reconcile acknowledged records on restart without duplicate cycles/fills.
Recovery must not change credentials, install packages, edit code, reset losses,
weaken risk checks, or restart failed work indefinitely.

## 9. Learning from Mistakes

Record decisions and completed outcomes with policy versions, evidence references,
costs, failure/mistake categories, and timestamps. Report realized and unrealized
results separately and compare cost-adjusted performance and drawdown to a defined
baseline; win rate alone is not profitability.

Propose only bounded strategy-parameter changes. Evaluate on separate chronological
periods with no future-outcome leakage, transaction costs, a predeclared minimum
sample size, and return/drawdown/risk gates. Insufficient evidence keeps the
current policy. Version tested paper-only promotions, retain the prior policy,
and roll back on predeclared evaluation failures.

Learning cannot change hard risk limits or authorize real orders. Deterministic
fixtures verify the mechanism, not the economic validity of a strategy.

### Evaluation and recovery details

Classify mistakes separately: operational failures, data-quality issues,
unsupported mapping, conflicting signals, execution assumptions, and strategy
losses. A losing trade is not automatically a software defect or proof a rule
should change. Record rejected/no-trade decisions for evaluation without
fabricating hypothetical fills.

Configure permitted parameter ranges, minimum completed sample size, evaluation
window, baseline, costs, and promotion/rollback gates before collecting outcomes.
Keep training/proposal periods separate from evaluation periods; repeated
experimentation on the same holdout must not be reported as independent evidence.
Policy changes apply to new decisions; existing positions retain their recorded
exit policy unless an explicitly tested migration rule exists.

Distinguish retryable network/provider failures from permanent schema, permission,
or journal failures. Retry only classified transient errors. Circuit breakers
use configured opening/cooldown/recovery probes and display their state.
Cancellation must release reservations and concurrency permits safely.

## 10. Delivery Steps and Acceptance

Tests and relevant documentation accompany every step, not a final cleanup phase.

1. **Foundation and contracts:** package/configuration, core schemas, deterministic
   mock services, journal, lifecycle controller, and dashboard shell.
   Acceptance: clean install/help/tests, valid source metadata, rejected invalid
   inputs, and safe journal locking/write/corruption handling.
2. **Signal and risk pipelines:** implement narrow Technical, News + Impact
   Mapping, and Corporate Actions rules plus shared risk and execution services.
   Acceptance: independent source tests, direct/indirect mapping evidence,
   corporate-action accounting, realistic fill rules, and mandatory risk rejection.
3. **Automatic orchestration:** wire all four modes, concurrent independent
   strategies, scheduler, recovery, outcome review, and paper-only learning.
   Acceptance: tests prove actual parallel overlap using timestamps/barriers,
   dependency order, safe merging, caps, timeout/retry/cancellation, partial
   results, conflict rejection, no duplicates, shared budgets, restart, and
   policy rejection/promotion/rollback without leakage or weakened limits.
4. **Usable UI and release:** complete Overview/Agent Activity and operating README.
   Acceptance: framework tests and browser checks verify controls, trade/P&L
   snapshots, empty/error/stale states, real animations/reduced motion, navigation,
   repeated clicks, multiple tabs, and browser disconnect without duplicate engines.

Use Pytest/pytest-asyncio, targeted adapter/contract tests, Ruff and MyPy.
Ordinary CI uses mock dependencies, not live market data or paid AI. Maintain
an 80% coverage target for implemented code; critical risk/accounting/lifecycle
behavior must be tested regardless of aggregate coverage.
Keep one basic GitHub Actions check workflow for the implemented scope.

Document installation, dashboard launch, one-click Start, headless operation,
pause/stop/restart, configuration, simulation limits, and exact test commands in
README. Report actual changed files, commands, results, and a demonstrated
execution example; never fabricate tests, overlap, performance, or implementation.

**Release gate:** all three independent strategies and combined mode run through
the same automatic paper pipeline; UI controls are idempotent; risk and accounting
are correct; journal recovery and bounded learning tests pass; real orders remain
disabled. No provider/infrastructure catalogue is a prerequisite.

### Required test matrix

| Area | Measurable checks |
|---|---|
| Technical | Indicator reference values, warm-up/history requirements, ordered bars, zero/invalid inputs, deterministic triggers and no future-bar leakage |
| News/mapping | Direct mentions, aliases, invalid/ambiguous symbols, supplier/customer/competitor/subsidiary exposure, all impact directions, multiple stocks, duplicates, unsupported/contradictory/stale relationships |
| Corporate actions | Ex/record dates, action status, split/bonus quantities and price basis, dividend entitlement/payment timing, no duplicate adjustments or free-profit artifacts |
| Modes | Each standalone mode, combined mode, concurrently enabled strategies, required-source failure, horizon conflicts, selected-agent routing |
| Risk/accounting | Boundary sizing, invalid stop direction, liquidity/events, fees/slippage, uncertain fills, realized/unrealized separation, account-wide loss/exposure limits, attribution totals |
| Concurrency | At least two independent tasks demonstrably overlap; dependent ordering, reducer retention, measured maximum concurrency, partial failures, cancellation and bounded retries |
| Journals/lifecycle | Single writer/process, repeated Start, acknowledged flush, corrupt record diagnostics, restart without duplicate fills, pause/stop preserving open positions |
| Learning | Insufficient/leaked evidence rejected, valid paper-only promotion, rollback, preserved position policy and immutable hard limits |
| UI | Both pages, all 13 names, status transitions, per-stock active tasks, stale/missing telemetry/marks, empty/error states, reduced motion, refresh/reconnect/multiple tabs without duplicate work |
| Adapters | Input/output validation, permission denial, timeout/exhaustion, provenance-preserving replacement and mixed mock/real configuration |

Test transport behavior with controlled local servers or mocked HTTP where
needed. Use the framework's UI tests plus browser validation; code inspection
alone is not proof that controls or animations work.

## 11. Existing Workspace Skills

Keep these focused workspace skills under `.github/skills/`:

- `stock-engine-architecture`
- `stock-engine-testing`
- `stock-engine-code-review`
- `stock-engine-agent-development`
- `stock-engine-provider-tool-integration`
- `stock-engine-workflow-development`
- `stock-engine-automatic-operation`

Use the relevant skill for the task, not all skills on every request. Maintain
valid name/description frontmatter and correct links to this plan. Do not add
new agents, skills, abstractions, or documentation just to fill a catalogue.
