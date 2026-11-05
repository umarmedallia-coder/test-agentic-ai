import asyncio
import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from threading import Event, RLock, Thread, current_thread
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.config import Settings
from app.agents.contracts import DiscoveryCandidate
from app.agents.critic import critique_evidence
from app.agents.fundamental import analyze_fundamentals
from app.agents.institutional_activity import analyze_institutional_activity
from app.agents.stock_discovery import discover_stocks
from app.agents.strategy import evaluate_strategy
from app.agents.synthesis import synthesize_recommendation
from app.contracts import CorporateActionRecord, PaperFill, Signal, TradeOutcome
from app.data.mock_provider import MockMarketDataProvider
from app.models import AgentResult, AgentStatus, Position, RiskDecision
from app.services.execution import PaperBroker
from app.services.journal import JsonlJournal
from app.services.learning import (
    CandidateEvaluation, PaperPolicy, PaperPolicyRegistry, evaluate_outcomes,
)
from app.services.intent_reconciliation import reconcile_intents
from app.services.risk import RiskManager
from app.services.portfolio import PortfolioLedger
from app.services.portfolio_intelligence import analyze_portfolio
from app.services.market_intelligence import run_market_intelligence
from app.services.technical import analyze_technical
from app.services.workflow import build_strategy_graph
from app.llm.factory import build_llm_provider
from app.services.strategy_pipelines import (
    run_corporate_actions_pipeline,
    run_news_pipeline,
)


class TradingEngine:
    """Single-process paper engine with journal snapshot recovery and fail-closed modes."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = MockMarketDataProvider()
        self.llm_provider = build_llm_provider(settings)
        self.journal = JsonlJournal(settings.journal_dir)
        self.risk = RiskManager(settings)
        self.broker = PaperBroker()
        self.ledger = PortfolioLedger(Decimal(str(settings.initial_capital_inr)))
        self._lock = RLock()
        self._scheduler_stop = Event()
        self._scheduler_thread: Thread | None = None
        self._started = False
        self.state = "idle"
        self.paused = False
        self.positions: list[Position] = []
        self.marks: dict[str, float] = {}
        self.realized_pnl = 0.0
        self.daily_realized_pnl = 0.0
        self.daily_pnl_date = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        self.daily_start_equity = settings.initial_capital_inr
        self.fees_paid = 0.0
        self.outcomes: list[TradeOutcome] = []
        self.policy_registry = PaperPolicyRegistry(
            PaperPolicy(version="paper-baseline-v1"),
        )
        self.equity_peak = settings.initial_capital_inr
        self._processed_intents: set[str] = set()
        self.processed_corporate_actions: set[str] = set()
        self.agents: list[AgentResult] = []
        self.errors: list[str] = []
        self.last_cycle_at: datetime | None = None
        self.last_data_as_of: datetime | None = None
        self.last_data_freshness_seconds: int | None = None
        self.last_data_source: str | None = None
        self.last_data_is_mock = True
        self.next_cycle_at: datetime | None = None

    @property
    def cash(self) -> float:
        return float(self.ledger.cash)

    @cash.setter
    def cash(self, value: float | Decimal) -> None:
        self.ledger.cash = Decimal(str(value))

    @property
    def equity(self) -> float:
        value = self.ledger.equity
        if value is None:
            raise ValueError("portfolio equity unavailable because an open position has no valid mark")
        return float(value)

    @property
    def unrealized_pnl(self) -> float | None:
        value = self.ledger.unrealized_pnl
        return float(value) if value is not None else None

    def _restore(self, events: list[dict]) -> None:
        snapshots = [event for event in events if event.get("type") == "portfolio_snapshot"]
        if not snapshots:
            return
        snapshot = snapshots[-1]
        self.cash = float(snapshot["cash"])
        self.positions = [Position.model_validate(item) for item in snapshot.get("positions", [])]
        self.marks = {key: float(value) for key, value in snapshot.get("marks", {}).items()}
        self.realized_pnl = float(snapshot.get("realized_pnl", 0))
        ledger_snapshot = snapshot.get("ledger")
        if ledger_snapshot:
            self.ledger.restore(ledger_snapshot)
        else:
            # Upgrade legacy snapshots into the canonical Decimal ledger.
            self.ledger = PortfolioLedger(Decimal(str(self.settings.initial_capital_inr)))
            for position in self.positions:
                self.ledger.apply_buy(PaperFill(
                    fill_id=position.entry_fill_id or position.intent_id,
                    signal_id=position.intent_id, symbol=position.symbol, side="buy",
                    quantity=position.quantity, price=Decimal(str(position.entry_price)),
                    fees=Decimal(str(position.entry_fees)), filled_at=position.opened_at,
                ))
                self.ledger.mark(
                    position.symbol,
                    Decimal(str(self.marks.get(position.symbol, position.entry_price))),
                )
            self.ledger.cash = Decimal(str(snapshot["cash"]))
            self.ledger.realized_pnl = Decimal(str(self.realized_pnl))
        self.daily_realized_pnl = float(snapshot.get("daily_realized_pnl", 0))
        self.daily_pnl_date = snapshot.get("daily_pnl_date", self.daily_pnl_date)
        self.daily_start_equity = float(snapshot.get("daily_start_equity", self.cash))
        self.fees_paid = float(snapshot.get("fees_paid", 0))
        self.outcomes = [
            TradeOutcome.model_validate(item) for item in snapshot.get("outcomes", [])
        ]
        if snapshot.get("policy_history"):
            self.policy_registry = PaperPolicyRegistry.from_snapshot(
                snapshot["policy_history"],
            )
        self.equity_peak = float(snapshot.get("equity_peak", self.settings.initial_capital_inr))
        self._processed_intents = set(snapshot.get("processed_intents", []))
        self.processed_corporate_actions = set(snapshot.get("processed_corporate_actions", []))

    def _persist(self) -> None:
        self.journal.append({
            "type": "portfolio_snapshot",
            "cash": self.cash,
            "ledger": self.ledger.snapshot(),
            "positions": [position.model_dump(mode="json") for position in self.positions],
            "marks": self.marks,
            "realized_pnl": self.realized_pnl,
            "daily_realized_pnl": self.daily_realized_pnl,
            "daily_pnl_date": self.daily_pnl_date,
            "daily_start_equity": self.daily_start_equity,
            "fees_paid": self.fees_paid,
            "outcomes": [outcome.model_dump(mode="json") for outcome in self.outcomes],
            "policy_history": self.policy_registry.snapshot(),
            "equity_peak": self.equity_peak,
            "processed_intents": sorted(self._processed_intents),
            "processed_corporate_actions": sorted(self.processed_corporate_actions),
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
            self.next_cycle_at = datetime.now(timezone.utc) + timedelta(
                seconds=self.settings.cycle_interval_seconds,
            )
            if self._scheduler_stop.wait(self.settings.cycle_interval_seconds):
                self.next_cycle_at = None
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

    def _apply_due_corporate_actions(
        self, action_agent: AgentResult, symbol: str, trading_day: date,
    ) -> bool:
        """Apply verified ex-date split/dividend effects once; return a fail-closed block."""
        blocked = action_agent.status == AgentStatus.FAILED
        raw_actions = action_agent.findings.get("actions", [])
        for raw in raw_actions:
            try:
                record = CorporateActionRecord.model_validate(raw)
                if record.action_id in self.processed_corporate_actions:
                    continue
                if not record.verified:
                    blocked = True
                    continue
                if record.ex_date is None or record.ex_date.date() > trading_day:
                    continue
                position = next(
                    (item for item in self.positions if item.symbol == record.symbol),
                    None,
                )
                action_type = record.action_type.lower()
                if position is not None and action_type in {"split", "bonus"}:
                    if record.ratio_from is None or record.ratio_to is None:
                        raise ValueError("split/bonus action is missing its ratio")
                    adjusted = self.ledger.apply_split(
                        record.symbol, record.ratio_from, record.ratio_to,
                        action_id=record.action_id,
                    )
                    if adjusted is None:
                        raise ValueError("split action did not resolve an open ledger position")
                    quantity, average_entry = adjusted
                    factor = float(record.ratio_from / record.ratio_to)
                    position.quantity = quantity
                    position.entry_price = float(average_entry)
                    position.stop_price *= factor
                    position.target_price *= factor
                    if record.symbol in self.marks:
                        self.marks[record.symbol] *= factor
                        self.ledger.mark(
                            record.symbol, Decimal(str(self.marks[record.symbol])),
                        )
                elif position is not None and action_type == "dividend":
                    if position.opened_at.date() < record.ex_date.date():
                        cash_per_share = Decimal(str(record.cash_amount or 0))
                        cashflow = self.ledger.apply_dividend(
                            record.symbol, cash_per_share, action_id=record.action_id,
                        )
                        self.realized_pnl = float(self.ledger.realized_pnl)
                        self.daily_realized_pnl += float(cashflow)
                self.processed_corporate_actions.add(record.action_id)
                self._persist()
                self.journal.append({
                    "type": "corporate_action_applied",
                    "action_id": record.action_id, "symbol": record.symbol,
                    "action_type": action_type,
                    "at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as exc:
                blocked = True
                self.errors.append(
                    f"corporate action {raw.get('action_id', 'unknown')}: "
                    f"{type(exc).__name__}: {exc}"
                )
                self.journal.append({
                    "type": "corporate_action_failed",
                    "symbol": symbol, "error": str(exc),
                    "at": datetime.now(timezone.utc).isoformat(),
                })
        return blocked

    @staticmethod
    def _stable_intent_id(intent, bar_timestamp: datetime) -> str:
        """Stable idempotency key for one strategy decision on one completed bar."""
        parts = (
            intent.symbol.upper(), intent.exchange.upper(), intent.strategy,
            intent.direction, format(intent.entry_price, ".12g"),
            format(intent.stop_price, ".12g"), format(intent.target_price, ".12g"),
            intent.policy_version, bar_timestamp.isoformat(),
        )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def _news_mapping_agent(
        self, news_agent: AgentResult, symbol: str, exchange: str,
    ) -> AgentResult:
        mapped = news_agent.findings.get("affected_securities", [])
        status = news_agent.status
        if status == AgentStatus.SUCCEEDED and not mapped:
            status = AgentStatus.SKIPPED
        return AgentResult(
            agent_name="News-to-Stock Impact Mapping Agent",
            status=status, symbol=symbol, exchange=exchange,
            conclusion=(
                "Direct and evidence-backed related securities mapped."
                if mapped else "No mapped securities available from the news feed."
            ),
            findings={"affected_securities": mapped},
            errors=news_agent.errors,
        )

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
        close_events: list[dict] = []
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
            entry_price = Decimal(str(position.entry_price))
            gross_decimal = (fill.price - entry_price) * fill.quantity
            total_fees_decimal = Decimal(str(position.entry_fees)) + fill.fees
            net_decimal = gross_decimal - total_fees_decimal
            net = float(net_decimal)
            outcome = TradeOutcome(
                fill_id=position.entry_fill_id or position.intent_id,
                entry_fill_id=position.entry_fill_id,
                exit_fill_id=fill.fill_id,
                symbol=position.symbol, entry_price=entry_price,
                exit_price=fill.price, quantity=fill.quantity,
                gross_pnl=gross_decimal, fees=total_fees_decimal,
                net_pnl=net_decimal, reason=reason,
                policy_version=position.policy_version, strategy=position.strategy,
                sector=position.sector, entry_at=position.opened_at, closed_at=fill.filled_at,
            )
            ledger_net = self.ledger.apply_sell(fill)
            self.realized_pnl = float(self.ledger.realized_pnl)
            self.daily_realized_pnl += float(ledger_net)
            self.fees_paid += float(fill.fees)
            self.outcomes.append(outcome)
            close_events.append({
                "type": "position_closed", "intent_id": position.intent_id,
                "exit_fill": fill.model_dump(mode="json"),
                "outcome": outcome.model_dump(mode="json"),
                "reason": reason, "net_pnl": net, "at": fill.filled_at.isoformat(),
            })
        self.positions = remaining
        if close_events:
            # Persist the resulting portfolio before appending descriptive close events.
            self._persist()
            for event in close_events:
                self.journal.append(event)

    def run_stock_discovery(self, limit: int | None = None) -> AgentResult:
        """Scan a bounded provider universe using validated OHLCV and active paper policy."""
        with self._lock:
            if not self._started:
                raise RuntimeError("Engine must be running to discover stocks")
            maximum = limit if limit is not None else self.settings.discovery_max_symbols
            if maximum < 1 or maximum > 500:
                raise ValueError("discovery limit must be between 1 and 500")

            async def scan_universe():
                universe = await asyncio.wait_for(
                    self.provider.get_stock_universe(self.settings.default_exchange),
                    timeout=self.settings.agent_timeout_seconds,
                )
                if universe.status.value != "ok" or not universe.payload:
                    return universe, [], {}, 0, 0
                if universe.freshness_seconds > self.settings.max_market_data_freshness_seconds:
                    return universe, [], {"__universe__": "stale universe snapshot"}, len(universe.payload), 0
                symbols = list(dict.fromkeys(item.strip().upper() for item in universe.payload if item.strip()))
                selected = symbols[:maximum]
                concurrency = (
                    self.settings.max_concurrent_tool_calls
                    if self.settings.enable_parallel_execution else 1
                )
                semaphore = asyncio.Semaphore(concurrency)

                async def collect_one(symbol: str):
                    async with semaphore:
                        try:
                            validation = await asyncio.wait_for(
                                self.provider.validate_stock_symbol(
                                    symbol, self.settings.default_exchange,
                                ),
                                timeout=self.settings.agent_timeout_seconds,
                            )
                            if validation.status.value != "ok" or validation.payload is not True:
                                return None, "symbol validation failed"
                            now = datetime.now(timezone.utc)
                            history = await asyncio.wait_for(
                                self.provider.get_historical_prices(
                                    symbol, now - timedelta(days=80), now,
                                    self.settings.default_exchange,
                                ),
                                timeout=self.settings.agent_timeout_seconds,
                            )
                            if (
                                history.status.value != "ok" or not history.payload
                                or history.freshness_seconds > self.settings.max_market_data_freshness_seconds
                            ):
                                return None, f"history unavailable or stale: {history.status.value}"
                            bars = [bar.model_dump(mode="python") for bar in history.payload]
                            timestamps = [bar["timestamp"] for bar in bars]
                            if (
                                len(bars) < 35
                                or any(bar["symbol"].upper() != symbol for bar in bars)
                                or any(bar["exchange"] != self.settings.default_exchange for bar in bars)
                                or timestamps != sorted(timestamps)
                                or len(set(timestamps)) != len(timestamps)
                            ):
                                return None, "history failed symbol, exchange, ordering or length validation"
                            technical, _ = analyze_technical(
                                symbol, self.settings.default_exchange, bars,
                                self.policy_registry.active.parameters,
                                is_mock=history.is_mock,
                            )
                            if technical.status != AgentStatus.SUCCEEDED:
                                return None, "technical history did not produce valid indicators"
                            latest = bars[-1]
                            last_price = float(latest["close"])
                            average_volume = sum(
                                int(row["volume"]) for row in bars[-20:]
                            ) / min(20, len(bars))
                            atr = float(technical.findings["atr_14"])
                            fast = float(technical.findings["ema_fast"])
                            slow = float(technical.findings["ema_slow"])
                            signal = technical.findings.get("signal")
                            trend = signal if signal in {"bullish", "bearish"} else "sideways"
                            return DiscoveryCandidate(
                                symbol=symbol, exchange=self.settings.default_exchange,
                                last_price=last_price,
                                average_daily_turnover=average_volume * last_price,
                                atr_pct=atr / last_price * 100,
                                trend_direction=trend,
                                trend_strength=min(1.0, abs(fast - slow) / atr) if atr > 0 else 0.0,
                                data_as_of=latest["timestamp"], source=history.source,
                                is_mock=history.is_mock,
                            ), None
                        except Exception as exc:
                            return None, f"{type(exc).__name__}: {exc}"

                collected = await asyncio.gather(*(collect_one(symbol) for symbol in selected))
                candidates = [candidate for candidate, error in collected if candidate is not None]
                rejected = {
                    symbol: error
                    for symbol, (candidate, error) in zip(selected, collected)
                    if candidate is None and error is not None
                }
                return universe, candidates, rejected, len(symbols), len(selected)

            try:
                result = asyncio.run(scan_universe())
            except Exception as exc:
                agent = AgentResult(
                    agent_name="Stock Discovery Agent", status=AgentStatus.FAILED,
                    conclusion="Stock universe discovery failed before candidate evaluation.",
                    errors=[f"{type(exc).__name__}: {exc}"],
                )
            else:
                universe, candidates, rejected, universe_count, scanned_count = result
                if (
                    universe.status.value != "ok" or not universe.payload
                    or universe.freshness_seconds > self.settings.max_market_data_freshness_seconds
                ):
                    unavailable = (
                        universe.status.value == "empty"
                        or universe.freshness_seconds > self.settings.max_market_data_freshness_seconds
                    )
                    agent = AgentResult(
                        agent_name="Stock Discovery Agent",
                        status=AgentStatus.SKIPPED if unavailable else AgentStatus.FAILED,
                        conclusion="Stock universe is empty, stale or unavailable; no candidates were inferred.",
                        findings={"feed_status": universe.status.value, "source": universe.source,
                                  "freshness_seconds": universe.freshness_seconds},
                        errors=(universe.warnings if universe.status.value != "empty"
                                else ["Stock universe is empty"]),
                        is_mock=universe.is_mock,
                    )
                else:
                    agent = discover_stocks(candidates, limit=maximum)
                    agent.findings.update({
                        "universe_count": universe_count,
                        "scanned_count": scanned_count,
                        "provider_rejections": rejected,
                        "universe_source": universe.source,
                    })
                    agent.is_mock = universe.is_mock or any(item.is_mock for item in candidates)
            self.agents = [
                item for item in self.agents
                if item.agent_name != "Stock Discovery Agent"
            ]
            self.agents.append(agent)
            self.journal.append({
                "type": "stock_discovery_completed",
                "result": agent.model_dump(mode="json"),
                "at": datetime.now(timezone.utc).isoformat(),
            })
            return agent

    def run_cycle(self, symbol: str = "RELIANCE", exchange: str = "NSE") -> None:
        with self._lock:
            if not self._started:
                raise RuntimeError("Engine is not running")
            now = datetime.now(timezone.utc)
            history = asyncio.run(self.provider.get_historical_prices(
                symbol, now - timedelta(days=80), now, exchange,
            ))
            self.last_data_as_of = history.as_of
            self.last_data_freshness_seconds = history.freshness_seconds
            self.last_data_source = history.source
            self.last_data_is_mock = history.is_mock
            if (
                history.status.value != "ok" or not history.payload
                or history.freshness_seconds > self.settings.max_market_data_freshness_seconds
            ):
                reason = history.error or (
                    f"historical prices status: {history.status.value}; "
                    f"freshness_seconds={history.freshness_seconds}"
                )
                self.agents = [AgentResult(
                    agent_name="Technical Analysis Agent", status=AgentStatus.FAILED,
                    symbol=symbol, exchange=exchange,
                    conclusion="Historical market data is unavailable; entries blocked.",
                    errors=[reason],
                    is_mock=history.is_mock,
                )]
                self.errors.append(f"{symbol}: {reason}")
                self.journal.append({
                    "type": "market_data_rejected", "symbol": symbol,
                    "status": history.status.value, "reason": reason,
                    "source": history.source, "is_mock": history.is_mock,
                    "at": datetime.now(timezone.utc).isoformat(),
                })
                self.last_cycle_at = datetime.now(timezone.utc)
                self._persist()
                return
            bars = [bar.model_dump(mode="python") for bar in history.payload]
            timestamps = [bar["timestamp"] for bar in bars]
            if (
                len(bars) < 35
                or any(bar["symbol"].upper() != symbol.upper() for bar in bars)
                or any(bar["exchange"] != exchange for bar in bars)
                or timestamps != sorted(timestamps)
                or len(set(timestamps)) != len(timestamps)
            ):
                reason = "OHLCV history has insufficient, misidentified, or unordered bars"
                self.agents = [AgentResult(
                    agent_name="Technical Analysis Agent", status=AgentStatus.FAILED,
                    symbol=symbol, exchange=exchange,
                    conclusion="Historical market data failed contract validation.",
                    errors=[reason], is_mock=history.is_mock,
                )]
                self.errors.append(f"{symbol}: {reason}")
                self.journal.append({
                    "type": "market_data_rejected", "symbol": symbol,
                    "status": "invalid", "reason": reason,
                    "source": history.source, "is_mock": history.is_mock,
                    "at": datetime.now(timezone.utc).isoformat(),
                })
                self.last_cycle_at = datetime.now(timezone.utc)
                self._persist()
                return
            latest = bars[-1]
            last_price = float(latest["close"])
            self.marks[symbol] = last_price
            self.ledger.mark(symbol, Decimal(str(last_price)))
            trading_date = datetime.now(ZoneInfo("Asia/Kolkata")).date()
            calendar = asyncio.run(self.provider.get_trading_calendar(trading_date))
            market_open = (
                calendar.status.value == "ok"
                and bool(calendar.payload.get("is_open", False))
            )
            self._roll_daily_pnl()
            self._close_triggered_positions(symbol, latest)

            market_agent = asyncio.run(run_market_intelligence(
                self.provider,
                max_freshness_seconds=self.settings.max_market_data_freshness_seconds,
            ))
            mode = self.settings.strategy_mode
            self.agents = [market_agent, AgentResult(
                agent_name="Technical Analysis Agent", status=AgentStatus.RUNNING,
                symbol=symbol, exchange=exchange, conclusion="Calculating deterministic indicators.",
            )]
            technical_agent, technical_intent = analyze_technical(
                symbol, exchange, bars, self.policy_registry.active.parameters,
                is_mock=history.is_mock,
            )
            fundamental_feed = asyncio.run(self.provider.get_fundamental_snapshot(symbol, exchange))
            if fundamental_feed.status.value == "ok" and fundamental_feed.payload is not None:
                fundamental_agent = analyze_fundamentals(fundamental_feed.payload)
            else:
                fundamental_agent = AgentResult(
                    agent_name="Fundamental Analysis Agent", status=AgentStatus.SKIPPED,
                    symbol=symbol, exchange=exchange,
                    conclusion="Optional fundamental snapshot is unavailable; no values were inferred.",
                    findings={"feed_status": fundamental_feed.status.value,
                              "source": fundamental_feed.source,
                              "warnings": fundamental_feed.warnings},
                    is_mock=fundamental_feed.is_mock,
                )
            institutional_feed = asyncio.run(
                self.provider.get_institutional_activity(symbol, exchange)
            )
            if institutional_feed.status.value == "ok" and institutional_feed.payload is not None:
                institutional_agent = analyze_institutional_activity(institutional_feed.payload)
            else:
                institutional_agent = AgentResult(
                    agent_name="Institutional Activity Agent", status=AgentStatus.SKIPPED,
                    symbol=symbol, exchange=exchange,
                    conclusion="Optional institutional-flow snapshot is unavailable; no values were inferred.",
                    findings={"feed_status": institutional_feed.status.value,
                              "source": institutional_feed.source,
                              "warnings": institutional_feed.warnings},
                    is_mock=institutional_feed.is_mock,
                )
            average_volume = int(
                sum(int(row["volume"]) for row in bars[-20:]) / min(20, len(bars))
            )
            atr_value = float(technical_agent.findings.get("atr_14", 0))
            ema_gap = abs(float(technical_agent.findings.get("ema_9", 0)) -
                          float(technical_agent.findings.get("ema_21", 0)))
            signal_label = technical_agent.findings.get("signal", "unknown")
            trend_direction = signal_label if signal_label in {"bullish", "bearish"} else "sideways"
            discovery_candidate = DiscoveryCandidate(
                symbol=symbol, exchange=exchange, last_price=last_price,
                average_daily_turnover=average_volume * last_price,
                atr_pct=min(100.0, atr_value / last_price * 100.0),
                trend_direction=trend_direction,
                trend_strength=min(1.0, ema_gap / atr_value) if atr_value > 0 else 0.0,
                data_as_of=latest["timestamp"], source=history.source, is_mock=history.is_mock,
            )
            discovery_agent = discover_stocks([discovery_candidate])
            intent = None
            if mode == "technical":
                action_agent, event_blocked = asyncio.run(
                    run_corporate_actions_pipeline(
                        self.provider, symbol,
                        datetime.now(ZoneInfo("Asia/Kolkata")).date(),
                    )
                )
                event_blocked = event_blocked or self._apply_due_corporate_actions(
                    action_agent, symbol, trading_date,
                )
                self.agents = [market_agent, technical_agent, action_agent]
                if event_blocked:
                    self.journal.append({
                        "type": "entry_blocked", "reason": "corporate_action",
                        "symbol": symbol, "at": datetime.now(timezone.utc).isoformat(),
                    })
                intent = None if event_blocked else technical_intent
            elif mode == "news":
                atr = float(technical_agent.findings.get("atr_14", 0))
                self.agents = [technical_agent, AgentResult(
                    agent_name="News Intelligence Agent", status=AgentStatus.RUNNING,
                    symbol=symbol, exchange=exchange, conclusion="Retrieving and scoring source news.",
                )]
                news_agent, news_intent = asyncio.run(
                    run_news_pipeline(self.provider, symbol, last_price, atr, self.llm_provider)
                )
                action_agent, event_blocked = asyncio.run(
                    run_corporate_actions_pipeline(
                        self.provider, symbol,
                        datetime.now(ZoneInfo("Asia/Kolkata")).date(),
                    )
                )
                mapping_agent = self._news_mapping_agent(news_agent, symbol, exchange)
                event_blocked = event_blocked or self._apply_due_corporate_actions(
                    action_agent, symbol, trading_date,
                )
                self.agents = [market_agent, technical_agent, news_agent, mapping_agent, action_agent]
                if event_blocked:
                    self.journal.append({
                        "type": "entry_blocked", "reason": "corporate_action",
                        "symbol": symbol, "at": datetime.now(timezone.utc).isoformat(),
                    })
                intent = None if event_blocked else news_intent
            elif mode == "corporate_actions":
                self.agents = [AgentResult(
                    agent_name="Corporate Actions Agent", status=AgentStatus.RUNNING,
                    symbol=symbol, exchange=exchange, conclusion="Checking verified event records.",
                )]
                action_agent, blocked = asyncio.run(
                    run_corporate_actions_pipeline(
                        self.provider, symbol, datetime.now(ZoneInfo("Asia/Kolkata")).date(),
                    )
                )
                blocked = blocked or self._apply_due_corporate_actions(
                    action_agent, symbol, trading_date,
                )
                self.agents = [market_agent, action_agent]
                if blocked:
                    self.journal.append({
                        "type": "entry_blocked", "reason": "corporate_action",
                        "symbol": symbol, "at": datetime.now(timezone.utc).isoformat(),
                    })
            else:
                atr = float(technical_agent.findings.get("atr_14", 0))
                self.agents = [
                    market_agent,
                    technical_agent,
                    AgentResult(
                        agent_name="News Intelligence Agent", status=AgentStatus.RUNNING,
                        symbol=symbol, exchange=exchange, conclusion="Running in parallel with event checks.",
                    ),
                    AgentResult(
                        agent_name="Corporate Actions Agent", status=AgentStatus.RUNNING,
                        symbol=symbol, exchange=exchange, conclusion="Running in parallel with news analysis.",
                    ),
                ]

                async def execute_independent_strategies():
                    graph = build_strategy_graph()
                    return await graph.ainvoke({
                        "strategies": ["news", "corporate_actions"],
                        "tasks": {
                            "news": lambda: run_news_pipeline(
                                self.provider, symbol, last_price, atr, self.llm_provider,
                            ),
                            "corporate_actions": lambda: run_corporate_actions_pipeline(
                                self.provider, symbol,
                                datetime.now(ZoneInfo("Asia/Kolkata")).date(),
                            ),
                        },
                        "results": [],
                        "timeout_seconds": self.settings.agent_timeout_seconds,
                        "max_retries": self.settings.agent_max_retries,
                    }, config={
                        "max_concurrency": (
                            self.settings.max_parallel_agents
                            if self.settings.enable_parallel_execution else 1
                        ),
                    })

                graph_result = asyncio.run(execute_independent_strategies())
                results_by_name = {
                    item["name"]: item for item in graph_result.get("results", [])
                }
                news_task = results_by_name.get("news", {})
                action_task = results_by_name.get("corporate_actions", {})
                if news_task.get("status") == "succeeded":
                    news_agent, news_intent = news_task["result"]
                else:
                    news_intent = None
                    news_agent = AgentResult(
                        agent_name="News Intelligence Agent", status=AgentStatus.FAILED,
                        symbol=symbol, exchange=exchange,
                        conclusion="News strategy task failed; combined entry blocked.",
                        errors=[news_task.get("error", "No result returned")],
                    )
                if action_task.get("status") == "succeeded":
                    action_agent, action_blocked = action_task["result"]
                else:
                    action_blocked = True
                    action_agent = AgentResult(
                        agent_name="Corporate Actions Agent", status=AgentStatus.FAILED,
                        symbol=symbol, exchange=exchange,
                        conclusion="Corporate-action task failed; combined entry blocked.",
                        errors=[action_task.get("error", "No result returned")],
                    )
                mapping_agent = self._news_mapping_agent(news_agent, symbol, exchange)
                self.agents = [market_agent, technical_agent, news_agent, mapping_agent, action_agent]
                action_blocked = action_blocked or self._apply_due_corporate_actions(
                    action_agent, symbol, trading_date,
                )
                if action_blocked:
                    self.journal.append({
                        "type": "entry_blocked", "reason": "corporate_action",
                        "symbol": symbol, "at": datetime.now(timezone.utc).isoformat(),
                    })
                # Combined mode requires all independent evidence pipelines to succeed.
                if technical_intent is not None and news_intent is not None:
                    reconciliation = reconcile_intents([technical_intent, news_intent])
                    for rejection in reconciliation.rejected:
                        self.journal.append({
                            "type": "intent_rejected",
                            "intent_id": rejection.intent_id,
                            "symbol": rejection.symbol, "reason": rejection.reason,
                        })
                    if (
                        reconciliation.accepted
                        and action_agent.status == AgentStatus.SUCCEEDED
                        and not action_blocked
                    ):
                        intent = reconciliation.accepted[0]
                        intent.strategy = "combined"

            strategy_agent = evaluate_strategy(
                mode=mode, horizon=self.settings.trading_horizon, results=self.agents,
                policy_version=self.policy_registry.active.version,
            )
            self.agents.extend([
                fundamental_agent, institutional_agent, discovery_agent, strategy_agent,
            ])
            critic_required = bool(
                strategy_agent.findings.get("conflict")
                or any(agent.findings.get("unresolved_symbols")
                       or agent.findings.get("rejected_relationships") for agent in self.agents)
            )
            critic_agent = (
                critique_evidence(self.agents)
                if critic_required else AgentResult(
                    agent_name="Debate/Critic Agent", status=AgentStatus.SKIPPED,
                    symbol=symbol, exchange=exchange,
                    conclusion="No configured contradiction or weak-evidence trigger; review not required.",
                )
            )
            self.agents.append(critic_agent)
            risk_decision: RiskDecision | None = None
            synthesis_agent: AgentResult | None = None
            if intent is not None and not strategy_agent.findings.get("candidate_allowed"):
                self.journal.append({
                    "type": "entry_rejected", "reason": "strategy policy did not authorize candidate",
                    "symbol": symbol, "at": datetime.now(timezone.utc).isoformat(),
                })
                intent = None
            if intent is not None and critic_required and (
                critic_agent.status != AgentStatus.SUCCEEDED
                or critic_agent.findings.get("review_passed") is not True
            ):
                self.journal.append({
                    "type": "entry_rejected", "reason": "critic review incomplete or unresolved",
                    "symbol": symbol, "at": datetime.now(timezone.utc).isoformat(),
                })
                intent = None
            if intent is not None:
                intent.policy_version = self.policy_registry.active.version
                intent.id = self._stable_intent_id(intent, latest["timestamp"])
            if intent is not None and not self.paused and not market_open:
                self.journal.append({
                    "type": "entry_rejected", "reason": "market calendar is closed or unavailable",
                    "symbol": symbol, "at": datetime.now(timezone.utc).isoformat(),
                })
            elif intent is not None and not self.paused:
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
                    self.agents.append(AgentResult(
                        agent_name="Risk Management Agent", status=AgentStatus.RUNNING,
                        symbol=symbol, exchange=exchange,
                        conclusion="Applying centralized account and liquidity limits.",
                    ))
                    profile_feed = None
                    profile_error = None
                    try:
                        profile_feed = asyncio.run(self.provider.get_company_profile(symbol))
                    except Exception as exc:
                        profile_error = f"{type(exc).__name__}: {exc}"
                    candidate_sector = (
                        profile_feed.payload.sector
                        if profile_feed is not None and profile_feed.status.value == "ok"
                        and profile_feed.payload is not None
                        and profile_feed.freshness_seconds <= self.settings.max_market_data_freshness_seconds
                        else None
                    )
                    try:
                        current_equity = self.equity
                        current_daily_pnl = self.daily_pnl
                    except ValueError as exc:
                        decision = RiskDecision(
                            accepted=False,
                            reasons=[f"Portfolio valuation unavailable: {exc}"],
                        )
                    else:
                        if not candidate_sector:
                            decision = RiskDecision(
                                accepted=False,
                                reasons=[profile_error or "Verified sector classification is unavailable"],
                            )
                        else:
                            current_symbol_exposure = sum(
                                self.marks[position.symbol] * position.quantity
                                for position in self.positions
                                if position.symbol == intent.symbol and position.symbol in self.marks
                            )
                            current_sector_exposure = sum(
                                self.marks[position.symbol] * position.quantity
                                for position in self.positions
                                if position.sector
                                and position.sector.casefold() == candidate_sector.casefold()
                            )
                            unclassified_exposure = sum(
                                self.marks[position.symbol] * position.quantity
                                for position in self.positions if not position.sector
                            )
                            decision = self.risk.validate(
                                intent, current_equity, current_daily_pnl,
                                len(self.positions), self.cash,
                                equity_peak=self.equity_peak,
                                current_exposure=current_equity - self.cash,
                                current_symbol_exposure=current_symbol_exposure,
                                candidate_sector=candidate_sector,
                                current_sector_exposure=current_sector_exposure,
                                unclassified_exposure=unclassified_exposure,
                                average_volume=average_volume,
                            )
                    self.agents[-1] = AgentResult(
                        agent_name="Risk Management Agent",
                        status=AgentStatus.SUCCEEDED if decision.accepted else AgentStatus.FAILED,
                        symbol=symbol, exchange=exchange,
                        conclusion="Risk checks passed." if decision.accepted else "Risk checks rejected the entry.",
                        findings={
                            "approved_quantity": decision.approved_quantity,
                            "risk_amount": decision.risk_amount,
                            "candidate_sector": candidate_sector,
                            "sector_source": profile_feed.source if profile_feed else None,
                        },
                        errors=decision.reasons,
                    )
                    risk_decision = decision
                    self.journal.append({
                        "type": "risk_decision", "intent": intent.model_dump(mode="json"),
                        "decision": decision.model_dump(mode="json"),
                    })
                    self._processed_intents.add(intent.id)
                    synthesis_agent = synthesize_recommendation(
                        strategy=strategy_agent, risk=risk_decision, intent=intent,
                        critic=critic_agent if critic_required else None,
                    )
                    self.agents.append(synthesis_agent)
                    if decision.accepted and synthesis_agent.status == AgentStatus.SUCCEEDED:
                        signal = Signal(
                            signal_id=intent.id,
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
                            self.ledger.apply_buy(fill)
                            self.ledger.mark(symbol, Decimal(str(last_price)))
                            self.fees_paid += float(fill.fees)
                            self.positions.append(Position(
                                intent_id=intent.id, symbol=intent.symbol, exchange=intent.exchange,
                                direction="long", quantity=fill.quantity, entry_price=float(fill.price),
                                stop_price=intent.stop_price, target_price=intent.target_price,
                                policy_version=intent.policy_version, strategy=intent.strategy,
                                sector=candidate_sector, entry_fees=float(fill.fees),
                                entry_fill_id=fill.fill_id,
                            ))
                            self._persist()
                            self.journal.append({
                                "type": "paper_fill", "fill": fill.model_dump(mode="json"),
                                "intent_id": intent.id,
                            })
                    elif decision.accepted:
                        self.journal.append({
                            "type": "entry_rejected", "reason": "recommendation synthesis rejected candidate",
                            "intent_id": intent.id,
                        })
            if not any(item.agent_name == "Risk Management Agent" for item in self.agents):
                self.agents.append(AgentResult(
                    agent_name="Risk Management Agent", status=AgentStatus.SKIPPED,
                    symbol=symbol, exchange=exchange,
                    conclusion="No candidate reached central risk validation in this cycle.",
                ))
            try:
                current_equity = self.equity
                portfolio_agent = analyze_portfolio(
                    self.positions, self.marks, current_equity, self.cash,
                    max_single_position_exposure_pct=(
                        self.settings.max_single_position_exposure_pct
                    ),
                )
            except ValueError as exc:
                portfolio_agent = AgentResult(
                    agent_name="Portfolio Intelligence Agent", status=AgentStatus.FAILED,
                    conclusion="Portfolio exposure is unavailable because one or more marks are missing.",
                    errors=[str(exc)],
                )
            self.agents = [
                agent for agent in self.agents
                if agent.agent_name != "Portfolio Intelligence Agent"
            ]
            self.agents.append(portfolio_agent)
            if synthesis_agent is None:
                synthesis_agent = synthesize_recommendation(
                    strategy=strategy_agent, risk=risk_decision, intent=intent,
                    critic=critic_agent if critic_required else None,
                )
                self.agents.append(synthesis_agent)
            self.last_cycle_at = datetime.now(timezone.utc)
            try:
                self.equity_peak = max(self.equity_peak, self.equity)
            except ValueError:
                # Missing marks must not be converted into zero equity or a new peak.
                pass
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
            self.next_cycle_at = None
            self.state = "stopped"

    def promote_paper_policy(
        self, candidate: PaperPolicy, evaluation: CandidateEvaluation,
    ) -> PaperPolicy:
        """Promote a candidate only after explicit offline evaluation gates pass."""
        with self._lock:
            if not self._started:
                raise RuntimeError("Engine must be running to change the paper policy")
            if candidate.version in self.policy_registry.versions:
                raise ValueError("policy versions must be unique")
            promoted = self.policy_registry.promote(candidate, evaluation)
            self._persist()
            self.journal.append({
                "type": "paper_policy_promoted",
                "version": promoted.version,
                "parent_version": promoted.parent_version,
                "evaluation": evaluation.model_dump(mode="json"),
                "at": datetime.now(timezone.utc).isoformat(),
            })
            return promoted

    def rollback_paper_policy(self) -> PaperPolicy:
        """Restore the previous paper policy; hard risk settings are not part of policies."""
        with self._lock:
            if not self._started:
                raise RuntimeError("Engine must be running to roll back the paper policy")
            previous = self.policy_registry.rollback()
            self._persist()
            self.journal.append({
                "type": "paper_policy_rolled_back",
                "active_version": previous.version,
                "at": datetime.now(timezone.utc).isoformat(),
            })
            return previous

    def learning_report(self):
        return evaluate_outcomes(
            self.outcomes, policy_version=self.policy_registry.active.version,
        )

    def snapshot(self) -> dict:
        try:
            equity_value = self.equity
            daily_pnl_value = self.daily_pnl
        except ValueError:
            # Missing marks remain unavailable; never render them as zero.
            equity_value = None
            daily_pnl_value = None
        strategy_totals: dict[str, dict[str, float | int]] = {}
        for outcome in self.outcomes:
            strategy_name = outcome.strategy or "unknown"
            totals = strategy_totals.setdefault(
                strategy_name, {"trades": 0, "net_pnl": 0.0, "fees": 0.0, "wins": 0},
            )
            totals["trades"] = int(totals["trades"]) + 1
            totals["net_pnl"] = float(totals["net_pnl"]) + float(outcome.net_pnl)
            totals["fees"] = float(totals["fees"]) + float(outcome.fees)
            totals["wins"] = int(totals["wins"]) + int(outcome.net_pnl > 0)
        attributed_net = sum(float(row["net_pnl"]) for row in strategy_totals.values())
        account_outcome_net = sum(float(item.net_pnl) for item in self.outcomes)
        open_trades = []
        for position in self.positions:
            mark = self.marks.get(position.symbol)
            unrealized = (
                (mark - position.entry_price) * position.quantity
                if mark is not None and position.direction == "long" else None
            )
            open_trades.append({
                **position.model_dump(mode="json"),
                "mark_price": mark,
                "mark_as_of": self.last_data_as_of.isoformat() if mark is not None and self.last_data_as_of else None,
                "unrealized_pnl": unrealized,
                "mark_status": "available" if mark is not None else "missing",
            })
        return {
            "state": self.state, "mode": self.settings.strategy_mode,
            "is_mock": self.last_data_is_mock, "data_source": self.last_data_source,
            "data_as_of": self.last_data_as_of,
            "data_freshness_seconds": self.last_data_freshness_seconds,
            "cash": self.cash, "equity": equity_value,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl, "daily_pnl": daily_pnl_value,
            "outcome_count": len(self.outcomes),
            "active_policy": self.policy_registry.active.model_dump(mode="json"),
            "fees_paid": self.fees_paid,
            "positions": self.positions, "open_trades": open_trades,
            "outcomes": self.outcomes,
            "strategy_performance": [
                {"strategy": name, **values}
                for name, values in sorted(strategy_totals.items())
            ],
            "strategy_attribution_net_pnl": attributed_net,
            "strategy_attribution_reconciles": abs(attributed_net - account_outcome_net) < 0.000001,
            "agents": self.agents, "errors": self.errors,
            "last_cycle_at": self.last_cycle_at, "next_cycle_at": self.next_cycle_at,
            "paused": self.paused,
            "scheduler_active": self._scheduler_thread is not None and self._scheduler_thread.is_alive(),
        }
