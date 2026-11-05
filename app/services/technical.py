from datetime import datetime, timezone

import pandas as pd

from app.models import AgentResult, AgentStatus, Evidence, TradeIntent


def analyze_technical(symbol: str, exchange: str, bars: list[dict]) -> tuple[AgentResult, TradeIntent | None]:
    frame = pd.DataFrame(bars)
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns) or len(frame) < 26:
        return AgentResult(agent_name="Technical Analysis Agent", status=AgentStatus.FAILED,
                           symbol=symbol, exchange=exchange,
                           conclusion="Insufficient OHLCV history",
                           errors=["At least 26 valid bars are required"]), None
    if frame[list(required)].isnull().any().any() or (frame["close"] <= 0).any():
        return AgentResult(agent_name="Technical Analysis Agent", status=AgentStatus.FAILED,
                           symbol=symbol, exchange=exchange, conclusion="Invalid OHLCV values",
                           errors=["Missing or non-positive market values"]), None
    close = frame["close"].astype(float)
    ema9 = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
    ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
    atr = float((frame["high"] - frame["low"]).rolling(14).mean().iloc[-1])
    last = float(close.iloc[-1])
    signal = "bullish" if ema9 > ema21 and last > ema9 else "bearish" if ema9 < ema21 and last < ema9 else "neutral"
    result = AgentResult(agent_name="Technical Analysis Agent", status=AgentStatus.SUCCEEDED,
                         symbol=symbol, exchange=exchange,
                         conclusion=f"{signal} EMA trend assessment",
                         findings={"ema_9": ema9, "ema_21": ema21, "atr_14_proxy": atr,
                                   "last_close": last, "signal": signal},
                         evidence=[Evidence(source="OHLCV", observed_at=datetime.now(timezone.utc),
                                            statement="EMA 9/21 and 14-bar range calculated",
                                            provenance="deterministic adapter",
                                            limitations=["Not a return forecast"])])
    if signal != "bullish" or atr <= 0:
        return result, None
    return result, TradeIntent(symbol=symbol, exchange=exchange, entry_price=last,
                               stop_price=last - 2*atr, target_price=last + 3*atr, quantity=1)
