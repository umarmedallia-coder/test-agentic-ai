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

- Validated runtime configuration and foundational typed contracts.
- Deterministic mock OHLCV/quote provider plus typed news, announcement, corporate-action, company-profile and relationship contracts; unsupported mock feeds return explicit EMPTY status.
- Deterministic EMA 9/21, ATR 14, RSI 14 and MACD 12/26/9 technical analysis.
- Basic shared risk sizing, append-only JSONL journal and exclusive writer lock.
- News normalization, exact alias mapping, duplicate suppression, separate sentiment/materiality scores, and evidence-backed one-hop relationship transmission (same/inverse/mixed/unknown). News signals require separately supplied quote and ATR values.
- Corporate-action schema validation and conservative event-date entry block.
- Paper fill simulator with fee/slippage configuration and idempotent signal key.
- Decimal-based portfolio ledger wired into engine entries, exits, marks, realized/unrealized P&L, and durable snapshot recovery; corporate-action ledger operations are idempotent.
- Bounded async fan-out helper, LangGraph fan-out/fan-in graph, paper outcome report, automatic watchlist scheduler and graceful scheduler drain.
- Optional structured JSON-schema adapters for local Ollama and OpenRouter, wired into news interpretation with deterministic fallback, timeout, usage/cost capture and LLM concurrency limits; disabled by default and never used to calculate prices or indicators.
- Initial unit tests and GitHub Actions CI workflow.
- Streamlit overview with a process-wide cached controller, five-second telemetry refresh and truthful status reporting for the 13-agent roster. Technical, news and corporate-action pipeline statuses are surfaced separately.

## Known incomplete requirements

This branch is **not yet the completed plan**. In particular:
- Engine still uses the legacy mock OHLCV adapter rather than the canonical typed OHLCV provider. Portfolio accounting uses the Decimal ledger; positions and ledger state restore from journal snapshots, but event-by-event journal reconstruction is not implemented.
- No complete event-by-event journal replay, short-position lifecycle, or recovery from every possible crash point. Long paper exits use stop-first handling when both stop and target occur in one OHLC bar.
- LangGraph fan-out/fan-in is used by combined mode to run news and corporate-action pipelines concurrently, with configured concurrency caps. The graph is not yet the primary execution graph for every strategy.
- Technical and news modes both pass through corporate-action restrictions; combined mode additionally requires matching technical/news direction and a successful unblocked corporate-action feed. News mapping supports direct symbol/alias validation and evidence-backed one-hop relationship transmission. Multi-source attribution, multi-symbol conflict reconciliation, unresolved entity workflows and full supplier/customer/commodity exposure validation remain incomplete. Split/dividend calculations are available in the ledger, but the engine does not yet automatically apply verified source events to open positions or journal entitlement cashflows.
- Risk management has per-trade sizing, open-position, daily-loss, drawdown, gross-exposure, lot-size and volume-participation checks, but still needs full exchange-calendar/event integration, sector/correlation exposure and more comprehensive daily P&L controls.
- Scheduler and process-wide Streamlit controller are implemented; the OS journal lock prevents a second process from becoming a writer. Circuit breakers, robust cancellation of every in-flight provider call and browser-level multi-tab acceptance tests remain incomplete.
- Ollama/OpenRouter adapters are wired into optional news interpretation. Trade outcomes are persisted; a leakage-safe chronological evaluation gate and paper-only versioned promotion/rollback registry are implemented as services, but automated candidate generation and engine-level policy promotion remain unwired. Browser-level multi-tab/disconnect acceptance tests remain incomplete.
- Agent roster names are not proof that those agents exist. Unimplemented agents must remain visibly unimplemented.

Mock data is synthetic and cannot establish strategy accuracy or profitability. No return target is promised. Live trading remains deliberately absent. Do not use this branch for financial decisions until critical risk, accounting, persistence and lifecycle acceptance tests pass.

## Checks

```bash
pytest --cov=app --cov-report=term-missing --cov-fail-under=80
ruff check .
mypy app
```
