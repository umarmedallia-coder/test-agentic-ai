from collections.abc import Mapping
from datetime import datetime, timezone
import math

import pandas as pd

from app.models import AgentResult, AgentStatus, Evidence, TradeIntent


def analyze_technical(
    symbol: str, exchange: str, bars: list[dict],
    policy: Mapping[str, float] | None = None, *, is_mock: bool = True,
) -> tuple[AgentResult, TradeIntent | None]:
    """Deterministic indicators and versioned entry parameters; no LLM creates prices."""
    parameters = policy or {}
    fast_period = int(parameters.get("ema_fast", 9))
    slow_period = int(parameters.get("ema_slow", 21))
    rsi_lower = float(parameters.get("rsi_lower", 50))
    rsi_upper = float(parameters.get("rsi_upper", 75))
    atr_stop_multiple = float(parameters.get("atr_stop_multiple", 2))
    reward_risk = float(parameters.get("reward_risk", 1.5))
    if not 2 <= fast_period < slow_period <= 200:
        raise ValueError("EMA policy requires 2 <= fast < slow <= 200")
    if not 0 < rsi_lower < rsi_upper < 100:
        raise ValueError("RSI policy requires 0 < lower < upper < 100")
    if not 0.5 <= atr_stop_multiple <= 5 or not 1 <= reward_risk <= 5:
        raise ValueError("ATR stop and reward/risk policy are outside safe bounds")
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
    ema_fast = close.ewm(span=fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=slow_period, adjust=False).mean()
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
    ema_fast_value = float(ema_fast.iloc[-1])
    ema_slow_value = float(ema_slow.iloc[-1])
    macd_value = float(macd.iloc[-1])
    macd_signal_value = float(macd_signal.iloc[-1])
    if not all(math.isfinite(value) for value in (last, atr, ema_fast_value, ema_slow_value, macd_value, macd_signal_value, rsi_value)) or atr <= 0:
        return AgentResult(
            agent_name="Technical Analysis Agent", status=AgentStatus.FAILED,
            symbol=symbol, exchange=exchange, conclusion="Indicator calculation unavailable",
            errors=["Indicator series contains unavailable values"],
        ), None

    bullish = (
        ema_fast_value > ema_slow_value and last > ema_fast_value
        and macd_value > macd_signal_value and rsi_lower <= rsi_value <= rsi_upper
    )
    bearish = (
        ema_fast_value < ema_slow_value and last < ema_fast_value
        and macd_value < macd_signal_value
        and 100 - rsi_upper <= rsi_value <= 100 - rsi_lower
    )
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
            "ema_9": ema_fast_value, "ema_21": ema_slow_value,
            "ema_fast": ema_fast_value, "ema_slow": ema_slow_value,
            "ema_fast_period": fast_period, "ema_slow_period": slow_period,
            "atr_14": atr, "rsi_14": rsi_value,
            "rsi_lower": rsi_lower, "rsi_upper": rsi_upper,
            "atr_stop_multiple": atr_stop_multiple, "reward_risk": reward_risk,
            "macd": macd_value, "macd_signal": macd_signal_value,
            "last_close": last, "average_volume_20": float(numeric["volume"].tail(20).mean()),
            "signal": signal,
        },
        evidence=[Evidence(
            source="OHLCV", observed_at=observed_at,
            statement=f"EMA {fast_period}/{slow_period}, ATR 14, RSI 14 and MACD 12/26/9 calculated",
            provenance="provider-supplied OHLCV",
            limitations=["Deterministic indicator rules are not a return forecast"]
                + (["Synthetic mock OHLCV"] if is_mock else []),
        )],
        is_mock=is_mock,
    )
    if not bullish:
        return result, None
    stop_distance = atr_stop_multiple * atr
    if last <= stop_distance:
        result.findings["signal"] = "neutral"
        result.findings["rejection_reason"] = "ATR stop distance would produce a non-positive stop price"
        return result, None
    return result, TradeIntent(
        symbol=symbol, exchange=exchange, entry_price=last,
        stop_price=last - stop_distance,
        target_price=last + stop_distance * reward_risk, quantity=1,
        confidence=0.5, source_agent="Technical Analysis Agent",
    )
