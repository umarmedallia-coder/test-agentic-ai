from datetime import UTC, datetime, timedelta

from app.contracts import RelationshipEdge
from app.services.relationship_mapper import expand_related_symbols


def test_relationship_expansion_requires_current_evidenced_high_confidence_edges():
    now = datetime.now(UTC)
    edges = [
        RelationshipEdge(
            source_symbol="BEL", target_symbol="BEML", relationship_type="supplier",
            evidence_ids=["e1"], source="exchange filing",
            valid_from=now - timedelta(days=5), confidence=0.9,
        ),
        RelationshipEdge(
            source_symbol="BEL", target_symbol="OLDCO", relationship_type="former_parent",
            evidence_ids=["e2"], source="old filing",
            valid_from=now - timedelta(days=20), valid_until=now - timedelta(days=1),
            confidence=0.99,
        ),
        RelationshipEdge(
            source_symbol="BEL", target_symbol="LOWCONF", relationship_type="peer",
            evidence_ids=["e3"], source="weak source",
            valid_from=now - timedelta(days=2), confidence=0.4,
        ),
        RelationshipEdge(
            source_symbol="BEML", target_symbol="TRANSITIVE", relationship_type="supplier",
            evidence_ids=["e4"], source="other filing",
            valid_from=now - timedelta(days=2), confidence=0.99,
        ),
    ]
    result = expand_related_symbols("bel", edges, now)
    assert [item.related_symbol for item in result] == ["BEML"]
    assert result[0].evidence_ids == ("e1",)
