"""Two-page local Streamlit dashboard backed only by engine snapshots."""
import streamlit as st
from typing import Literal, cast

from app.config import Settings
from app.models import AgentStatus
from app.services.engine import TradingEngine

st.set_page_config(page_title="NSE/BSE Paper Engine", layout="wide")
st.title("NSE/BSE Agentic Paper Trading Engine")
st.caption("PAPER TRADING · MOCK DATA · LIVE ORDERS DISABLED")
reduced_motion = st.sidebar.checkbox("Reduce motion", value=False)
if not reduced_motion:
    st.markdown(
        """
        <style>
        @keyframes agent-pulse {
            0% { opacity: .55; transform: scale(.985); }
            50% { opacity: 1; transform: scale(1); }
            100% { opacity: .55; transform: scale(.985); }
        }
        .agent-running { animation: agent-pulse 1.5s ease-in-out infinite; }
        @media (prefers-reduced-motion: reduce) {
            .agent-running { animation: none !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def get_engine() -> TradingEngine:
    """One process-wide controller shared by browser sessions and tabs."""
    return TradingEngine(Settings())


engine = get_engine()
page = st.sidebar.radio("Workspace", ["Overview", "Agent Activity"])
if engine.state != "running":
    selected_mode = st.sidebar.selectbox(
        "Strategy mode",
        ["technical", "news", "corporate_actions", "combined"],
        index=["technical", "news", "corporate_actions", "combined"].index(
            engine.settings.strategy_mode
        ),
        help="Mode changes apply to the next engine start; open positions retain their original policy.",
    )
    if selected_mode != engine.settings.strategy_mode:
        engine.settings.strategy_mode = cast(
            Literal["technical", "news", "corporate_actions", "combined"], selected_mode,
        )

if page == "Overview":
    start_col, stop_col, pause_col, resume_col, cycle_col = st.columns(5)
    if start_col.button("Start", type="primary", disabled=engine.state == "running"):
        try:
            engine.start(automatic=True)
        except Exception as exc:
            st.error(f"Start rejected: {exc}")
    if stop_col.button("Stop", disabled=engine.state != "running"):
        try:
            engine.stop()
        except Exception as exc:
            st.error(f"Stop failed: {exc}")
    if pause_col.button("Pause entries", disabled=engine.state != "running" or engine.paused):
        engine.pause_new_entries()
    if resume_col.button("Resume", disabled=engine.state != "running" or not engine.paused):
        engine.resume()
    if cycle_col.button("Run cycle", disabled=engine.state != "running"):
        try:
            engine.run_cycle()
        except Exception as exc:
            st.error(f"Cycle failed: {exc}")

    @st.fragment(run_every="5s")
    def render_overview() -> None:
        snapshot = engine.snapshot()
        drawdown = max(0.0, (engine.equity_peak - snapshot["equity"]) / engine.equity_peak)
        a, b, c, d, e = st.columns(5)
        a.metric("Engine", snapshot["state"])
        b.metric("Cash", f"₹{snapshot['cash']:,.2f}")
        c.metric("Equity", f"₹{snapshot['equity']:,.2f}")
        d.metric("Realized P&L", f"₹{snapshot['realized_pnl']:,.2f}")
        e.metric("Open positions", len(snapshot["positions"]))
        st.info(
            f"Mode: {snapshot['mode']} · Data: MOCK · Scheduler: "
            f"{snapshot['scheduler_active']} · Last cycle: "
            f"{snapshot['last_cycle_at'] or 'not run'}"
        )
        unrealized_value = snapshot["unrealized_pnl"]
        unrealized_label = (
            f"₹{unrealized_value:,.2f}" if unrealized_value is not None else "Unavailable"
        )
        st.caption(
            f"Unrealized P&L: {unrealized_label} · "
            f"Daily P&L: ₹{snapshot['daily_pnl']:,.2f} · "
            f"Fees: ₹{snapshot['fees_paid']:,.2f} · "
            f"Peak-to-current drawdown: {drawdown:.2%} · "
            f"Entries paused: {snapshot['paused']}"
        )
        st.subheader("Open paper positions")
        st.dataframe(
            [position.model_dump(mode="json") for position in snapshot["positions"]],
            use_container_width=True,
        )
        st.subheader("Completed paper trades")
        st.dataframe(
            [outcome.model_dump(mode="json") for outcome in snapshot["outcomes"]],
            use_container_width=True,
        )
        st.subheader("Learning review")
        report = engine.learning_report()
        st.write(
            f"Samples: {report.sample_count} · Win rate: {report.win_rate:.1%} · "
            f"Net P&L: ₹{report.net_pnl:,.2f}"
        )
        st.caption(report.recommendation)
        if snapshot["errors"]:
            st.subheader("Operational errors")
            for error in snapshot["errors"][-10:]:
                st.error(error)
        st.caption("Synthetic mock data is not evidence of strategy profitability.")

    render_overview()

else:
    st.subheader("Agent Activity")
    st.caption("Statuses are derived from actual engine results. No fabricated progress is shown.")
    roster = [
        ("Market Intelligence Agent", "Benchmark-based risk-on, risk-off or mixed context"),
        ("Technical Analysis Agent", "Deterministic price and volume indicators"),
        ("Fundamental Analysis Agent", "On-demand financial statement analysis"),
        ("News Intelligence Agent", "News deduplication, facts and event impact"),
        ("Corporate Actions Agent", "Announcement validation and event restrictions"),
        ("Institutional Activity Agent", "On-demand institutional flow evidence"),
        ("Risk Management Agent", "Deterministic account-wide risk gate"),
        ("Stock Discovery Agent", "On-demand candidate discovery"),
        ("Strategy Agent", "Versioned strategy and horizon policy"),
        ("Portfolio Intelligence Agent", "Marked exposure, cash allocation and concentration review"),
        ("Debate/Critic Agent", "Configured contradiction and evidence review"),
        ("Recommendation Synthesis Agent", "Evidence-backed decision synthesis"),
        ("News-to-Stock Impact Mapping Agent", "Direct and evidenced indirect exposure mapping"),
    ]

    @st.fragment(run_every="5s")
    def render_activity() -> None:
        snapshot = engine.snapshot()
        active = {agent.agent_name: agent for agent in snapshot["agents"]}
        for name, responsibility in roster:
            result = active.get(name)
            status = result.status if result else AgentStatus.UNIMPLEMENTED
            with st.container(border=True):
                left, right = st.columns([3, 1])
                left.markdown(f"**{name}**")
                left.caption(responsibility)
                status_label = status.value.replace("_", " ").title()
                css_class = "agent-running" if status == AgentStatus.RUNNING and not reduced_motion else ""
                right.markdown(
                    f'<div class="{css_class}"><strong>{status_label}</strong></div>',
                    unsafe_allow_html=True,
                )
                if result:
                    st.write(result.conclusion)
                    if result.findings:
                        st.json(result.findings)
                    if result.errors:
                        for error in result.errors:
                            st.error(error)
                    st.caption(
                        f"Task ID: {result.task_id} · "
                        f"Instrument: {result.symbol or '—'} / {result.exchange or '—'}"
                    )
        st.caption(
            f"Snapshot last updated: {snapshot['last_cycle_at'] or 'no cycle yet'} · "
            f"Engine state: {snapshot['state']}"
        )

    render_activity()
