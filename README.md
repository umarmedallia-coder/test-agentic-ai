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

Headless one-cycle mode:

```bash
python -m app.cli start --mode paper
```

## Implemented in this branch

- Validated runtime configuration and foundational typed contracts.
- Deterministic mock OHLCV and quote data provider protocol.
- Existing EMA 9/21 technical analysis foundation.
- Basic shared risk sizing, append-only JSONL journal and exclusive writer lock.
- News normalization, exact alias mapping, duplicate suppression and conservative keyword impact heuristic.
- Corporate-action schema validation and conservative event-date entry block.
- Paper fill simulator with fee/slippage configuration and idempotent signal key.
- Decimal-based portfolio ledger with mark-to-market and duplicate-fill protection.
- Bounded async fan-out helper, LangGraph fan-out/fan-in graph, paper outcome report.
- Initial unit tests and GitHub Actions CI workflow.
- Existing Streamlit overview and 13-agent roster; only the implemented technical agent is reported as active.

## Known incomplete requirements

This branch is **not yet the completed plan**. In particular:
- Engine still uses the legacy mock adapter and in-memory positions; the new ledger and typed provider are not yet wired end-to-end.
- No journal event replay/restart restoration, close/exit lifecycle, or robust crash-safe lock recovery.
- The LangGraph graph is a thin fan-out skeleton; it is not yet connected to selected modes, the shared risk manager, paper broker or portfolio ledger.
- No combined-signal conflict resolution, duplicate symbol/offsetting intent reconciliation, complete news-to-stock relationship graph, or validated corporate-action entitlement/cash-flow accounting.
- Risk management still needs aggregate exposure, drawdown, liquidity, event, market-calendar, lot-size and daily realized/unrealized loss enforcement.
- No background scheduler, durable single controller across Streamlit sessions/processes, circuit breakers, or graceful drain/cancellation.
- No provider-backed Ollama/OpenRouter adapter, outcome persistence, chronological train/test evaluation, policy versioning/rollback, or UI/browser acceptance suite.
- Agent roster names are not proof that those agents exist. Unimplemented agents must remain visibly unimplemented.

Mock data is synthetic and cannot establish strategy accuracy or profitability. No return target is promised. Live trading remains deliberately absent. Do not use this branch for financial decisions until critical risk, accounting, persistence and lifecycle acceptance tests pass.

## Checks

```bash
pytest --cov=app --cov-report=term-missing
ruff check .
mypy app
```
