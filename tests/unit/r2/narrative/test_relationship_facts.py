from __future__ import annotations

import pytest
from r2.narrative.relationship_facts import RELATIONSHIP_FACT_KEY_VERSION, relationship_fact_predicate

from r2.narrative.errors import NarrativeRelationshipIntegrityError

# Regression anchor: the exact wire string for the shared mapping. Anything that moves it
# invalidates every persisted relationship Fact key and must be a deliberate v2 mapping.
_HERO_TRUST_GOLDEN = "r2rel:20ca2e58dc593e529822b294b398285d42a00fb92a5b10fa63eb157c96b1fa3b"


def test_mapping_version_constant_is_v1() -> None:
    assert RELATIONSHIP_FACT_KEY_VERSION == "r2-relationship-fact-key-v1"


def test_predicate_is_direction_target_and_key_sensitive() -> None:
    ab = relationship_fact_predicate("b", "trust_level")
    ba = relationship_fact_predicate("a", "trust_level")
    ak = relationship_fact_predicate("b", "rivalry")
    assert len({ab, ba, ak}) == 3
    assert ab == relationship_fact_predicate("b", "trust_level")  # deterministic


def test_predicate_prefix_and_golden_vector() -> None:
    value = relationship_fact_predicate("hero", "trust_level")
    assert value.startswith("r2rel:")
    assert value == _HERO_TRUST_GOLDEN


def test_unknown_mapping_version_fails_closed() -> None:
    with pytest.raises(NarrativeRelationshipIntegrityError):
        relationship_fact_predicate("b", "trust_level", mapping_version="r2-relationship-fact-key-v2")
