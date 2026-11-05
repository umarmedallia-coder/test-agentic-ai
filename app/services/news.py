"""News normalization, duplicate suppression and conservative impact heuristics."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Iterable

from pydantic import BaseModel, Field

from app.contracts import Evidence


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
    impact: float = Field(ge=-1, le=1)
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
    impact = max(-1.0, min(1.0, (positive-negative)*0.35))
    matches = positive+negative
    confidence = min(0.85,0.35+matches*0.12) if matches else 0.25
    evidence = Evidence(kind="news",source=item.source,observed_at=datetime.now(timezone.utc),
        published_at=item.published_at,headline=item.headline,confidence=confidence,url=item.url,
        facts={"positive_matches":positive,"negative_matches":negative})
    return NewsImpact(fingerprint=fingerprint(item),headline=item.headline,
        symbols=sorted({s.upper() for s in item.symbols}),impact=impact,confidence=confidence,
        rationale="Keyword heuristic only; not sufficient by itself to authorize a trade.",evidence=evidence)
