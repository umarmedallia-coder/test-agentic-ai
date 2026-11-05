from datetime import datetime, timezone
from threading import RLock

from app.config import Settings
from app.data.mock import MockMarketData
from app.models import AgentResult, Position
from app.services.journal import JsonlJournal
from app.services.risk import RiskManager
from app.services.technical import analyze_technical


class TradingEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.data = MockMarketData()
        self.journal = JsonlJournal(settings.journal_dir)
        self.risk = RiskManager(settings)
        self._lock = RLock()
        self._started = False
        self.state = "idle"
        self.paused = False
        self.cash = settings.initial_capital_inr
        self.positions: list[Position] = []
        self.agents: list[AgentResult] = []
        self.errors: list[str] = []
        self.last_cycle_at: datetime | None = None

    @property
    def equity(self) -> float:
        return self.cash + sum(p.entry_price*p.quantity for p in self.positions)

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self.journal.acquire()
            try:
                self.journal.read_all()
                self.journal.append({"type": "engine_started", "mode": self.settings.strategy_mode,
                                     "at": datetime.now(timezone.utc).isoformat()})
                self._started = True
                self.state = "running"
            except Exception:
                self.journal.release()
                raise

    def pause_new_entries(self) -> None:
        if self.state == "running":
            self.paused = True

    def resume(self) -> None:
        if self.state == "running":
            self.paused = False

    def run_cycle(self, symbol: str = "RELIANCE", exchange: str = "NSE") -> None:
        with self._lock:
            if not self._started:
                raise RuntimeError("Engine is not running")
            envelope = self.data.historical_prices(symbol, exchange)
            agent, intent = analyze_technical(symbol, exchange, envelope.payload["bars"])
            self.agents = [agent]
            if intent is not None and not self.paused:
                decision = self.risk.validate(intent, self.equity, 0, len(self.positions), self.cash)
                self.journal.append({"type": "risk_decision", "intent": intent.model_dump(mode="json"),
                                     "decision": decision.model_dump(mode="json")})
                if decision.accepted:
                    quantity = decision.approved_quantity
                    self.positions.append(Position(intent_id=intent.id, symbol=intent.symbol,
                        exchange=intent.exchange, direction=intent.direction, quantity=quantity,
                        entry_price=intent.entry_price, stop_price=intent.stop_price,
                        target_price=intent.target_price, policy_version=intent.policy_version))
                    self.cash -= intent.entry_price * quantity
            self.last_cycle_at = datetime.now(timezone.utc)

    def stop(self) -> None:
        with self._lock:
            if self._started:
                self.journal.append({"type": "engine_stopped", "open_positions": len(self.positions)})
                self.journal.release()
            self._started = False
            self.state = "stopped"

    def snapshot(self) -> dict:
        return {"state": self.state, "mode": self.settings.strategy_mode, "is_mock": True,
                "cash": self.cash, "equity": self.equity, "positions": self.positions,
                "agents": self.agents, "errors": self.errors, "last_cycle_at": self.last_cycle_at}
