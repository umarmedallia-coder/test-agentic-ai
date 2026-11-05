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
    args = parser.parse_args()
    if args.command == "ui":
        print("Dashboard: http://localhost:8501")
        stcli.main_run(["app/ui/dashboard.py", "--server.address=127.0.0.1"])
        return
    engine = TradingEngine(Settings())
    try:
        engine.start()
        engine.run_cycle()
        print(engine.snapshot())
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()


if __name__ == "__main__":
    main()
