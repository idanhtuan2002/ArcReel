"""The sole versioned mapping from a directional relationship to an M5A Fact key.

Every relationship-aware surface (the F9 validator, the change-set effect-key
normalizer, and the CanonDelta compiler) resolves a relationship predicate only through
``relationship_fact_predicate``. No extractor, compiler, provider, orchestrator, or
caller concatenates or otherwise invents a relationship predicate.

The Fact collision key for a directional relationship is
``(subject_ref=source_character_ref, predicate=relationship_fact_predicate(target, key))``
and the Fact value is the relationship state string.
"""

from __future__ import annotations

import hashlib

from r2.contracts import canonical_json_bytes, ensure_json_value

from .errors import NarrativeRelationshipIntegrityError

RELATIONSHIP_FACT_KEY_VERSION = "r2-relationship-fact-key-v1"


def relationship_fact_predicate(
    target_character_ref: str,
    relationship_key: str,
    *,
    mapping_version: str = RELATIONSHIP_FACT_KEY_VERSION,
) -> str:
    """Return the ``r2rel:`` Fact predicate for ``(target_character_ref, relationship_key)``.

    Directional: the source character is the Fact subject, not part of the predicate.
    Raises ``NarrativeRelationshipIntegrityError`` for any unknown ``mapping_version``.
    """
    if mapping_version != RELATIONSHIP_FACT_KEY_VERSION:
        raise NarrativeRelationshipIntegrityError(f"unknown relationship-key mapping {mapping_version!r}")
    payload = {
        "schema": RELATIONSHIP_FACT_KEY_VERSION,
        "target_character_ref": target_character_ref,
        "relationship_key": relationship_key,
    }
    return "r2rel:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(payload))).hexdigest()
