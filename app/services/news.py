"""News normalization, duplicate suppression and conservative impact heuristics."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Iterable, Literal

from pydantic import BaseModel, Field

from app.contracts import Evidence, RelationshipEdge


class NewsItem(BaseModel):
    headline: str
    body: str = ""
    source: str
    published_at: datetime
    url: str | None = None
    symbols: list[str] = Field(default_factory=list)


class NewsImpact(BaseModel):
    fingerprint: str
    headline: str
    symbols: list[str]
    sentiment: float = Field(ge=-1, le=1)
    impact_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    rationale: str
    evidence: Evidence


_POSITIVE = ("order win", "contract win", "profit rises", "upgrade", "approval", "buyback", "dividend")
_NEGATIVE = ("fraud", "probe", "default", "downgrade", "loss widens", "resigns", "penalty", "recall")


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def fingerprint(item: NewsItem) -> str:
    return hashlib.sha256(normalize_text(item.headline).encode("utf-8")).hexdigest()


def deduplicate_news(items: Iterable[NewsItem]) -> list[NewsItem]:
    unique: dict[str, NewsItem] = {}
    for item in items:
        key = fingerprint(item)
        if key not in unique or item.published_at > unique[key].published_at:
            unique[key] = item
    return list(unique.values())


def map_news_to_symbols(item: NewsItem, aliases: dict[str, str]) -> list[str]:
    text = normalize_text(f"{item.headline} {item.body}")
    resolved = {symbol.upper() for symbol in item.symbols}
    for alias, symbol in aliases.items():
        normalized = normalize_text(alias)
        if normalized and re.search(rf"\b{re.escape(normalized)}\b", text):
            resolved.add(symbol.upper())
    return sorted(resolved)


def score_news(item: NewsItem) -> NewsImpact:
    text = normalize_text(f"{item.headline} {item.body}")
    positive = sum(phrase in text for phrase in _POSITIVE)
    negative = sum(phrase in text for phrase in _NEGATIVE)
    matches = positive + negative
    sentiment = (positive - negative) / matches if matches else 0.0
    # Impact estimates event materiality; sentiment measures directional language.
    magnitude = min(1.0, matches * 0.25)
    impact_score = magnitude * 100
    confidence = min(0.85, 0.35 + matches * 0.12) if matches else 0.25
    evidence = Evidence(
        kind="news", source=item.source, observed_at=datetime.now(timezone.utc),
        published_at=item.published_at, headline=item.headline, confidence=confidence,
        url=item.url, facts={
            "positive_matches": positive, "negative_matches": negative,
            "sentiment": sentiment, "impact_score": impact_score,
        },
    )
    return NewsImpact(
        fingerprint=fingerprint(item), headline=item.headline,
        symbols=sorted({symbol.upper() for symbol in item.symbols}),
        sentiment=sentiment, impact_score=impact_score, confidence=confidence,
        rationale="Deterministic heuristic only; not sufficient by itself to authorize a trade.",
        evidence=evidence,
    )


def build_news_signal(
    impact: NewsImpact,
    reference_price: float,
    atr: float,
    *,
    min_impact_score: float = 65.0,
    min_confidence: float = 0.65,
):
    """Build price levels only from a supplied validated quote/ATR, never from news text."""
    from decimal import Decimal

    from app.contracts import Signal

    if not impact.symbols or impact.impact_score < min_impact_score:
        return None
    if impact.confidence < min_confidence or reference_price <= 0 or atr <= 0:
        return None
    if impact.sentiment == 0:
        return None
    entry = Decimal(str(reference_price))
    volatility = Decimal(str(atr))
    if impact.sentiment > 0:
        direction = "long"
        stop = entry - Decimal("1.5") * volatility
        target = entry + Decimal("2.5") * volatility
    else:
        direction = "short"
        stop = entry + Decimal("1.5") * volatility
        target = entry - Decimal("2.5") * volatility
    if stop <= 0 or target <= 0:
        return None
    return Signal(
        strategy="news_impact", symbol=impact.symbols[0], direction=direction,
        entry=entry, stop=stop, target=target, confidence=impact.confidence,
        rationale="News impact heuristic gated by independently supplied quote and ATR.",
        evidence_ids=[impact.evidence.evidence_id],
    )


class AffectedSecurity(BaseModel):
    symbol: str
    direction: Literal["positive", "negative", "mixed", "neutral", "uncertain"]
    impact_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    horizon: str
    relationship_type: str
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str


class NewsImpactResult(BaseModel):
    news_fingerprint: str
    unresolved_entities: list[str] = Field(default_factory=list)
    affected_securities: list[AffectedSecurity]
    evaluated_relationships: int
    rejected_relationships: int


def map_news_impact(
    impact: NewsImpact,
    relationships: list[RelationshipEdge],
    *,
    as_of: datetime,
    minimum_relationship_confidence: float = 0.7,
) -> NewsImpactResult:
    """Map only explicitly evidenced relationships with an explicit transmission rule."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if not 0 <= minimum_relationship_confidence <= 1:
        raise ValueError("minimum relationship confidence must be between 0 and 1")

    direct_direction: Literal["positive", "negative", "mixed", "neutral", "uncertain"]
    if impact.sentiment > 0:
        direct_direction = "positive"
    elif impact.sentiment < 0:
        direct_direction = "negative"
    else:
        direct_direction = "neutral"

    securities: dict[str, AffectedSecurity] = {}
    for symbol in impact.symbols:
        securities[symbol] = AffectedSecurity(
            symbol=symbol, direction=direct_direction, impact_score=impact.impact_score,
            confidence=impact.confidence, horizon="event-dependent",
            relationship_type="direct", evidence_ids=[impact.evidence.evidence_id],
            rationale="Direct symbol mapping from the source news record.",
        )

    evaluated = 0
    rejected = 0
    for edge in relationships:
        if edge.source_symbol.upper() not in impact.symbols:
            continue
        if edge.valid_from > as_of or (edge.valid_until is not None and edge.valid_until < as_of):
            rejected += 1
            continue
        if edge.confidence < minimum_relationship_confidence:
            rejected += 1
            continue
        evaluated += 1
        direction: Literal["positive", "negative", "mixed", "neutral", "uncertain"]
        if edge.transmission == "same":
            direction = direct_direction
        elif edge.transmission == "inverse":
            direction = (
                "negative" if direct_direction == "positive"
                else "positive" if direct_direction == "negative"
                else "uncertain"
            )
        elif edge.transmission == "mixed":
            direction = "mixed"
        else:
            direction = "uncertain"
        candidate = AffectedSecurity(
            symbol=edge.target_symbol.upper(), direction=direction,
            impact_score=impact.impact_score * edge.confidence,
            confidence=min(impact.confidence, edge.confidence),
            horizon="relationship-dependent",
            relationship_type=edge.relationship_type,
            evidence_ids=sorted(set(edge.evidence_ids + [impact.evidence.evidence_id])),
            rationale=(
                f"Indirect exposure via {edge.relationship_type}; "
                f"transmission={edge.transmission}. Direction remains uncertain "
                "unless the relationship explicitly defines same/inverse transmission."
            ),
        )
        existing = securities.get(candidate.symbol)
        if existing is None:
            securities[candidate.symbol] = candidate
        else:
            directions = {existing.direction, candidate.direction}
            if len(directions) > 1:
                existing.direction = "mixed"
            existing.impact_score = max(existing.impact_score, candidate.impact_score)
            existing.confidence = min(existing.confidence, candidate.confidence)
            existing.evidence_ids = sorted(set(existing.evidence_ids + candidate.evidence_ids))
            if candidate.relationship_type not in existing.relationship_type:
                existing.relationship_type += f";{candidate.relationship_type}"

    return NewsImpactResult(
        news_fingerprint=impact.fingerprint,
        unresolved_entities=[],
        affected_securities=list(securities.values()),
        evaluated_relationships=evaluated,
        rejected_relationships=rejected,
    )


class NewsInterpretation(BaseModel):
    """Unverified LLM interpretation kept separate from source facts and deterministic scores."""
    event_category: str
    extracted_source_facts: list[str] = Field(default_factory=list)
    interpretation: str
    mentioned_entities: list[str] = Field(default_factory=list)
    horizon: str
    risk_flags: list[str] = Field(default_factory=list)
