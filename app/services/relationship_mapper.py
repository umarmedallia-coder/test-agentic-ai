"""Evidence-backed one-hop company relationship expansion for news mapping."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import RelationshipEdge


class RelatedSymbolMapping(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_symbol: str
    related_symbol: str
    relationship_type: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: tuple[str, ...]
    source: str


def expand_related_symbols(
    primary_symbol: str,
    edges: list[RelationshipEdge],
    as_of: datetime,
    *,
    min_confidence: float = 0.7,
) -> list[RelatedSymbolMapping]:
    """Return only current, evidenced, direct edges; never infer transitive relationships."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be between zero and one")
    primary = primary_symbol.upper()
    best: dict[str, RelatedSymbolMapping] = {}
    for edge in edges:
        if edge.source_symbol.upper() != primary:
            continue
        if edge.target_symbol.upper() == primary or edge.confidence < min_confidence:
            continue
        if edge.valid_from > as_of or (edge.valid_until is not None and edge.valid_until < as_of):
            continue
        mapping = RelatedSymbolMapping(
            source_symbol=primary,
            related_symbol=edge.target_symbol.upper(),
            relationship_type=edge.relationship_type,
            confidence=edge.confidence,
            evidence_ids=tuple(edge.evidence_ids),
            source=edge.source,
        )
        current = best.get(mapping.related_symbol)
        if current is None or mapping.confidence > current.confidence:
            best[mapping.related_symbol] = mapping
    return sorted(best.values(), key=lambda item: (-item.confidence, item.related_symbol))
