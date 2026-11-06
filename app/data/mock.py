from datetime import datetime, timedelta, timezone

import pandas as pd

from app.models import DataEnvelope


class MockMarketData:
    """Deterministic mock OHLCV source; never represents live prices."""

    def historical_prices(self, symbol: str, exchange: str = "NSE", bars: int = 80) -> DataEnvelope:
        if not symbol.strip() or exchange not in {"NSE", "BSE"} or bars < 1:
            raise ValueError("valid symbol, exchange and bar count are required")
        now = datetime.now(timezone.utc)
        rows = []
        for i in range(bars):
            close = 100.0 + i * .22 + ((i % 7) - 3) * .31
            rows.append({"timestamp": now - timedelta(minutes=bars-i), "open": close-.15,
                         "high": close+.55, "low": close-.55, "close": close,
                         "volume": 100_000 + (i % 9) * 8_000})
        frame = pd.DataFrame(rows)
        return DataEnvelope(payload={"symbol": symbol.upper(), "exchange": exchange,
                                     "bars": frame.to_dict("records"),
                                     "adjustment": "unadjusted_mock"},
                            source="deterministic_mock", is_mock=True,
                            observed_at=now, freshness_seconds=0)

    def quote(self, symbol: str, exchange: str = "NSE") -> DataEnvelope:
        bars = self.historical_prices(symbol, exchange, 2).payload["bars"]
        return DataEnvelope(payload={"symbol": symbol.upper(), "exchange": exchange,
                                     "price": float(bars[-1]["close"]), "volume": bars[-1]["volume"]},
                            source="deterministic_mock", is_mock=True,
                            observed_at=datetime.now(timezone.utc), freshness_seconds=0)
