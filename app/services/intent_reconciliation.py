"""Deterministic reconciliation of overlapping agent trade intents."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models import TradeIntent


class IntentRejection(BaseModel):
    intent_id: str
    symbol: str
    reason: str


class IntentReconciliation(BaseModel):
    accepted: list[TradeIntent] = Field(default_factory=list)
    rejected: list[IntentRejection] = Field(default_factory=list)


def reconcile_intents(intents: list[TradeIntent]) -> IntentReconciliation:
    """Reject directional conflicts; merge same-direction evidence and keep one intent per symbol."""
    result = IntentReconciliation()
    unique: list[TradeIntent] = []
    seen_ids: set[str] = set()
    for intent in intents:
        if intent.id in seen_ids:
            result.rejected.append(IntentRejection(
                intent_id=intent.id, symbol=intent.symbol,
                reason="duplicate intent id",
            ))
            continue
        seen_ids.add(intent.id)
        unique.append(intent)

    groups: dict[tuple[str, str], list[TradeIntent]] = {}
    for intent in unique:
        key = (intent.exchange.upper(), intent.symbol.upper())
        groups.setdefault(key, []).append(intent)

    for (_, _), candidates in sorted(groups.items()):
        directions = {candidate.direction for candidate in candidates}
        if len(directions) > 1:
            for candidate in candidates:
                result.rejected.append(IntentRejection(
                    intent_id=candidate.id, symbol=candidate.symbol,
                    reason="conflicting long and short agent intents",
                ))
            continue
        winner = max(
            candidates,
            key=lambda candidate: (
                candidate.confidence, candidate.created_at, candidate.id,
            ),
        )
        evidence_ids = sorted({
            evidence_id
            for candidate in candidates
            for evidence_id in candidate.evidence_ids
        })
        merged = winner.model_copy(update={
            "evidence_ids": evidence_ids,
            "source_agent": (
                ",".join(sorted({
                    candidate.source_agent for candidate in candidates
                    if candidate.source_agent
                })) or winner.source_agent
            ),
        })
        result.accepted.append(merged)
        for candidate in candidates:
            if candidate.id != winner.id:
                result.rejected.append(IntentRejection(
                    intent_id=candidate.id, symbol=candidate.symbol,
                    reason=f"superseded by higher-confidence intent {winner.id}",
                ))
    return result
