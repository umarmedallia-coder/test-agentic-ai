import argparse

import streamlit.web.cli as stcli

from app.config import Settings
from app.services.engine import TradingEngine


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ui")
    start = sub.add_parser("start")
    start.add_argument("--mode", choices=["paper"], default="paper")
    start.add_argument(
        "--strategy-mode",
        choices=["technical", "news", "corporate_actions", "combined"],
        default="technical",
    )
    start.add_argument("--symbol", default="RELIANCE")
    start.add_argument("--exchange", choices=["NSE", "BSE"], default="NSE")
    args = parser.parse_args()
    if args.command == "ui":
        print("Dashboard: http://localhost:8501")
        stcli.main_run(["app/ui/dashboard.py", "--server.address=127.0.0.1"])
        return

    # Execution mode is deliberately paper-only; strategy selection is independent.
    settings = Settings(strategy_mode=args.strategy_mode)
    engine = TradingEngine(settings)
    try:
        engine.start()
        engine.run_cycle(symbol=args.symbol, exchange=args.exchange)
        print(engine.snapshot())
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()


if __name__ == "__main__":
    main()
