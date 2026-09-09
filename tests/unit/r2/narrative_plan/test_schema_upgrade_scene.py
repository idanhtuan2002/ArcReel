from __future__ import annotations

import pytest

from r2.narrative.errors import NarrativePlanSchemaVersionError
from r2.narrative_plan.schema_upgrade import (
    minimum_scene_selector,
    require_plan_schema_transition,
    require_scene_schema_transition,
)
from tests.unit.r2.narrative_plan._helpers import relationship_constraint, scene_contract_v2

_S1 = "r2-scene-contract-content-v1"
_S2 = "r2-scene-contract-content-v2"
_P1 = "r2-narrative-plan-v1"
_P2 = "r2-narrative-plan-v2"


def test_genesis_to_v1_scene_is_legal_only_without_v2_semantics() -> None:
    require_scene_schema_transition(from_selector=None, to_selector=_S1, content_minimum=_S1)
    with pytest.raises(NarrativePlanSchemaVersionError):
        require_scene_schema_transition(from_selector=None, to_selector=_S1, content_minimum=_S2)


def test_genesis_and_v1_to_v2_scene_transitions_are_legal() -> None:
    assert require_scene_schema_transition(from_selector=None, to_selector=_S2, content_minimum=_S2) is None
    assert require_scene_schema_transition(from_selector=_S1, to_selector=_S2, content_minimum=_S2) is None
    assert require_scene_schema_transition(from_selector=_S1, to_selector=_S1, content_minimum=_S1) is None


def test_scene_with_relationship_semantic_cannot_stay_on_the_v1_selector() -> None:
    assert minimum_scene_selector(scene_contract_v2(entry_state_constraints=[relationship_constraint()])) == _S2
    with pytest.raises(NarrativePlanSchemaVersionError):
        require_scene_schema_transition(from_selector=_S1, to_selector=_S1, content_minimum=_S2)


def test_v2_scene_lineage_cannot_downgrade_even_when_v2_lists_empty() -> None:
    with pytest.raises(NarrativePlanSchemaVersionError):
        require_scene_schema_transition(from_selector=_S2, to_selector=_S1, content_minimum=_S1)
    # v2 -> v2 stays legal after the v2-only lists later become empty.
    require_scene_schema_transition(from_selector=_S2, to_selector=_S2, content_minimum=_S1)


def test_unknown_scene_selector_fails_closed() -> None:
    with pytest.raises(NarrativePlanSchemaVersionError):
        require_scene_schema_transition(
            from_selector=_S1, to_selector="r2-scene-contract-content-v3", content_minimum=_S1
        )
    with pytest.raises(NarrativePlanSchemaVersionError):
        require_scene_schema_transition(from_selector="bogus", to_selector=_S2, content_minimum=_S2)


def test_plan_ratchet_mirrors_the_scene_ratchet() -> None:
    assert require_plan_schema_transition(from_selector=None, to_selector=_P1, contains_v2_scene=False) is None
    assert require_plan_schema_transition(from_selector=None, to_selector=_P2, contains_v2_scene=True) is None
    assert require_plan_schema_transition(from_selector=_P1, to_selector=_P2, contains_v2_scene=True) is None
    assert require_plan_schema_transition(from_selector=_P2, to_selector=_P2, contains_v2_scene=False) is None


def test_plan_with_a_v2_scene_member_must_be_the_v2_plan_selector() -> None:
    with pytest.raises(NarrativePlanSchemaVersionError):
        require_plan_schema_transition(from_selector=_P1, to_selector=_P1, contains_v2_scene=True)


def test_v2_plan_lineage_cannot_downgrade_to_v1() -> None:
    with pytest.raises(NarrativePlanSchemaVersionError):
        require_plan_schema_transition(from_selector=_P2, to_selector=_P1, contains_v2_scene=False)


def test_unknown_plan_selector_fails_closed() -> None:
    with pytest.raises(NarrativePlanSchemaVersionError):
        require_plan_schema_transition(from_selector=_P1, to_selector="r2-narrative-plan-v3", contains_v2_scene=False)
