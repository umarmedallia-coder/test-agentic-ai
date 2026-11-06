"""Deterministic reconciliation of overlapping and related portfolio intents."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.contracts import RelationshipEdge
from app.models import Position, TradeIntent


class IntentRejection(BaseModel):
    intent_id: str
    symbol: str
    reason: str


class IntentReconciliation(BaseModel):
    accepted: list[TradeIntent] = Field(default_factory=list)
    rejected: list[IntentRejection] = Field(default_factory=list)


def reconcile_intents(intents: list[TradeIntent]) -> IntentReconciliation:
    """Reject same-symbol directional conflicts; merge same-direction evidence."""
    result = IntentReconciliation()
    unique: list[TradeIntent] = []
    seen_ids: set[str] = set()
    for intent in intents:
        if intent.id in seen_ids:
            result.rejected.append(IntentRejection(
                intent_id=intent.id, symbol=intent.symbol, reason="duplicate intent id",
            ))
            continue
        seen_ids.add(intent.id)
        unique.append(intent)

    groups: dict[tuple[str, str], list[TradeIntent]] = {}
    for intent in unique:
        groups.setdefault((intent.exchange.upper(), intent.symbol.upper()), []).append(intent)

    for candidates in groups.values():
        if len({item.direction for item in candidates}) > 1:
            for candidate in candidates:
                result.rejected.append(IntentRejection(
                    intent_id=candidate.id, symbol=candidate.symbol,
                    reason="conflicting long and short agent intents",
                ))
            continue
        winner = max(
            candidates,
            key=lambda item: (item.confidence, item.created_at, item.id),
        )
        evidence_ids = sorted({
            evidence for candidate in candidates for evidence in candidate.evidence_ids
        })
        merged = winner.model_copy(update={
            "evidence_ids": evidence_ids,
            "source_agent": ",".join(sorted({
                candidate.source_agent for candidate in candidates if candidate.source_agent
            })) or winner.source_agent,
        })
        result.accepted.append(merged)
        for candidate in candidates:
            if candidate.id != winner.id:
                result.rejected.append(IntentRejection(
                    intent_id=candidate.id, symbol=candidate.symbol,
                    reason=f"superseded by higher-confidence intent {winner.id}",
                ))
    return result


def reconcile_portfolio_intents(
    intents: list[TradeIntent],
    relationship_edges: list[RelationshipEdge],
    as_of: datetime,
    *,
    open_positions: list[Position] | None = None,
    min_confidence: float = 0.7,
) -> IntentReconciliation:
    """Apply evidence-backed cross-symbol consistency checks before portfolio entry.

    Same-transmission relationships require matching trade directions; inverse
    relationships require opposite directions. Mixed, unknown, weak, or
    contradictory current evidence fails closed. Expired edges are ignored.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be between zero and one")

    result = reconcile_intents(intents)
    if not result.accepted:
        return result

    positions = open_positions or []
    blocked: dict[str, str] = {}

    def assess(first_symbol: str, first_direction: str, second_symbol: str,
               second_direction: str) -> str | None:
        if first_symbol.upper() == second_symbol.upper():
            return None
        relevant = [
            edge for edge in relationship_edges
            if {edge.source_symbol.upper(), edge.target_symbol.upper()}
            == {first_symbol.upper(), second_symbol.upper()}
            and edge.valid_from <= as_of
            and (edge.valid_until is None or edge.valid_until >= as_of)
        ]
        if not relevant:
            return None
        # A relationship assertion without traceable supporting evidence is
        # not admissible for portfolio-level directional decisions.
        if any(
            not edge.evidence_ids
            or any(not evidence_id.strip() for evidence_id in edge.evidence_ids)
            for edge in relevant
        ):
            return "related-entity exposure blocked: relationship evidence is missing"
        signatures = {
            (edge.transmission, edge.relationship_type, edge.source)
            for edge in relevant
        }
        if len(signatures) != 1:
            return "conflicting current relationship evidence"
        edge = relevant[0]
        if edge.confidence < min_confidence:
            return "related-entity exposure blocked: relationship confidence below threshold"
        if edge.transmission not in {"same", "inverse"}:
            return f"related-entity exposure blocked: {edge.transmission} transmission is unresolved"

        expected_same_direction = edge.transmission == "same"
        if (first_direction == second_direction) != expected_same_direction:
            return (
                f"cross-symbol directional conflict: {first_symbol.upper()} and "
                f"{second_symbol.upper()} have {edge.transmission} transmission"
            )
        return None

    accepted = result.accepted
    for index, candidate in enumerate(accepted):
        for other in accepted[index + 1:]:
            if candidate.exchange.upper() != other.exchange.upper():
                continue
            reason = assess(
                candidate.symbol, candidate.direction, other.symbol, other.direction,
            )
            if reason:
                blocked[candidate.id] = reason
                blocked[other.id] = reason
        for position in positions:
            if position.exchange.upper() != candidate.exchange.upper():
                continue
            reason = assess(
                candidate.symbol, candidate.direction, position.symbol, position.direction,
            )
            if reason:
                blocked[candidate.id] = (
                    f"existing holding {position.symbol.upper()}: {reason}"
                )

    if blocked:
        result.accepted = [
            candidate for candidate in accepted if candidate.id not in blocked
        ]
        for candidate in accepted:
            if candidate.id in blocked:
                result.rejected.append(IntentRejection(
                    intent_id=candidate.id, symbol=candidate.symbol,
                    reason=blocked[candidate.id],
                ))
    return result
