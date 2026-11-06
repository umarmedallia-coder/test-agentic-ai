from app.models import Position
from app.services.portfolio_intelligence import analyze_portfolio


def test_portfolio_intelligence_reports_long_short_gross_and_net_exposure():
    positions = [
        Position(
            intent_id="long-1", symbol="LONGCO", exchange="NSE", direction="long",
            quantity=10, entry_price=100, stop_price=95, target_price=110,
            policy_version="v1",
        ),
        Position(
            intent_id="short-1", symbol="SHORTCO", exchange="NSE", direction="short",
            quantity=5, entry_price=80, stop_price=90, target_price=70,
            policy_version="v1",
        ),
    ]

    result = analyze_portfolio(
        positions, {"LONGCO": 110, "SHORTCO": 70}, 10_000, 9_000,
        max_single_position_exposure_pct=0.25,
    )

    assert result.status.value == "succeeded"
    assert result.findings["long_exposure"] == 1100
    assert result.findings["short_exposure"] == 350
    assert result.findings["gross_exposure"] == 1450
    assert result.findings["net_exposure"] == 750
