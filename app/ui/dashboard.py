"""Two-page local Streamlit dashboard backed only by engine snapshots."""
import streamlit as st
from typing import Literal, cast

from app.config import Settings
from app.models import AgentStatus
from app.services.engine import TradingEngine

st.set_page_config(page_title="NSE/BSE Paper Engine", layout="wide")
st.title("NSE/BSE Agentic Paper Trading Engine")
st.caption("PAPER TRADING · LIVE ORDERS DISABLED")
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
    start_col, stop_col, pause_col, resume_col, cycle_col, discover_col = st.columns(6)
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
    if discover_col.button("Discover universe", disabled=engine.state != "running"):
        try:
            result = engine.run_stock_discovery()
            st.success(
                f"Scanned {result.findings.get('scanned_count', 0)} symbols; "
                f"{result.findings.get('eligible_count', 0)} candidates passed filters."
            )
        except Exception as exc:
            st.error(f"Discovery failed: {exc}")

    @st.fragment(run_every="5s")
    def render_overview() -> None:
        snapshot = engine.snapshot()
        drawdown = (
            max(0.0, (engine.equity_peak - snapshot["equity"]) / engine.equity_peak)
            if snapshot["equity"] is not None else None
        )
        a, b, c, d, e = st.columns(5)
        a.metric("Engine", snapshot["state"])
        b.metric("Cash", f"₹{snapshot['cash']:,.2f}")
        equity_label = f"₹{snapshot['equity']:,.2f}" if snapshot["equity"] is not None else "Unavailable"
        c.metric("Equity", equity_label)
        d.metric("Realized P&L", f"₹{snapshot['realized_pnl']:,.2f}")
        e.metric("Open positions", len(snapshot["positions"]))
        data_label = "MOCK" if snapshot["is_mock"] else "REAL"
        freshness = (
            f"{snapshot['data_freshness_seconds']}s old"
            if snapshot["data_freshness_seconds"] is not None else "unknown"
        )
        st.info(
            f"Mode: {snapshot['mode']} · Data: {data_label} ({snapshot['data_source'] or 'not loaded'}) · "
            f"As of: {snapshot['data_as_of'] or 'not available'} · Freshness: {freshness} · "
            f"Scheduler: {snapshot['scheduler_active']} · Last cycle: "
            f"{snapshot['last_cycle_at'] or 'not run'} · Next cycle: "
            f"{snapshot['next_cycle_at'] or 'not scheduled'}"
        )
        unrealized_value = snapshot["unrealized_pnl"]
        unrealized_label = (
            f"₹{unrealized_value:,.2f}" if unrealized_value is not None else "Unavailable"
        )
        daily_pnl_label = (
            f"₹{snapshot['daily_pnl']:,.2f}"
            if snapshot["daily_pnl"] is not None else "Unavailable"
        )
        drawdown_label = f"{drawdown:.2%}" if drawdown is not None else "Unavailable"
        st.caption(
            f"Unrealized P&L: {unrealized_label} · "
            f"Daily P&L: {daily_pnl_label} · "
            f"Fees: ₹{snapshot['fees_paid']:,.2f} · "
            f"Peak-to-current drawdown: {drawdown_label} · "
            f"Entries paused: {snapshot['paused']} · "
            f"Policy: {snapshot['active_policy']['version']}"
        )
        st.subheader("Open paper positions")
        st.dataframe(
            snapshot["open_trades"],
            use_container_width=True,
        )
        st.subheader("Completed paper trades")
        completed = [outcome.model_dump(mode="json") for outcome in snapshot["outcomes"]]
        completed_symbols = ["All"] + sorted({row["symbol"] for row in completed})
        selected_symbol = st.selectbox("Completed-trade symbol", completed_symbols)
        if selected_symbol != "All":
            completed = [row for row in completed if row["symbol"] == selected_symbol]
        st.dataframe(completed, use_container_width=True)
        st.subheader("Strategy attribution")
        st.dataframe(snapshot["strategy_performance"], use_container_width=True)
        if not snapshot["strategy_attribution_reconciles"]:
            st.warning("Strategy-level net P&L does not reconcile to completed account outcomes.")
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
