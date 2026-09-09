from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import (
    CANON_SCHEMA_V1,
    CANON_SCHEMA_V2,
    CanonContent,
    Entity,
    EntityType,
    Event,
    Fact,
)
from r2.narrative.errors import NarrativeSchemaVersionError
from r2.narrative.hashing import compute_canon_content_hash
from r2.narrative.schema_upgrade import require_schema_transition, upgrade_canon_content

# Frozen v1 content bytes and the content hash produced by the accepted M5A implementation,
# captured from that implementation before schema-v2 serialization existed.
V1_CONTENT_JSON: dict[str, object] = {
    "entities_by_id": {
        "char-ada": {
            "aliases": ["Ada", "Countess"],
            "canonical_name": "Ada",
            "entity_id": "char-ada",
            "entity_type": "CHARACTER",
        },
        "loc-hall": {
            "aliases": [],
            "canonical_name": "Great Hall",
            "entity_id": "loc-hall",
            "entity_type": "LOCATION",
        },
        "obj-ring": {
            "aliases": [],
            "canonical_name": "Signet Ring",
            "entity_id": "obj-ring",
            "entity_type": "OBJECT",
        },
    },
    "events_by_id": {
        "ev-gift": {
            "causal_refs": [],
            "event_id": "ev-gift",
            "event_type": "GIFT",
            "location_ref": "loc-hall",
            "participant_refs": ["char-ada"],
            "state_effect_refs": [],
            "temporal_anchor": "2026-03-01T09:00:00Z",
        }
    },
    "facts_by_id": {
        "fact-owner": {
            "effective_from": "2026-03-01T09:00:00Z",
            "effective_until": None,
            "fact_id": "fact-owner",
            "predicate": "owner",
            "source_event_refs": ["ev-gift"],
            "subject_ref": "obj-ring",
            "value": "char-ada",
        }
    },
}
M5A_V1_GOLDEN_HASH = "56ebc632b669dae6db6c643a56fe1992def05f00af5e1dc5195b81f8d45a0484"

T = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)


def v1_content() -> CanonContent:
    return CanonContent(
        entities_by_id={
            "char-ada": Entity(
                entity_id="char-ada",
                entity_type=EntityType.CHARACTER,
                canonical_name="Ada",
                aliases=["Ada", "Countess"],
            ),
            "loc-hall": Entity(
                entity_id="loc-hall", entity_type=EntityType.LOCATION, canonical_name="Great Hall", aliases=[]
            ),
            "obj-ring": Entity(
                entity_id="obj-ring", entity_type=EntityType.OBJECT, canonical_name="Signet Ring", aliases=[]
            ),
        },
        facts_by_id={
            "fact-owner": Fact(
                fact_id="fact-owner",
                subject_ref="obj-ring",
                predicate="owner",
                value="char-ada",
                effective_from=T,
                effective_until=None,
                source_event_refs=["ev-gift"],
            )
        },
        events_by_id={
            "ev-gift": Event(
                event_id="ev-gift",
                event_type="GIFT",
                participant_refs=["char-ada"],
                location_ref="loc-hall",
                temporal_anchor=T,
            )
        },
    )


def test_v1_content_hash_ignores_the_v2_default_maps() -> None:
    parsed = CanonContent.model_validate(V1_CONTENT_JSON)
    assert parsed.knowledge_states_by_id == {}
    assert compute_canon_content_hash(parsed, schema_version=CANON_SCHEMA_V1) == M5A_V1_GOLDEN_HASH
    assert compute_canon_content_hash(v1_content(), schema_version=CANON_SCHEMA_V1) == M5A_V1_GOLDEN_HASH


def test_v2_content_hash_includes_the_v2_maps_and_differs_from_v1() -> None:
    content = v1_content()
    v1_digest = compute_canon_content_hash(content, schema_version=CANON_SCHEMA_V1)
    v2_digest = compute_canon_content_hash(content, schema_version=CANON_SCHEMA_V2)
    assert v1_digest != v2_digest


def test_upgrade_is_pure_and_keeps_v1_atoms() -> None:
    upgraded = upgrade_canon_content(v1_content(), from_schema=CANON_SCHEMA_V1, to_schema=CANON_SCHEMA_V2)
    assert upgraded.entities_by_id == v1_content().entities_by_id
    assert upgraded.facts_by_id == v1_content().facts_by_id
    assert upgraded.events_by_id == v1_content().events_by_id
    assert upgraded.knowledge_states_by_id == {}
    assert upgraded.epistemic_propositions_by_ref == {}
    assert upgraded.temporal_relations_by_id == {}


def test_genesis_and_same_version_transitions_are_legal() -> None:
    legal_transitions = [
        (None, CANON_SCHEMA_V1),
        (None, CANON_SCHEMA_V2),
        (CANON_SCHEMA_V1, CANON_SCHEMA_V1),
        (CANON_SCHEMA_V1, CANON_SCHEMA_V2),
        (CANON_SCHEMA_V2, CANON_SCHEMA_V2),
    ]
    for from_schema, to_schema in legal_transitions:
        assert require_schema_transition(from_schema=from_schema, to_schema=to_schema) is None


def test_downgrade_v2_to_v1_is_rejected() -> None:
    with pytest.raises(NarrativeSchemaVersionError):
        require_schema_transition(from_schema=CANON_SCHEMA_V2, to_schema=CANON_SCHEMA_V1)
    with pytest.raises(NarrativeSchemaVersionError):
        upgrade_canon_content(v1_content(), from_schema=CANON_SCHEMA_V2, to_schema=CANON_SCHEMA_V1)


def test_unknown_schema_selectors_are_rejected() -> None:
    with pytest.raises(NarrativeSchemaVersionError):
        require_schema_transition(from_schema=CANON_SCHEMA_V1, to_schema="r2-canon-schema-v9")
    with pytest.raises(NarrativeSchemaVersionError):
        require_schema_transition(from_schema="r2-canon-schema-v0", to_schema=CANON_SCHEMA_V1)
