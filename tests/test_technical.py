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


def test_technical_analysis_uses_versioned_parameters_and_provider_provenance():
    result, _ = analyze_technical(
        "ABC", "NSE", make_bars(),
        {"ema_fast": 5, "ema_slow": 30, "rsi_lower": 45,
         "rsi_upper": 70, "atr_stop_multiple": 1.5, "reward_risk": 2.0},
        is_mock=False,
    )
    assert result.findings["ema_fast_period"] == 5
    assert result.findings["ema_slow_period"] == 30
    assert result.findings["atr_stop_multiple"] == 1.5
    assert result.findings["reward_risk"] == 2.0
    assert result.is_mock is False
    assert "Synthetic mock OHLCV" not in result.evidence[0].limitations


def test_technical_analysis_rejects_unsafe_policy_parameters():
    import pytest

    with pytest.raises(ValueError, match="EMA policy"):
        analyze_technical("ABC", "NSE", make_bars(), {"ema_fast": 21, "ema_slow": 9})


def test_bearish_technical_signal_creates_a_valid_short_intent():
    bars = make_bars()
    for index, bar in enumerate(bars):
        close = 200 - index * 0.25 + 1.5 * __import__("math").sin(index * 0.7 + 3.0)
        bar.update({"open": close - 0.05, "high": close + 0.8,
                    "low": close - 0.8, "close": close})
    result, intent = analyze_technical("ABC", "NSE", bars)
    assert result.findings["signal"] == "bearish"
    assert intent is not None
    assert intent.direction == "short"
    assert intent.target_price < intent.entry_price < intent.stop_price
