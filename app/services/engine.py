import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from threading import Event, RLock, Thread, current_thread
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.config import Settings
from app.contracts import Signal
from app.data.mock import MockMarketData
from app.data.mock_provider import MockMarketDataProvider
from app.models import AgentResult, AgentStatus, Position
from app.services.execution import PaperBroker
from app.services.journal import JsonlJournal
from app.services.risk import RiskManager
from app.services.technical import analyze_technical
from app.services.strategy_pipelines import (
    run_corporate_actions_pipeline,
    run_news_pipeline,
)


class TradingEngine:
    """Single-process paper engine with journal snapshot recovery and fail-closed modes."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.data = MockMarketData()
        self.provider = MockMarketDataProvider()
        self.journal = JsonlJournal(settings.journal_dir)
        self.risk = RiskManager(settings)
        self.broker = PaperBroker()
        self._lock = RLock()
        self._scheduler_stop = Event()
        self._scheduler_thread: Thread | None = None
        self._started = False
        self.state = "idle"
        self.paused = False
        self.cash = settings.initial_capital_inr
        self.positions: list[Position] = []
        self.marks: dict[str, float] = {}
        self.realized_pnl = 0.0
        self.daily_realized_pnl = 0.0
        self.daily_pnl_date = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        self.daily_start_equity = settings.initial_capital_inr
        self.fees_paid = 0.0
        self.equity_peak = settings.initial_capital_inr
        self._processed_intents: set[str] = set()
        self.agents: list[AgentResult] = []
        self.errors: list[str] = []
        self.last_cycle_at: datetime | None = None

    @property
    def equity(self) -> float:
        market_value = sum(self.marks.get(p.symbol, p.entry_price) * p.quantity
                           for p in self.positions)
        return self.cash + market_value

    @property
    def unrealized_pnl(self) -> float:
        return sum(
            (self.marks.get(p.symbol, p.entry_price) - p.entry_price) * p.quantity
            - p.entry_fees for p in self.positions
        )

    def _restore(self, events: list[dict]) -> None:
        snapshots = [event for event in events if event.get("type") == "portfolio_snapshot"]
        if not snapshots:
            return
        snapshot = snapshots[-1]
        self.cash = float(snapshot["cash"])
        self.positions = [Position.model_validate(item) for item in snapshot.get("positions", [])]
        self.marks = {key: float(value) for key, value in snapshot.get("marks", {}).items()}
        self.realized_pnl = float(snapshot.get("realized_pnl", 0))
        self.daily_realized_pnl = float(snapshot.get("daily_realized_pnl", 0))
        self.daily_pnl_date = snapshot.get("daily_pnl_date", self.daily_pnl_date)
        self.daily_start_equity = float(snapshot.get("daily_start_equity", self.cash))
        self.fees_paid = float(snapshot.get("fees_paid", 0))
        self.equity_peak = float(snapshot.get("equity_peak", self.settings.initial_capital_inr))
        self._processed_intents = set(snapshot.get("processed_intents", []))

    def _persist(self) -> None:
        self.journal.append({
            "type": "portfolio_snapshot",
            "cash": self.cash,
            "positions": [position.model_dump(mode="json") for position in self.positions],
            "marks": self.marks,
            "realized_pnl": self.realized_pnl,
            "daily_realized_pnl": self.daily_realized_pnl,
            "daily_pnl_date": self.daily_pnl_date,
            "daily_start_equity": self.daily_start_equity,
            "fees_paid": self.fees_paid,
            "equity_peak": self.equity_peak,
            "processed_intents": sorted(self._processed_intents),
            "at": datetime.now(timezone.utc).isoformat(),
        })

    def start(self, automatic: bool = False) -> None:
        with self._lock:
            if self._started:
                if automatic:
                    self._start_scheduler()
                return
            self.journal.acquire()
            try:
                self._restore(self.journal.read_all())
                self.journal.append({
                    "type": "engine_started", "mode": self.settings.strategy_mode,
                    "at": datetime.now(timezone.utc).isoformat(),
                })
                self._started = True
                self.state = "running"
                if automatic:
                    self._start_scheduler()
            except Exception:
                self.journal.release()
                raise

    def _start_scheduler(self) -> None:
        if self._scheduler_thread is not None and self._scheduler_thread.is_alive():
            return
        self._scheduler_stop.clear()
        self._scheduler_thread = Thread(
            target=self._scheduler_loop, name="paper-cycle-scheduler", daemon=True,
        )
        self._scheduler_thread.start()

    def _scheduler_loop(self) -> None:
        while not self._scheduler_stop.is_set():
            for symbol in self.settings.watchlist:
                if self._scheduler_stop.is_set():
                    break
                try:
                    self.run_cycle(symbol=symbol, exchange=self.settings.default_exchange)
                except Exception as exc:
                    with self._lock:
                        self.errors.append(f"{symbol}: {type(exc).__name__}: {exc}")
                        if self._started:
                            self.journal.append({
                                "type": "scheduler_error", "symbol": symbol,
                                "error": f"{type(exc).__name__}: {exc}",
                                "at": datetime.now(timezone.utc).isoformat(),
                            })
            if self._scheduler_stop.wait(self.settings.cycle_interval_seconds):
                break

    def pause_new_entries(self) -> None:
        with self._lock:
            if self.state == "running":
                self.paused = True
                self.journal.append({"type": "entries_paused", "at": datetime.now(timezone.utc).isoformat()})

    def resume(self) -> None:
        with self._lock:
            if self.state == "running":
                self.paused = False
                self.journal.append({"type": "entries_resumed", "at": datetime.now(timezone.utc).isoformat()})

    def _roll_daily_pnl(self) -> None:
        trading_date = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        if trading_date != self.daily_pnl_date:
            self.daily_pnl_date = trading_date
            self.daily_realized_pnl = 0.0
            self.daily_start_equity = self.equity

    @property
    def daily_pnl(self) -> float:
        return self.equity - self.daily_start_equity

    def _close_triggered_positions(self, symbol: str, bar: dict) -> None:
        remaining: list[Position] = []
        for position in self.positions:
            if position.symbol != symbol or position.direction != "long":
                remaining.append(position)
                continue
            stop_hit = float(bar["low"]) <= position.stop_price
            target_hit = float(bar["high"]) >= position.target_price
            if not stop_hit and not target_hit:
                remaining.append(position)
                continue
            # If both levels occur in one OHLC bar, assume the adverse stop filled first.
            reason = "stop_loss" if stop_hit else "take_profit"
            trigger_price = position.stop_price if stop_hit else position.target_price
            exit_signal = Signal(
                signal_id=f"exit-{position.intent_id}-{uuid4()}",
                strategy="position_exit", symbol=position.symbol, exchange=position.exchange,
                direction="short", entry=Decimal(str(trigger_price)),
                stop=Decimal(str(trigger_price * 1.01)),
                target=Decimal(str(trigger_price * 0.99)), confidence=1,
                rationale=reason,
            )
            fill = self.broker.execute(exit_signal, position.quantity, Decimal(str(trigger_price)))
            proceeds = float(fill.price) * fill.quantity - float(fill.fees)
            net = (float(fill.price) - position.entry_price) * fill.quantity
            net -= position.entry_fees + float(fill.fees)
            self.cash += proceeds
            self.realized_pnl += net
            self.daily_realized_pnl += net
            self.fees_paid += float(fill.fees)
            self.journal.append({
                "type": "position_closed", "intent_id": position.intent_id,
                "exit_fill": fill.model_dump(mode="json"), "reason": reason,
                "net_pnl": net, "at": fill.filled_at.isoformat(),
            })
        self.positions = remaining

    def run_cycle(self, symbol: str = "RELIANCE", exchange: str = "NSE") -> None:
        with self._lock:
            if not self._started:
                raise RuntimeError("Engine is not running")
            envelope = self.data.historical_prices(symbol, exchange)
            bars = envelope.payload["bars"]
            latest = bars[-1]
            last_price = float(latest["close"])
            self.marks[symbol] = last_price
            self._roll_daily_pnl()
            self._close_triggered_positions(symbol, latest)

            mode = self.settings.strategy_mode
            technical_agent, technical_intent = analyze_technical(symbol, exchange, bars)
            intent = None
            if mode == "technical":
                self.agents = [technical_agent]
                intent = technical_intent
            elif mode == "news":
                atr = float(technical_agent.findings.get("atr_14", 0))
                news_agent, intent = asyncio.run(
                    run_news_pipeline(self.provider, symbol, last_price, atr)
                )
                self.agents = [technical_agent, news_agent]
            elif mode == "corporate_actions":
                action_agent, blocked = asyncio.run(
                    run_corporate_actions_pipeline(
                        self.provider, symbol, date.today(),
                    )
                )
                self.agents = [action_agent]
                if blocked:
                    self.journal.append({
                        "type": "entry_blocked", "reason": "corporate_action",
                        "symbol": symbol, "at": datetime.now(timezone.utc).isoformat(),
                    })
            else:
                atr = float(technical_agent.findings.get("atr_14", 0))
                news_agent, news_intent = asyncio.run(
                    run_news_pipeline(self.provider, symbol, last_price, atr)
                )
                action_agent, action_blocked = asyncio.run(
                    run_corporate_actions_pipeline(
                        self.provider, symbol, date.today(),
                    )
                )
                self.agents = [technical_agent, news_agent, action_agent]
                # Combined mode requires all independent evidence pipelines to succeed.
                if (
                    technical_intent is not None
                    and news_intent is not None
                    and news_intent.direction == technical_intent.direction
                    and action_agent.status == AgentStatus.SUCCEEDED
                    and not action_blocked
                ):
                    technical_intent.strategy = "combined"
                    intent = technical_intent

            if intent is not None and not self.paused:
                if intent.direction != "long":
                    self.journal.append({
                        "type": "entry_rejected", "reason": "short paper execution is not enabled",
                        "symbol": symbol, "intent_id": intent.id,
                    })
                elif any(position.symbol == symbol for position in self.positions):
                    self.journal.append({
                        "type": "entry_rejected", "reason": "position already open",
                        "symbol": symbol, "at": datetime.now(timezone.utc).isoformat(),
                    })
                elif intent.id in self._processed_intents:
                    self.journal.append({
                        "type": "entry_rejected", "reason": "duplicate intent",
                        "intent_id": intent.id,
                    })
                else:
                    average_volume = int(
                        sum(int(row["volume"]) for row in bars[-20:]) / min(20, len(bars))
                    )
                    decision = self.risk.validate(
                        intent, self.equity, self.daily_pnl, len(self.positions), self.cash,
                        equity_peak=self.equity_peak, current_exposure=self.equity - self.cash,
                        average_volume=average_volume,
                    )
                    self.journal.append({
                        "type": "risk_decision", "intent": intent.model_dump(mode="json"),
                        "decision": decision.model_dump(mode="json"),
                    })
                    self._processed_intents.add(intent.id)
                    if decision.accepted:
                        signal = Signal(
                            strategy=intent.strategy, symbol=intent.symbol, exchange=intent.exchange,
                            direction=intent.direction, entry=Decimal(str(intent.entry_price)),
                            stop=Decimal(str(intent.stop_price)), target=Decimal(str(intent.target_price)),
                            confidence=0.7, rationale=f"{intent.strategy} strategy signal",
                        )
                        fill = self.broker.execute(
                            signal, decision.approved_quantity, Decimal(str(intent.entry_price))
                        )
                        total_cost = float(fill.price) * fill.quantity + float(fill.fees)
                        if total_cost > self.cash:
                            self.journal.append({
                                "type": "entry_rejected", "reason": "execution cost exceeds available cash",
                                "intent_id": intent.id,
                            })
                        else:
                            self.cash -= total_cost
                            self.fees_paid += float(fill.fees)
                            self.positions.append(Position(
                                intent_id=intent.id, symbol=intent.symbol, exchange=intent.exchange,
                                direction="long", quantity=fill.quantity, entry_price=float(fill.price),
                                stop_price=intent.stop_price, target_price=intent.target_price,
                                policy_version=intent.policy_version, entry_fees=float(fill.fees),
                                entry_fill_id=fill.fill_id,
                            ))
                            self._persist()
                            self.journal.append({
                                "type": "paper_fill", "fill": fill.model_dump(mode="json"),
                                "intent_id": intent.id,
                            })
            self.last_cycle_at = datetime.now(timezone.utc)
            self.equity_peak = max(self.equity_peak, self.equity)
            self._persist()

    def stop(self) -> None:
        self._scheduler_stop.set()
        thread = self._scheduler_thread
        if thread is not None and thread.is_alive() and thread is not current_thread():
            thread.join(timeout=self.settings.agent_timeout_seconds)
            if thread.is_alive():
                raise RuntimeError("Scheduler did not drain before stop timeout")
        with self._lock:
            if self._started:
                self._persist()
                self.journal.append({
                    "type": "engine_stopped", "open_positions": len(self.positions),
                    "at": datetime.now(timezone.utc).isoformat(),
                })
                self.journal.release()
            self._started = False
            self._scheduler_thread = None
            self.state = "stopped"

    def snapshot(self) -> dict:
        return {
            "state": self.state, "mode": self.settings.strategy_mode, "is_mock": True,
            "cash": self.cash, "equity": self.equity, "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl, "daily_pnl": self.daily_pnl,
            "fees_paid": self.fees_paid,
            "positions": self.positions, "agents": self.agents, "errors": self.errors,
            "last_cycle_at": self.last_cycle_at, "paused": self.paused,
            "scheduler_active": self._scheduler_thread is not None and self._scheduler_thread.is_alive(),
        }
