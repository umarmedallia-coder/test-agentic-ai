from datetime import datetime, timezone
import math

import pandas as pd

from app.models import AgentResult, AgentStatus, Evidence, TradeIntent


def analyze_technical(
    symbol: str, exchange: str, bars: list[dict]
) -> tuple[AgentResult, TradeIntent | None]:
    """Deterministic indicator analysis. No language model generates prices or indicators."""
    frame = pd.DataFrame(bars)
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns) or len(frame) < 35:
        return AgentResult(
            agent_name="Technical Analysis Agent", status=AgentStatus.FAILED,
            symbol=symbol, exchange=exchange, conclusion="Insufficient OHLCV history",
            errors=["At least 35 valid bars are required for the indicator set"],
        ), None
    numeric = frame[["open", "high", "low", "close", "volume"]].astype(float)
    if numeric.isnull().any().any() or not numeric.map(math.isfinite).all().all():
        return AgentResult(
            agent_name="Technical Analysis Agent", status=AgentStatus.FAILED,
            symbol=symbol, exchange=exchange, conclusion="Invalid OHLCV values",
            errors=["Missing or non-finite market values"],
        ), None
    if (numeric[["open", "high", "low", "close"]] <= 0).any().any() or (numeric["volume"] < 0).any():
        return AgentResult(
            agent_name="Technical Analysis Agent", status=AgentStatus.FAILED,
            symbol=symbol, exchange=exchange, conclusion="Invalid OHLCV values",
            errors=["Prices must be positive and volume cannot be negative"],
        ), None
    if (numeric["high"] < numeric[["open", "low", "close"]].max(axis=1)).any():
        return AgentResult(
            agent_name="Technical Analysis Agent", status=AgentStatus.FAILED,
            symbol=symbol, exchange=exchange, conclusion="Invalid OHLCV range",
            errors=["High must be the maximum OHLC value"],
        ), None
    if (numeric["low"] > numeric[["open", "high", "close"]].min(axis=1)).any():
        return AgentResult(
            agent_name="Technical Analysis Agent", status=AgentStatus.FAILED,
            symbol=symbol, exchange=exchange, conclusion="Invalid OHLCV range",
            errors=["Low must be the minimum OHLC value"],
        ), None

    close = numeric["close"]
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()

    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            numeric["high"] - numeric["low"],
            (numeric["high"] - previous_close).abs(),
            (numeric["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr14 = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    relative_strength = gain / loss.replace(0, float("nan"))
    rsi14 = 100 - (100 / (1 + relative_strength))
    if loss.iloc[-1] == 0:
        rsi_value = 100.0 if gain.iloc[-1] > 0 else 50.0
    else:
        rsi_value = float(rsi14.iloc[-1])

    last = float(close.iloc[-1])
    atr = float(atr14.iloc[-1])
    ema9_value = float(ema9.iloc[-1])
    ema21_value = float(ema21.iloc[-1])
    macd_value = float(macd.iloc[-1])
    macd_signal_value = float(macd_signal.iloc[-1])
    if not all(math.isfinite(value) for value in (last, atr, ema9_value, ema21_value, macd_value, macd_signal_value, rsi_value)) or atr <= 0:
        return AgentResult(
            agent_name="Technical Analysis Agent", status=AgentStatus.FAILED,
            symbol=symbol, exchange=exchange, conclusion="Indicator calculation unavailable",
            errors=["Indicator series contains unavailable values"],
        ), None

    bullish = ema9_value > ema21_value and last > ema9_value and macd_value > macd_signal_value and 50 <= rsi_value <= 75
    bearish = ema9_value < ema21_value and last < ema9_value and macd_value < macd_signal_value and 25 <= rsi_value <= 50
    signal = "bullish" if bullish else "bearish" if bearish else "neutral"
    observed_at = frame["timestamp"].iloc[-1] if "timestamp" in frame.columns else datetime.now(timezone.utc)
    if isinstance(observed_at, str):
        observed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        return AgentResult(
            agent_name="Technical Analysis Agent", status=AgentStatus.FAILED,
            symbol=symbol, exchange=exchange, conclusion="Naive source timestamp rejected",
            errors=["OHLCV timestamp must be timezone-aware"],
        ), None

    result = AgentResult(
        agent_name="Technical Analysis Agent", status=AgentStatus.SUCCEEDED,
        symbol=symbol, exchange=exchange, conclusion=f"{signal} multi-indicator assessment",
        findings={
            "ema_9": ema9_value, "ema_21": ema21_value, "atr_14": atr,
            "rsi_14": rsi_value, "macd": macd_value, "macd_signal": macd_signal_value,
            "last_close": last, "average_volume_20": float(numeric["volume"].tail(20).mean()),
            "signal": signal,
        },
        evidence=[Evidence(
            source="OHLCV", observed_at=observed_at,
            statement="EMA 9/21, ATR 14, RSI 14 and MACD 12/26/9 calculated",
            provenance="deterministic mock adapter",
            limitations=["Not a return forecast", "Mock data is synthetic"],
        )],
    )
    if not bullish:
        return result, None
    return result, TradeIntent(
        symbol=symbol, exchange=exchange, entry_price=last,
        stop_price=last - 2 * atr, target_price=last + 3 * atr, quantity=1,
    )
