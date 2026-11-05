from datetime import UTC, datetime, timedelta

from app.models import AgentStatus
from app.services.technical import analyze_technical


def make_bars(count=60):
    bars = []
    start = datetime.now(UTC) - timedelta(minutes=count)
    for index in range(count):
        close = 100 + index * 0.2
        bars.append({
            "timestamp": start + timedelta(minutes=index),
            "open": close - 0.05,
            "high": close + 0.8,
            "low": close - 0.8,
            "close": close,
            "volume": 100_000 + index * 1_000,
        })
    return bars


def test_technical_analysis_calculates_all_deterministic_indicators():
    result, intent = analyze_technical("ABC", "NSE", make_bars())
    assert result.status == AgentStatus.SUCCEEDED
    assert {"ema_9", "ema_21", "atr_14", "rsi_14", "macd", "macd_signal"} <= set(result.findings)
    assert result.findings["atr_14"] > 0
    assert 0 <= result.findings["rsi_14"] <= 100
    # The generated trend is intentionally overbought; it must not force an entry.
    assert intent is None


def test_technical_analysis_rejects_bad_price_range():
    bars = make_bars()
    bars[-1]["high"] = bars[-1]["low"] - 1
    result, intent = analyze_technical("ABC", "NSE", bars)
    assert result.status == AgentStatus.FAILED
    assert intent is None


def test_technical_analysis_rejects_naive_market_timestamp():
    bars = make_bars()
    bars[-1]["timestamp"] = datetime.now()
    result, intent = analyze_technical("ABC", "NSE", bars)
    assert result.status == AgentStatus.FAILED
    assert intent is None
