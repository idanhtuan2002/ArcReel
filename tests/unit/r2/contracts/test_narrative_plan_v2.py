from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from r2.contracts.narrative_plan import (
    PLAN_CONTENT_HASH_VERSION_V2,
    PLAN_SCHEMA_VERSION_V2,
    SCENE_CONTRACT_CONTENT_HASH_VERSION_V2,
    CanonBasis,
    NarrativePlan,
    NarrativePlanContent,
    NarrativePlanContentV2,
    NarrativePlanContentValue,
    NarrativePlanVersionSnapshot,
    SceneContract,
    SceneContractV2,
    SceneContractValue,
    SceneRelationshipConstraint,
    SceneTemporalWindow,
    SceneThreadConstraint,
)
from r2.narrative.errors import NarrativePlanSchemaVersionError

FROM = datetime(2026, 3, 1, 10, tzinfo=UTC)
UNTIL = datetime(2026, 3, 1, 12, tzinfo=UTC)
BASIS = CanonBasis(branch_id="br-1", canon_version_id="cv-1")


def _window() -> SceneTemporalWindow:
    return SceneTemporalWindow(effective_from=FROM, effective_until=UNTIL)


def v1_scene(**overrides: object) -> SceneContract:
    kwargs: dict[str, object] = {
        "scene_contract_id": "sc-v1",
        "version": 1,
        "semantic_hash": "sh:placeholder-v1",
        "sequence_index": 0,
        "purpose": "p",
        "pov": None,
        "location_ref": None,
        "temporal_window": _window(),
    }
    kwargs.update(overrides)
    return SceneContract(**kwargs)


def v2_scene(**overrides: object) -> SceneContractV2:
    kwargs: dict[str, object] = {
        "scene_contract_id": "sc-v2",
        "version": 1,
        "semantic_hash": "sh:placeholder-v2",
        "semantic_hash_version": "r2-scene-contract-content-v2",
        "sequence_index": 1,
        "purpose": "p",
        "pov": None,
        "location_ref": None,
        "temporal_window": _window(),
    }
    kwargs.update(overrides)
    return SceneContractV2(**kwargs)


def _relationship(**overrides: object) -> SceneRelationshipConstraint:
    kwargs: dict[str, object] = {
        "constraint_id": "r1",
        "source_character_ref": "hero",
        "target_character_ref": "mentor",
        "relationship_key": "trust_level",
        "comparison": "PRESENT",
    }
    kwargs.update(overrides)
    return SceneRelationshipConstraint(**kwargs)


def v2_scene_with_relationship() -> SceneContractV2:
    return v2_scene(entry_state_constraints=[_relationship()])


def test_v2_selectors_are_fixed_strings() -> None:
    assert SCENE_CONTRACT_CONTENT_HASH_VERSION_V2 == "r2-scene-contract-content-v2"
    assert PLAN_SCHEMA_VERSION_V2 == "r2-narrative-plan-v2"
    assert PLAN_CONTENT_HASH_VERSION_V2 == "r2-narrative-plan-content-v2"


def test_relationship_constraint_requires_expected_state_only_for_equality() -> None:
    with pytest.raises(ValidationError):
        SceneRelationshipConstraint(
            constraint_id="c1",
            source_character_ref="a",
            target_character_ref="b",
            relationship_key="trust_level",
            comparison="PRESENT",
            expected_state="TRUSTED",
        )
    with pytest.raises(ValidationError):
        SceneRelationshipConstraint(
            constraint_id="c1",
            source_character_ref="a",
            target_character_ref="b",
            relationship_key="trust_level",
            comparison="EQUALS",
        )
    ok = SceneRelationshipConstraint(
        constraint_id="c1",
        source_character_ref="a",
        target_character_ref="b",
        relationship_key="trust_level",
        comparison="EQUALS",
        expected_state="TRUSTED",
    )
    assert ok.comparison == "EQUALS"
    assert ok.constraint_kind == "RELATIONSHIP"


def test_relationship_constraint_rejects_self_reference_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SceneRelationshipConstraint(
            constraint_id="c1",
            source_character_ref="a",
            target_character_ref="a",
            relationship_key="trust_level",
            comparison="PRESENT",
        )
    with pytest.raises(ValidationError):
        SceneRelationshipConstraint.model_validate(
            {
                "constraint_id": "c1",
                "source_character_ref": "a",
                "target_character_ref": "b",
                "relationship_key": "trust_level",
                "comparison": "PRESENT",
                "provider": "openai",
            }
        )


def test_thread_constraint_payoff_ref_presence_is_state_dependent() -> None:
    with pytest.raises(ValidationError):
        SceneThreadConstraint(constraint_id="c2", thread_ref="t1", required_state="OPEN", payoff_ref="p1")
    with pytest.raises(ValidationError):
        SceneThreadConstraint(constraint_id="c3", thread_ref="t1", required_state="RESOLVED")
    opened = SceneThreadConstraint(constraint_id="c2", thread_ref="t1", required_state="OPEN")
    resolved = SceneThreadConstraint(constraint_id="c3", thread_ref="t1", required_state="RESOLVED", payoff_ref="p1")
    assert opened.payoff_ref is None
    assert resolved.payoff_ref == "p1"
    assert opened.constraint_kind == "THREAD"


def test_thread_constraint_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SceneThreadConstraint.model_validate(
            {"constraint_id": "c2", "thread_ref": "t1", "required_state": "OPEN", "runtime_task_id": "x"}
        )


def test_v1_scene_contract_still_rejects_relationship_and_thread_members() -> None:
    for kind in ("RELATIONSHIP", "THREAD"):
        with pytest.raises(ValidationError):
            v1_scene(entry_state_constraints=[{"constraint_kind": kind, "constraint_id": "c1"}])


def test_v2_scene_contract_defaults_omniscient_flag_to_false() -> None:
    assert v2_scene().omniscient_authoring_allowed_by_scene is False
    assert v2_scene(omniscient_authoring_allowed_by_scene=True).omniscient_authoring_allowed_by_scene is True


def test_v2_scene_contract_semantic_hash_version_is_pinned_to_v2() -> None:
    with pytest.raises(ValidationError):
        v2_scene(semantic_hash_version="r2-scene-contract-content-v1")


def test_scene_contract_value_selects_the_class_from_the_semantic_hash_version() -> None:
    adapter: TypeAdapter[SceneContractValue] = TypeAdapter(SceneContractValue)
    resolved_v1 = adapter.validate_python(v1_scene().model_dump())
    resolved_v2 = adapter.validate_python(v2_scene_with_relationship().model_dump())
    assert type(resolved_v1) is SceneContract
    assert type(resolved_v2) is SceneContractV2


def test_v2_plan_content_may_hold_both_v1_and_v2_scene_members() -> None:
    content = NarrativePlanContentV2(
        canon_basis=BASIS,
        story_frame="f",
        scene_contracts=[v1_scene(), v2_scene_with_relationship()],
    )
    kinds = {s.semantic_hash_version for s in content.scene_contracts}
    assert kinds == {"r2-scene-contract-content-v1", "r2-scene-contract-content-v2"}


def test_v2_plan_content_schema_version_is_pinned_to_v2() -> None:
    content = NarrativePlanContentV2(canon_basis=BASIS, story_frame="f")
    assert content.schema_version == "r2-narrative-plan-v2"
    with pytest.raises(ValidationError):
        NarrativePlanContentV2.model_validate(
            {"canon_basis": BASIS.model_dump(), "story_frame": "f", "schema_version": "r2-narrative-plan-v1"}
        )


def test_narrative_plan_schema_version_error_is_an_exception_type() -> None:
    assert issubclass(NarrativePlanSchemaVersionError, Exception)
    with pytest.raises(NarrativePlanSchemaVersionError):
        raise NarrativePlanSchemaVersionError("boom")


# --- v2 plan aggregate envelope: discriminator back-compat + selector coherence ----

_NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)


def test_missing_schema_version_tag_still_resolves_as_v1() -> None:
    adapter: TypeAdapter[NarrativePlanContentValue] = TypeAdapter(NarrativePlanContentValue)
    resolved = adapter.validate_python({"canon_basis": BASIS.model_dump(), "story_frame": "f"})
    assert type(resolved) is NarrativePlanContent
    assert resolved.schema_version == "r2-narrative-plan-v1"


def test_explicit_unknown_schema_version_tag_fails_closed() -> None:
    adapter: TypeAdapter[NarrativePlanContentValue] = TypeAdapter(NarrativePlanContentValue)
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {"canon_basis": BASIS.model_dump(), "story_frame": "f", "schema_version": "r2-narrative-plan-v9"}
        )


def test_scene_contract_value_missing_tag_resolves_v1_and_unknown_fails() -> None:
    adapter: TypeAdapter[SceneContractValue] = TypeAdapter(SceneContractValue)
    resolved = adapter.validate_python(
        {
            "scene_contract_id": "sc",
            "version": 1,
            "semantic_hash": "sh:x",
            "sequence_index": 0,
            "purpose": "p",
            "pov": None,
            "location_ref": None,
            "temporal_window": {"effective_from": FROM.isoformat(), "effective_until": UNTIL.isoformat()},
        }
    )
    assert type(resolved) is SceneContract
    with pytest.raises(ValidationError):
        adapter.validate_python({"scene_contract_id": "sc", "semantic_hash_version": "r2-scene-contract-content-v9"})


def _v2_content() -> NarrativePlanContentV2:
    return NarrativePlanContentV2(canon_basis=BASIS, story_frame="f")


def test_narrative_plan_rejects_a_selector_tuple_mismatch() -> None:
    with pytest.raises(ValidationError):
        NarrativePlan(
            plan_id="p1",
            version=1,
            content=_v2_content(),
            content_hash="np:x",
            content_hash_version="r2-narrative-plan-content-v1",  # v2 content, v1 hash selector
            committed_at=_NOW,
            committed_by="a",
            approval_ref="ap-1",
        )


def test_version_snapshot_rejects_an_outer_schema_that_disagrees_with_the_content() -> None:
    kwargs = {
        "plan_id": "p1",
        "version": 1,
        "user_id": "u1",
        "project_name": "proj",
        "plan_revision_id": "rev-1",
        "parent_version": None,
        "canon_branch_id": "br-1",
        "canon_version_id": "cv-1",
        "content": _v2_content(),
        "content_hash": "np:x",
        "approval_ref": "ap-1",
        "approved_by": "a",
        "approved_at": _NOW,
        "committed_at": _NOW,
        "committed_by": "a",
    }
    with pytest.raises(ValidationError):
        NarrativePlanVersionSnapshot(
            schema_version="r2-narrative-plan-v1", content_hash_version="r2-narrative-plan-content-v1", **kwargs
        )
    ok = NarrativePlanVersionSnapshot(
        schema_version="r2-narrative-plan-v2",
        content_hash_version="r2-narrative-plan-content-v2",
        **kwargs,
    )
    assert ok.schema_version == "r2-narrative-plan-v2"
