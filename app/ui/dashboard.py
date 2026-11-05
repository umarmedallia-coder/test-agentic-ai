import streamlit as st

from app.config import Settings
from app.services.engine import TradingEngine

st.set_page_config(page_title="Stock Engine", layout="wide")
st.title("NSE/BSE Paper Trading Engine")
st.caption("PAPER TRADING · MOCK DATA · LIVE ORDERS DISABLED")


@st.cache_resource
def get_engine() -> TradingEngine:
    """One controller per Streamlit process, shared across browser sessions."""
    return TradingEngine(Settings())


engine = get_engine()
start_col, stop_col, pause_col, resume_col, cycle_col = st.columns(5)
if start_col.button("Start", type="primary", disabled=engine.state == "running"):
    try:
        engine.start(automatic=True)
    except Exception as exc:
        st.error(str(exc))
if stop_col.button("Stop", disabled=engine.state != "running"):
    engine.stop()
if pause_col.button("Pause entries", disabled=engine.state != "running" or engine.paused):
    engine.pause_new_entries()
if resume_col.button("Resume", disabled=engine.state != "running" or not engine.paused):
    engine.resume()
if cycle_col.button("Run cycle", disabled=engine.state != "running"):
    try:
        engine.run_cycle()
    except Exception as exc:
        st.error(str(exc))

snapshot = engine.snapshot()
a, b, c, d, e = st.columns(5)
a.metric("Engine", snapshot["state"])
b.metric("Cash", f"₹{snapshot['cash']:,.2f}")
c.metric("Equity", f"₹{snapshot['equity']:,.2f}")
d.metric("Realized P&L", f"₹{snapshot['realized_pnl']:,.2f}")
e.metric("Open positions", len(snapshot["positions"]))
st.info(
    f"Mode: {snapshot['mode']} · Data: MOCK · Automatic scheduler: "
    f"{engine._scheduler_thread is not None and engine._scheduler_thread.is_alive()} · "
    f"Last cycle: {snapshot['last_cycle_at'] or 'not run'}"
)
st.caption(
    f"Unrealized P&L: ₹{snapshot['unrealized_pnl']:,.2f} · "
    f"Fees paid: ₹{snapshot['fees_paid']:,.2f} · "
    f"Entries paused: {snapshot['paused']}"
)
st.subheader("Open paper positions")
st.dataframe(
    [position.model_dump(mode="json") for position in snapshot["positions"]],
    use_container_width=True,
)
st.subheader("Agent Activity")
roster = [
    "Market Intelligence Agent", "Technical Analysis Agent", "Fundamental Analysis Agent",
    "News Intelligence Agent", "Corporate Actions Agent", "Institutional Activity Agent",
    "Risk Management Agent", "Stock Discovery Agent", "Strategy Agent",
    "Portfolio Intelligence Agent", "Debate/Critic Agent",
    "Recommendation Synthesis Agent", "News-to-Stock Impact Mapping Agent",
]
for name in roster:
    result = next((agent for agent in snapshot["agents"] if agent.agent_name == name), None)
    st.write(f"**{name}** — {result.status.value if result else 'unimplemented'}")
    if result:
        st.caption(result.conclusion)
st.caption("Mock results are not evidence of strategy profitability.")
