from app.config import Settings
from app.models import RiskDecision, TradeIntent


class RiskManager:
    """Single deterministic gate for every strategy's paper trade intent."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate(
        self,
        intent: TradeIntent,
        equity: float,
        daily_pnl: float,
        open_positions: int,
        available_cash: float,
        *,
        equity_peak: float | None = None,
        current_exposure: float = 0.0,
        average_volume: int | None = None,
        max_participation_pct: float = 0.01,
        lot_size: int = 1,
    ) -> RiskDecision:
        reasons: list[str] = []
        if equity <= 0:
            reasons.append("Account equity is not positive")
            return RiskDecision(accepted=False, reasons=reasons)
        if open_positions >= self.settings.max_open_positions:
            reasons.append("Maximum open positions reached")
        if daily_pnl <= -(equity * self.settings.max_daily_loss_pct):
            reasons.append("Maximum daily loss reached")
        if equity_peak is not None and equity_peak > 0:
            drawdown = max(0.0, (equity_peak - equity) / equity_peak)
            if drawdown >= self.settings.max_drawdown_pct:
                reasons.append("Maximum account drawdown reached")
        if current_exposure >= equity:
            reasons.append("Portfolio gross exposure is already at or above equity")
        if lot_size < 1:
            reasons.append("Lot size must be positive")
        unit_risk = abs(intent.entry_price - intent.stop_price)
        budget = equity * self.settings.max_risk_per_trade_pct
        quantity = min(intent.quantity, int(budget // unit_risk)) if unit_risk > 0 else 0
        if lot_size > 1:
            quantity = (quantity // lot_size) * lot_size
        if quantity < 1:
            reasons.append("Cannot size one lot within per-trade risk limit")
        notional = intent.entry_price * quantity
        if notional > available_cash:
            reasons.append("Insufficient available cash")
        if current_exposure + notional > equity:
            reasons.append("Portfolio gross exposure limit would be exceeded")
        if average_volume is not None:
            if average_volume <= 0:
                reasons.append("Average traded volume is unavailable")
            elif quantity > average_volume * max_participation_pct:
                reasons.append("Order exceeds configured market-volume participation limit")
        if not 0 < max_participation_pct <= 1:
            reasons.append("Invalid market-volume participation limit")
        if reasons:
            return RiskDecision(accepted=False, reasons=reasons)
        return RiskDecision(accepted=True, approved_quantity=quantity,
                            risk_amount=quantity * unit_risk)
