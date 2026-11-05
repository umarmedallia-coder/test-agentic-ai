# NSE/BSE Agentic Stock Engine

Local Python paper-trading-first application. The current market-data adapter is deterministic mock data. There is no broker integration or live-order execution path.

## Install

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp .env.example .env
```

## Run

```bash
python -m app.cli ui
```

The Streamlit dashboard binds to loopback at http://localhost:8501. Start acquires the local journal writer lock and launches the automatic mock watchlist scheduler. Run cycle triggers an additional manual cycle. Pause blocks new entries while existing positions continue to be monitored; Stop drains the scheduler, writes a lifecycle snapshot and releases the lock.

Headless automatic mode (Ctrl+C performs a graceful stop):

```bash
python -m app.cli start --mode paper
```

One-cycle diagnostic mode:

```bash
python -m app.cli start --mode paper --once
```

The UI Start button and default CLI mode run the configured watchlist automatically. The dashboard refreshes telemetry every five seconds. Pause blocks new entries while existing positions continue to be monitored.

## Implemented in this branch

- Validated runtime configuration and foundational typed contracts. `TradingEngine` accepts an injected `MarketDataProvider`; the default remains deterministic mock data, so a future MySQL/exchange adapter can be connected without changing strategy or risk logic.
- Canonical typed OHLCV, quote, calendar, news, announcement, corporate-action, company-profile and relationship provider contracts; deterministic mock adapter carries explicit source and mock provenance, and unsupported mock feeds return EMPTY status.
- Deterministic EMA, ATR 14, RSI 14 and MACD 12/26/9 technical analysis; active immutable paper-policy parameters control EMA periods, RSI thresholds, ATR stops and reward/risk.
- Market Intelligence Agent retrieves benchmark returns and labels risk-on/risk-off/mixed context only when the required NIFTY and BANK NIFTY observations agree; stale, unavailable and non-finite data fail closed. It never generates a trade intent.
- Shared risk sizing with configurable gross, per-symbol and sector exposure caps, verified sector classification, unclassified-holding fail-closed behavior, finite-input validation, append-only JSONL journal and exclusive writer lock.
- Portfolio Intelligence Agent computes marked gross exposure, cash ratio, per-symbol concentration and missing-mark diagnostics; single-symbol and sector concentration are enforced by the central risk gate.
- News normalization, exact alias mapping, duplicate suppression, separate sentiment/materiality scores, and evidence-backed one-hop relationship transmission (same/inverse/mixed/unknown). News signals require separately supplied quote and ATR values.
- Corporate-action schema validation, conservative event-date entry blocks, and idempotent verified split/bonus/dividend settlement for open paper positions.
- Paper fill simulator with fee/slippage configuration and stable per-bar intent/fill idempotency keys.
- Decimal-based portfolio ledger wired into engine long entries/exits, marks, realized/unrealized P&L, and durable snapshot recovery. The ledger now also has isolated, tested short-open/cover accounting, short dividend liabilities, and fractional split cash-in-lieu settlement; the engine's strategy/order lifecycle remains long-only until that path is integrated.
- Bounded async fan-out helper, LangGraph fan-out/fan-in graph with task IDs, timeouts and transient-only retries; synchronous timed-out workers are not duplicated and retain their concurrency slot until exit. Includes paper outcome reports, automatic watchlist scheduler and graceful scheduler drain.
- Optional structured JSON-schema adapters for local Ollama and OpenRouter, wired into news interpretation with deterministic fallback, timeout, usage/cost capture and LLM concurrency limits; disabled by default and never used to calculate prices or indicators.
- Paper-policy registry with immutable strategy parameters, chronological held-out evaluation, matched candidate/baseline windows, explicit engine-level promotion/rollback, and durable policy lineage; hard risk limits are not tunable.
- Deterministic Fundamental Analysis, Institutional Activity, Stock Discovery, versioned Strategy evaluation, conditional Debate/Critic review, and risk-gated Recommendation Synthesis agents. Fundamental and institutional feeds are fetched concurrently with independent deadlines, per-agent failure isolation, freshness checks, and symbol/exchange identity validation. The mock adapter returns explicit EMPTY responses rather than fabricated metrics. Stock Discovery ranks the active cycle's validated symbol and also supports a bounded, on-demand provider-universe scan from the dashboard.
- Initial unit tests and GitHub Actions CI workflow.
- Streamlit overview with a process-wide cached controller, five-second telemetry refresh and truthful status reporting for the 13-agent roster. Market-regime, technical, news, corporate-action and portfolio-intelligence statuses are surfaced separately.

## Known incomplete requirements

This branch is **not yet the completed plan**. In particular:
- Engine now consumes canonical typed OHLCV envelopes and rejects stale, empty, misidentified, unordered, or insufficient history. Portfolio accounting uses the Decimal ledger; positions and ledger state restore from journal snapshots, but event-by-event journal reconstruction is not implemented.
- No complete event-by-event journal replay or recovery from every possible crash point. Short accounting is implemented and tested at the ledger layer but is not yet wired through engine position creation, monitoring, risk sizing, and exits. Long paper exits use stop-first handling when both stop and target occur in one OHLC bar.
- LangGraph fan-out/fan-in is used by combined mode to run news and corporate-action pipelines concurrently, with configured concurrency caps, task IDs, timeouts and bounded retries. The graph is not yet the primary execution graph for every strategy.
- Technical and news modes both pass through corporate-action restrictions; combined mode additionally requires matching technical/news direction and a successful unblocked corporate-action feed. News mapping supports direct symbol/alias validation and evidence-backed one-hop relationship transmission. Same-symbol technical/news intents are reconciled by direction, confidence and evidence; engine-level cross-symbol conflict resolution, unresolved entity workflows and full supplier/customer/commodity exposure validation remain incomplete. Verified split/bonus/dividend events are applied to open paper positions and the Decimal ledger, with persisted action IDs preventing repeat settlement after restart. Fractional split cash-in-lieu is available in the ledger API, but the engine's corporate-action adapter still needs a verified cash-in-lieu price contract before it can invoke that settlement path.
- Risk management has per-trade sizing, open-position, daily-loss, drawdown, configurable gross-exposure, lot-size, finite-input and volume-participation checks, but still needs authoritative exchange-calendar integration, correlation exposure and more comprehensive daily P&L controls.
- Scheduler and process-wide Streamlit controller are implemented; the OS journal lock prevents a second process from becoming a writer. Circuit breakers are implemented in the agent orchestrator; robust cancellation of every in-flight provider call and browser-level multi-tab acceptance tests remain incomplete.
- Ollama/OpenRouter adapters are wired into optional news interpretation. Trade outcomes and policy history are persisted; leakage-safe chronological evaluation, matched-window baseline comparison, bounded strategy-only parameter proposals, and engine-level paper-only versioned promotion/rollback are implemented. Automated candidate generation and a dashboard control for policy promotion remain unwired. Browser-level multi-tab/disconnect acceptance tests remain incomplete.
- Market Intelligence, Technical Analysis, News Intelligence, Corporate Actions, Portfolio Intelligence and Risk Management have executable paths. Fundamental and Institutional agents are wired to optional provider contracts but remain SKIPPED under the mock adapter because no genuine financial/institutional datasets are supplied. Full-universe discovery is bounded and on-demand; a production exchange-wide symbol master and genuine financial/institutional data providers remain external integration work. Sector exposure is enforced using provider-supplied company classifications; the mock adapter uses explicitly synthetic sector labels. Strategy and Recommendation Synthesis gate paper execution and remain fail-closed; Debate/Critic runs only on configured contradiction or weak-evidence triggers. Active paper-policy parameters are applied by deterministic technical analysis, and outcomes preserve strategy/policy attribution. The UI must distinguish unavailable optional data from a failed analysis.

Mock data is synthetic and cannot establish strategy accuracy or profitability. No return target is promised. Live trading remains deliberately absent. Do not use this branch for financial decisions until critical risk, accounting, persistence and lifecycle acceptance tests pass.

## Checks

```bash
pytest --cov=app --cov-report=term-missing --cov-fail-under=80
ruff check .
mypy app
```
