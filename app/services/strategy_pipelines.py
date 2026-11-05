"""Independent news and corporate-action strategy pipelines with fail-closed outputs."""
from __future__ import annotations

from datetime import date

from app.contracts import CorporateActionRecord
from app.data.contracts import MarketDataProvider
from app.models import AgentResult, AgentStatus, Evidence, TradeIntent
from app.services.corporate_actions import ActionType, CorporateAction, blocks_new_entry
from app.services.news import (
    NewsItem,
    build_news_signal,
    deduplicate_news,
    map_news_to_symbols,
    score_news,
)


async def run_news_pipeline(
    provider: MarketDataProvider,
    symbol: str,
    reference_price: float,
    atr: float,
) -> tuple[AgentResult, TradeIntent | None]:
    feed = await provider.get_stock_news(symbol)
    if feed.status.value == "empty" or not feed.payload:
        return AgentResult(
            agent_name="News Intelligence Agent", status=AgentStatus.SKIPPED,
            symbol=symbol, conclusion="No source news records available; no news trade signal.",
            findings={"feed_status": feed.status.value},
        ), None
    if feed.status.value != "ok":
        return AgentResult(
            agent_name="News Intelligence Agent", status=AgentStatus.FAILED,
            symbol=symbol, conclusion="News feed is not usable; entries blocked.",
            errors=[feed.error or feed.status.value],
        ), None

    try:
        profile = await provider.get_company_profile(symbol)
    except Exception as exc:
        return AgentResult(
            agent_name="News Intelligence Agent", status=AgentStatus.FAILED,
            symbol=symbol, conclusion="Company identity could not be verified.",
            errors=[f"{type(exc).__name__}: {exc}"],
        ), None
    aliases = {profile.payload.company_name: symbol}
    items = [
        NewsItem(
            headline=record.headline, body=record.body, source=record.source,
            published_at=record.published_at, url=record.url,
            symbols=map_news_to_symbols(
                NewsItem(
                    headline=record.headline, body=record.body, source=record.source,
                    published_at=record.published_at, url=record.url, symbols=record.symbols,
                ),
                aliases,
            ),
        )
        for record in feed.payload
    ]
    impacts = [score_news(item) for item in deduplicate_news(items)]
    relevant = [impact for impact in impacts if symbol.upper() in impact.symbols]
    if not relevant:
        return AgentResult(
            agent_name="News Intelligence Agent", status=AgentStatus.SKIPPED,
            symbol=symbol, conclusion="No news item could be mapped to this company.",
            findings={"deduplicated_items": len(impacts)},
        ), None
    relevant.sort(key=lambda item: (abs(item.impact) * item.confidence), reverse=True)
    selected = relevant[0]
    signal = build_news_signal(selected, reference_price, atr)
    result = AgentResult(
        agent_name="News Intelligence Agent", status=AgentStatus.SUCCEEDED,
        symbol=symbol, conclusion="News impact evaluated using explicit company mapping.",
        findings={
            "impact": selected.impact, "confidence": selected.confidence,
            "headline": selected.headline, "deduplicated_items": len(impacts),
        },
        evidence=[Evidence(
            source=selected.evidence.source, observed_at=selected.evidence.observed_at,
            statement=selected.headline, provenance=selected.evidence.url or selected.evidence.source,
            limitations=["Keyword impact heuristic; review required"],
        )],
    )
    if signal is None:
        return result, None
    intent = TradeIntent(
        symbol=signal.symbol, exchange=signal.exchange, direction=signal.direction,
        entry_price=float(signal.entry), stop_price=float(signal.stop),
        target_price=float(signal.target), quantity=1, strategy="news_impact",
    )
    return result, intent


async def run_corporate_actions_pipeline(
    provider: MarketDataProvider,
    symbol: str,
    trading_day: date,
) -> tuple[AgentResult, bool]:
    feed = await provider.get_corporate_actions(symbol)
    if feed.status.value == "empty" or not feed.payload:
        return AgentResult(
            agent_name="Corporate Actions Agent", status=AgentStatus.SKIPPED,
            symbol=symbol, conclusion="No corporate-action records returned by the source.",
            findings={"feed_status": feed.status.value},
        ), False
    if feed.status.value != "ok":
        return AgentResult(
            agent_name="Corporate Actions Agent", status=AgentStatus.FAILED,
            symbol=symbol, conclusion="Corporate-action feed unavailable; entries blocked.",
            errors=[feed.error or feed.status.value],
        ), True

    blocked = False
    event_summaries = []
    for record in feed.payload:
        try:
            action = _to_action(record)
        except Exception as exc:
            return AgentResult(
                agent_name="Corporate Actions Agent", status=AgentStatus.FAILED,
                symbol=symbol, conclusion="An invalid corporate-action record blocks new entries.",
                errors=[f"{type(exc).__name__}: {exc}"],
            ), True
        action_blocked = not action.verified or blocks_new_entry(action, trading_day)
        blocked = blocked or action_blocked
        event_summaries.append({
            "action_type": action.action_type.value,
            "ex_date": action.ex_date.isoformat() if action.ex_date else None,
            "verified": action.verified, "blocks_entry": action_blocked,
        })
    return AgentResult(
        agent_name="Corporate Actions Agent", status=AgentStatus.SUCCEEDED,
        symbol=symbol, conclusion="Corporate-action event restrictions evaluated.",
        findings={"blocked": blocked, "events": event_summaries},
    ), blocked


def _to_action(record: CorporateActionRecord) -> CorporateAction:
    try:
        action_type = ActionType(record.action_type.lower())
    except ValueError:
        action_type = ActionType.OTHER
    return CorporateAction(
        symbol=record.symbol, action_type=action_type,
        announcement_date=record.announcement_date.date(),
        ex_date=record.ex_date.date() if record.ex_date else None,
        record_date=record.record_date.date() if record.record_date else None,
        source=record.source, verified=record.verified,
        ratio_from=record.ratio_from, ratio_to=record.ratio_to,
        cash_amount=record.cash_amount,
    )
