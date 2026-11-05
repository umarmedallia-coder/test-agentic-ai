# NSE/BSE Agentic Stock Engine

Local Python paper-trading-first application. Initial market data is deterministic mock data. No broker integration or live-order execution path is present.

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

The Streamlit dashboard binds to loopback at http://localhost:8501. Start acquires the local journal writer lock. Run cycle triggers one deterministic mock analysis cycle. Pause entries does not close existing positions. Stop writes a lifecycle event and releases the lock.

Headless one-cycle mode:

```bash
python -m app.cli start --mode paper
```

## Current foundation

Implemented: validated configuration; typed data/evidence/agent/trade/position models; deterministic mock OHLCV and quote source; EMA 9/21 trend analysis; basic per-trade sizing and account guards; append-only JSONL journal with exclusive writer lock and corruption detection; in-process idempotent lifecycle; one-cycle paper simulation; Streamlit overview and 13-agent status roster; initial pytest coverage.

Not yet implemented: News Intelligence and evidence-backed stock impact mapping; Corporate Actions accounting; combined strategy reconciliation; dynamic parallel LangGraph workflows; asynchronous scheduler; durable process-wide controller across UI processes/tabs; full fill/fee/slippage/exit/mark-to-market accounting; restart reconstruction of positions; bounded recovery/circuit breakers; outcome evaluation and policy learning; animated telemetry; Ollama/OpenRouter adapter; browser acceptance tests; and release gates in `plan.md`.

The foundation is not a complete trading system. Its accounting and execution behavior are development scaffolding and must be completed and independently tested before relying on any simulation. Mock outcomes are not evidence of profitability. Live trading is intentionally absent.

## Quality checks

```bash
pytest
ruff check .
mypy app
```

CI should use deterministic mocks only; no paid model calls or live market data are required.
