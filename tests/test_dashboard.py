from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_overview_page_loads_without_starting_engine():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app/ui/dashboard.py").run()
    assert not app.exception
    assert app.title[0].value == "NSE/BSE Agentic Paper Trading Engine"
    assert app.sidebar.radio[0].value == "Overview"


def test_agent_activity_page_loads_all_agent_cards():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app/ui/dashboard.py").run()
    app.sidebar.radio[0].set_value("Agent Activity").run()
    assert not app.exception
    assert len(app.markdown) >= 13
