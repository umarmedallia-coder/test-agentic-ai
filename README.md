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

The Streamlit dashboard binds to loopback at http://localhost:8501. Start acquires the local journal writer lock. Run cycle triggers one deterministic mock analysis cycle. Pause blocks new entries; Stop writes a lifecycle event and releases the lock.

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
- News normalization, exact alias mapping, duplicate suppression and conservative keyword impact heuristic.
- Corporate-action schema validation and conservative event-date entry block.
- Paper fill simulator with fee/slippage configuration and idempotent signal key.
- Decimal-based portfolio ledger with mark-to-market and duplicate-fill protection.
- Bounded async fan-out helper, LangGraph fan-out/fan-in graph, paper outcome report, automatic watchlist scheduler and graceful scheduler drain.
- Optional structured JSON-schema adapters for local Ollama and OpenRouter; disabled by default and not used to calculate prices or indicators.
- Initial unit tests and GitHub Actions CI workflow.
- Existing Streamlit overview and 13-agent roster; only the implemented technical agent is reported as active.

## Known incomplete requirements

This branch is **not yet the completed plan**. In particular:
- Engine still uses the legacy mock OHLCV adapter; the new typed provider and Decimal portfolio ledger are not yet wired end-to-end. Engine positions are restored from journal snapshots, but event-by-event reconstruction is not complete.
- No complete event-by-event journal replay, short-position lifecycle, or recovery from every possible crash point. Long paper exits use stop-first handling when both stop and target occur in one OHLC bar.
- The LangGraph graph is a thin fan-out skeleton; it is not yet connected to selected modes, the shared risk manager, paper broker or portfolio ledger.
- No combined-signal conflict resolution, duplicate symbol/offsetting intent reconciliation, complete news-to-stock relationship graph, or validated corporate-action entitlement/cash-flow accounting.
- Risk management has per-trade sizing, open-position, daily-loss, drawdown, gross-exposure, lot-size and volume-participation checks, but still needs full exchange-calendar/event integration, sector/correlation exposure and more comprehensive daily P&L controls.
- No background scheduler, durable single controller across Streamlit sessions/processes, circuit breakers, or graceful drain/cancellation.
- Ollama/OpenRouter adapters are not yet wired into the news interpretation pipeline. No outcome persistence, chronological train/test evaluation, policy versioning/rollback, or UI/browser acceptance suite.
- Agent roster names are not proof that those agents exist. Unimplemented agents must remain visibly unimplemented.

Mock data is synthetic and cannot establish strategy accuracy or profitability. No return target is promised. Live trading remains deliberately absent. Do not use this branch for financial decisions until critical risk, accounting, persistence and lifecycle acceptance tests pass.

## Checks

```bash
pytest --cov=app --cov-report=term-missing
ruff check .
mypy app
```
