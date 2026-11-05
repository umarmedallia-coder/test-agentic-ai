from pathlib import Path

from streamlit.testing.v1 import AppTest


DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "app" / "ui" / "dashboard.py"


def test_overview_page_loads_without_starting_engine():
    app = AppTest.from_file(DASHBOARD_PATH).run()
    assert not app.exception
    assert app.title[0].value == "NSE/BSE Agentic Paper Trading Engine"
    assert app.sidebar.radio[0].value == "Overview"


def test_agent_activity_page_loads_all_agent_cards():
    app = AppTest.from_file(DASHBOARD_PATH).run()
    app.sidebar.radio[0].set_value("Agent Activity").run()
    assert not app.exception
    assert len(app.markdown) >= 13


def test_overview_exposes_policy_history_without_offering_unvalidated_promotion():
    app = AppTest.from_file(DASHBOARD_PATH).run()
    assert not app.exception
    assert any("paper policy" in item.value.lower() for item in app.caption)
    assert not any("promote candidate" in item.label.lower() for item in app.button)
