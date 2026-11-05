from app.config import Settings
from app.models import RiskDecision, TradeIntent


class RiskManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate(self, intent: TradeIntent, equity: float, daily_pnl: float,
                 open_positions: int, available_cash: float) -> RiskDecision:
        reasons: list[str] = []
        if equity <= 0:
            reasons.append("Account equity is not positive")
        if open_positions >= self.settings.max_open_positions:
            reasons.append("Maximum open positions reached")
        if daily_pnl <= -(equity * self.settings.max_daily_loss_pct):
            reasons.append("Maximum daily loss reached")
        unit_risk = abs(intent.entry_price - intent.stop_price)
        budget = equity * self.settings.max_risk_per_trade_pct
        quantity = min(intent.quantity, int(budget // unit_risk)) if unit_risk > 0 else 0
        if quantity < 1:
            reasons.append("Cannot size one unit within per-trade risk limit")
        if intent.entry_price * quantity > available_cash:
            reasons.append("Insufficient available cash")
        if reasons:
            return RiskDecision(accepted=False, reasons=reasons)
        return RiskDecision(accepted=True, approved_quantity=quantity,
                            risk_amount=quantity * unit_risk)
