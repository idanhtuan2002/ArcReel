from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import (
    CanonBasis,
    CanonContent,
    Entity,
    EntityType,
    Fact,
    NarrativePlan,
    NarrativePlanContent,
)
from r2.contracts.narrative_plan import (
    SceneContractV2,
    SceneFactConstraint,
    SceneRelationshipConstraint,
    SceneTemporalWindow,
)
from r2.narrative.canon_state import ResolvedCanonView
from r2.narrative.relationship_facts import relationship_fact_predicate
from r2.narrative.validation import NarrativeInvariantValidator, validate_scene_relationship

AT_09 = datetime(2026, 9, 1, tzinfo=UTC)
ENTRY = datetime(2026, 9, 2, tzinfo=UTC)
EXIT = datetime(2026, 9, 3, tzinfo=UTC)


def entity(entity_id: str, kind: EntityType = EntityType.CHARACTER) -> Entity:
    return Entity(entity_id=entity_id, entity_type=kind, canonical_name=entity_id.title(), aliases=[])


def rel_fact(
    source: str,
    target: str,
    key: str,
    state: object,
    frm: datetime | None,
    until: datetime | None,
) -> Fact:
    return Fact(
        fact_id=f"f-{source}-{target}-{key}-{state}",
        subject_ref=source,
        predicate=relationship_fact_predicate(target, key),
        value=state,
        effective_from=frm,
        effective_until=until,
        source_event_refs=[],
    )


def canon_with_characters(*names: str, facts: list[Fact] | None = None) -> ResolvedCanonView:
    content = CanonContent(
        entities_by_id={n: entity(n) for n in names},
        facts_by_id={f.fact_id: f for f in (facts or [])},
        events_by_id={},
    )
    return ResolvedCanonView(
        canon_version_id="cv-1",
        branch_id="main",
        content_hash="scene-eval",
        content_schema_version="r2-canon-schema-v2",
        content=content,
    )


def rel_constraint(
    comparison: str,
    expected_state: str | None,
    *,
    constraint_id: str = "rc-1",
    source: str = "hero",
    target: str = "mentor",
    key: str = "trust_level",
) -> SceneRelationshipConstraint:
    return SceneRelationshipConstraint(
        constraint_id=constraint_id,
        source_character_ref=source,
        target_character_ref=target,
        relationship_key=key,
        comparison=comparison,
        expected_state=expected_state,
    )


@pytest.mark.parametrize(
    ("comparison", "expected_state", "facts", "phase", "rule"),
    [
        ("PRESENT", None, [rel_fact("hero", "mentor", "trust_level", "TRUSTED", AT_09, None)], "entry", None),
        (
            "ABSENT",
            None,
            [rel_fact("hero", "mentor", "trust_level", "TRUSTED", AT_09, None)],
            "entry",
            "SCENE_ENTRY_RELATIONSHIP_UNMET",
        ),
        (
            "EQUALS",
            "BROKEN",
            [rel_fact("hero", "mentor", "trust_level", "TRUSTED", AT_09, None)],
            "exit",
            "SCENE_EXIT_RELATIONSHIP_UNMET",
        ),
        ("NOT_EQUALS", "TRUSTED", [], "entry", "SCENE_ENTRY_RELATIONSHIP_UNMET"),  # absence is not inequality
        ("PRESENT", None, [], "entry", "SCENE_ENTRY_RELATIONSHIP_UNMET"),
        (
            "EQUALS",
            "TRUSTED",
            [rel_fact("hero", "mentor", "trust_level", "TRUSTED", AT_09, None)],
            "entry",
            None,
        ),
        (
            "NOT_EQUALS",
            "BROKEN",
            [rel_fact("hero", "mentor", "trust_level", "TRUSTED", AT_09, None)],
            "entry",
            None,
        ),
    ],
)
def test_relationship_comparison_matrix(
    comparison: str, expected_state: str | None, facts: list[Fact], phase: str, rule: str | None
) -> None:
    at = ENTRY if phase == "entry" else EXIT
    report = validate_scene_relationship(
        canon=canon_with_characters("hero", "mentor", facts=facts),
        constraint=rel_constraint(comparison, expected_state),
        at=at,
        phase=phase,
    )
    observed = report.findings[0].rule_id if report.findings else None
    assert observed == rule


def test_reversed_direction_and_wrong_key_do_not_match_the_exact_key() -> None:
    facts = [rel_fact("mentor", "hero", "trust_level", "TRUSTED", AT_09, None)]
    report = validate_scene_relationship(
        canon=canon_with_characters("hero", "mentor", facts=facts),
        constraint=rel_constraint("PRESENT", None),
        at=ENTRY,
        phase="entry",
    )
    assert [f.rule_id for f in report.findings] == ["SCENE_ENTRY_RELATIONSHIP_UNMET"]


def test_two_active_relationship_facts_for_the_same_key_is_an_integrity_finding() -> None:
    report = validate_scene_relationship(
        canon=canon_with_characters(
            "hero",
            "mentor",
            facts=[
                rel_fact("hero", "mentor", "trust_level", "TRUSTED", AT_09, None),
                Fact(
                    fact_id="f-dup",
                    subject_ref="hero",
                    predicate=relationship_fact_predicate("mentor", "trust_level"),
                    value="TRUSTED",
                    effective_from=AT_09,
                    effective_until=None,
                    source_event_refs=[],
                ),
            ],
        ),
        constraint=rel_constraint("PRESENT", None),
        at=ENTRY,
        phase="entry",
    )
    assert [f.rule_id for f in report.findings] == ["RELATIONSHIP_INTEGRITY"]


def test_non_string_relationship_state_is_an_integrity_finding_not_absence() -> None:
    report = validate_scene_relationship(
        canon=canon_with_characters(
            "hero", "mentor", facts=[rel_fact("hero", "mentor", "trust_level", {"x": 1}, AT_09, None)]
        ),
        constraint=rel_constraint("PRESENT", None),
        at=ENTRY,
        phase="entry",
    )
    assert [f.rule_id for f in report.findings] == ["RELATIONSHIP_INTEGRITY"]


def test_unresolved_or_non_character_endpoints_are_integrity_findings() -> None:
    missing = validate_scene_relationship(
        canon=canon_with_characters("hero"),  # no mentor
        constraint=rel_constraint("PRESENT", None),
        at=ENTRY,
        phase="entry",
    )
    assert [f.rule_id for f in missing.findings] == ["RELATIONSHIP_INTEGRITY"]

    content = CanonContent(
        entities_by_id={"hero": entity("hero"), "mentor": entity("mentor", EntityType.LOCATION)},
        facts_by_id={},
        events_by_id={},
    )
    view = ResolvedCanonView(
        canon_version_id="cv-1",
        branch_id="main",
        content_hash="scene-eval",
        content_schema_version="r2-canon-schema-v2",
        content=content,
    )
    non_char = validate_scene_relationship(
        canon=view, constraint=rel_constraint("PRESENT", None), at=ENTRY, phase="entry"
    )
    assert [f.rule_id for f in non_char.findings] == ["RELATIONSHIP_INTEGRITY"]


def test_relationship_fact_active_only_inside_its_half_open_interval() -> None:
    facts = [rel_fact("hero", "mentor", "trust_level", "TRUSTED", AT_09, EXIT)]
    canon = canon_with_characters("hero", "mentor", facts=facts)
    inside = validate_scene_relationship(
        canon=canon, constraint=rel_constraint("PRESENT", None), at=ENTRY, phase="entry"
    )
    at_boundary = validate_scene_relationship(
        canon=canon, constraint=rel_constraint("PRESENT", None), at=EXIT, phase="exit"
    )
    assert inside.findings == ()
    assert [f.rule_id for f in at_boundary.findings] == ["SCENE_EXIT_RELATIONSHIP_UNMET"]


# --- validate_scene integration: relationship + R9 + R10 -----------------------

_WINDOW = SceneTemporalWindow(effective_from=ENTRY, effective_until=EXIT)


def _canon() -> ResolvedCanonView:
    return canon_with_characters("hero", "mentor")


def _plan() -> NarrativePlan:
    return NarrativePlan(
        plan_id="plan-1",
        version=1,
        content=NarrativePlanContent(
            canon_basis=CanonBasis(branch_id="main", canon_version_id="cv-1"),
            story_frame="frame",
        ),
        content_hash="np:x",
        committed_at=AT_09,
        committed_by="author",
        approval_ref="ap-1",
    )


def _scene_v2(**overrides: object) -> SceneContractV2:
    kwargs: dict[str, object] = {
        "scene_contract_id": "sc-1",
        "version": 1,
        "semantic_hash": "sh:x",
        "sequence_index": 0,
        "purpose": "p",
        "pov": None,
        "location_ref": None,
        "temporal_window": _WINDOW,
    }
    kwargs.update(overrides)
    return SceneContractV2(**kwargs)


def _fact_constraint(cid: str, subject: str, predicate: str, comparison: str) -> SceneFactConstraint:
    return SceneFactConstraint(
        constraint_id=cid,
        subject_ref=subject,
        predicate=predicate,
        comparison=comparison,
    )


def test_validate_scene_flags_entry_relationship_constraint_through_the_public_entry_point() -> None:
    scene = _scene_v2(entry_state_constraints=[rel_constraint("PRESENT", None)])
    report = NarrativeInvariantValidator().validate_scene(canon=_canon(), plan=_plan(), scene=scene)
    assert "SCENE_ENTRY_RELATIONSHIP_UNMET" in [f.rule_id for f in report.findings]


def test_r9_unresolved_present_state_ref_fails_at_plan_commit() -> None:
    scene = _scene_v2(entry_state_constraints=[_fact_constraint("c1", "ghost", "role", "PRESENT")])
    report = NarrativeInvariantValidator().validate_scene(canon=_canon(), plan=_plan(), scene=scene)
    assert "SCENE_PRESENT_REF_UNRESOLVED" in [f.rule_id for f in report.findings]


def test_r9_resolved_present_state_ref_does_not_raise_the_unresolved_finding() -> None:
    scene = _scene_v2(entry_state_constraints=[_fact_constraint("c1", "hero", "role", "PRESENT")])
    report = NarrativeInvariantValidator().validate_scene(canon=_canon(), plan=_plan(), scene=scene)
    assert "SCENE_PRESENT_REF_UNRESOLVED" not in [f.rule_id for f in report.findings]


def test_r10_rejects_duplicate_constraint_id() -> None:
    scene = _scene_v2(
        entry_state_constraints=[
            _fact_constraint("dup", "hero", "role", "PRESENT"),
            _fact_constraint("dup", "mentor", "role", "PRESENT"),
        ]
    )
    report = NarrativeInvariantValidator().validate_scene(canon=_canon(), plan=_plan(), scene=scene)
    assert "SCENE_CONSTRAINT_DUPLICATE_ID" in [f.rule_id for f in report.findings]


def test_r10_rejects_normalized_semantic_duplicate_under_a_different_id() -> None:
    scene = _scene_v2(
        entry_state_constraints=[
            _fact_constraint("c1", "hero", "role", "PRESENT"),
            _fact_constraint("c2", "hero", "role", "PRESENT"),
        ]
    )
    report = NarrativeInvariantValidator().validate_scene(canon=_canon(), plan=_plan(), scene=scene)
    assert "SCENE_CONSTRAINT_DUPLICATE_SEMANTIC" in [f.rule_id for f in report.findings]


def test_r10_distinct_constraints_do_not_trip_either_duplicate_rule() -> None:
    scene = _scene_v2(
        entry_state_constraints=[
            _fact_constraint("c1", "hero", "role", "PRESENT"),
            _fact_constraint("c2", "mentor", "rank", "PRESENT"),
        ]
    )
    report = NarrativeInvariantValidator().validate_scene(canon=_canon(), plan=_plan(), scene=scene)
    rule_ids = [f.rule_id for f in report.findings]
    assert "SCENE_CONSTRAINT_DUPLICATE_ID" not in rule_ids
    assert "SCENE_CONSTRAINT_DUPLICATE_SEMANTIC" not in rule_ids


def test_validate_scene_still_accepts_a_v1_scene_contract_unchanged() -> None:
    from r2.contracts.narrative_plan import SceneContract

    v1 = SceneContract(
        scene_contract_id="sc-v1",
        version=1,
        semantic_hash="sh:x",
        sequence_index=0,
        purpose="p",
        pov=None,
        location_ref=None,
        temporal_window=_WINDOW,
        entry_state_constraints=[_fact_constraint("c1", "hero", "role", "PRESENT")],
    )
    report = NarrativeInvariantValidator().validate_scene(canon=_canon(), plan=_plan(), scene=v1)
    assert all(f.rule_id.startswith(("SCENE_", "M5A_", "EPI_")) for f in report.findings)
