from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import (
    CanonContent,
    Entity,
    EntityType,
    EpistemicProposition,
    EpistemicState,
    Fact,
    KnowledgeState,
    NarrativePlan,
    NarrativePlanContent,
    SceneContract,
    SceneFactConstraint,
    SceneKnowledgeConstraint,
    SceneTemporalWindow,
    compute_epistemic_proposition_ref,
)
from r2.narrative import NarrativeInvariantValidator, ResolvedCanonView
from r2.narrative.hashing import compute_canon_content_hash
from r2.narrative_plan.errors import NarrativePlanIdentityConflictError
from r2.narrative_plan.hashing import compute_plan_content_hash, compute_scene_semantic_hash
from r2.narrative_plan.validation import (
    next_scene_version,
    validate_plan_hierarchy,
    validate_scene_version,
)
from tests.unit.r2.narrative_plan._helpers import node, plan_content, scene_contract

S_FROM = datetime(2026, 3, 1, 10, tzinfo=UTC)
S_UNTIL = datetime(2026, 3, 1, 12, tzinfo=UTC)
RING = compute_epistemic_proposition_ref(subject_ref="obj-ring", predicate="owner", object_or_value="char-b")


def rule_ids(report: object) -> list[str]:
    return [finding.rule_id for finding in report.findings]


def test_byte_identical_scene_must_retain_its_version() -> None:
    previous = scene_contract(version=3, purpose="discover ring")
    same = previous.model_copy(update={"version": 3})
    assert validate_scene_version(previous=previous, proposed=same).ok
    with pytest.raises(NarrativePlanIdentityConflictError):
        validate_scene_version(previous=previous, proposed=previous.model_copy(update={"version": 4}))


def test_changed_scene_semantics_require_exactly_next_version() -> None:
    previous = scene_contract(version=3, purpose="discover ring")
    changed = scene_contract(version=3, purpose="hide ring")
    with pytest.raises(NarrativePlanIdentityConflictError):
        validate_scene_version(previous=previous, proposed=changed)
    assert validate_scene_version(previous=previous, proposed=changed.model_copy(update={"version": 4})).ok


def test_decreasing_or_skipping_a_scene_version_is_a_conflict() -> None:
    previous = scene_contract(version=3, purpose="discover ring")
    with pytest.raises(NarrativePlanIdentityConflictError):
        validate_scene_version(previous=previous, proposed=scene_contract(version=2, purpose="hide ring"))
    with pytest.raises(NarrativePlanIdentityConflictError):
        validate_scene_version(previous=previous, proposed=scene_contract(version=6, purpose="hide ring"))


def test_next_scene_version_from_history() -> None:
    history = (scene_contract(version=1, purpose="a"), scene_contract(version=2, purpose="b"))
    assert next_scene_version(history=history, semantic_hash="sh:brand-new") == 3
    assert next_scene_version(history=history, semantic_hash=history[0].semantic_hash) == 1
    assert next_scene_version(history=(), semantic_hash="sh:brand-new") == 1


def test_clean_hierarchy_passes() -> None:
    content = plan_content(
        volume_plans=[node("vol-1", "VOLUME", child_refs=["arc-1"])],
        arc_plans=[node("arc-1", "ARC", parent_id="vol-1")],
    )
    assert validate_plan_hierarchy(content).findings == ()


def test_hierarchy_cycle_is_reported() -> None:
    content = plan_content(
        arc_plans=[
            node("arc-1", "ARC", parent_id="arc-2"),
            node("arc-2", "ARC", parent_id="arc-1"),
        ]
    )
    assert "PLAN_HIERARCHY_CYCLE" in rule_ids(validate_plan_hierarchy(content))


def test_missing_child_and_child_asymmetry_are_reported() -> None:
    missing = plan_content(volume_plans=[node("vol-1", "VOLUME", child_refs=["ghost"])])
    assert "PLAN_HIERARCHY_MISSING_CHILD" in rule_ids(validate_plan_hierarchy(missing))
    asymmetry = plan_content(
        volume_plans=[node("vol-1", "VOLUME", child_refs=["arc-1"])],
        arc_plans=[node("arc-1", "ARC", parent_id="vol-2")],
    )
    ids = rule_ids(validate_plan_hierarchy(asymmetry))
    assert "PLAN_HIERARCHY_CHILD_ASYMMETRY" in ids
    assert "PLAN_HIERARCHY_MISSING_PARENT" in ids


def test_illegal_parent_kind_is_reported() -> None:
    content = plan_content(
        arc_plans=[node("arc-1", "ARC", child_refs=["vol-1"])],
        volume_plans=[node("vol-1", "VOLUME", parent_id="arc-1")],
    )
    assert "PLAN_HIERARCHY_ILLEGAL_PARENT" in rule_ids(validate_plan_hierarchy(content))


def test_duplicate_sibling_sequence_index_is_reported() -> None:
    content = plan_content(
        volume_plans=[node("vol-1", "VOLUME", child_refs=["arc-1", "arc-2"])],
        arc_plans=[
            node("arc-1", "ARC", parent_id="vol-1", sequence_index=0),
            node("arc-2", "ARC", parent_id="vol-1", sequence_index=0),
        ],
    )
    assert "PLAN_HIERARCHY_DUPLICATE_SEQUENCE_INDEX" in rule_ids(validate_plan_hierarchy(content))


# --- validate_scene / validate_scene_outcome ------------------------------------


def _prop() -> EpistemicProposition:
    return EpistemicProposition(
        proposition_ref=RING, subject_ref="obj-ring", predicate="owner", object_or_value="char-b"
    )


def _canon(*, facts: list[Fact] | None = None, states: list[KnowledgeState] | None = None) -> ResolvedCanonView:
    content = CanonContent(
        entities_by_id={
            "char-a": Entity(entity_id="char-a", entity_type=EntityType.CHARACTER, canonical_name="A"),
            "obj-ring": Entity(entity_id="obj-ring", entity_type=EntityType.OBJECT, canonical_name="Ring"),
        },
        facts_by_id={fact.fact_id: fact for fact in (facts or [])},
        events_by_id={},
        epistemic_propositions_by_ref={RING: _prop()} if states else {},
        knowledge_states_by_id={state.knowledge_state_id: state for state in (states or [])},
    )
    return ResolvedCanonView(
        canon_version_id="v-1",
        branch_id="main",
        content_hash=compute_canon_content_hash(content, schema_version="r2-canon-schema-v2"),
        content_schema_version="r2-canon-schema-v2",
        content=content,
    )


def _plan() -> NarrativePlan:
    from r2.contracts import CanonBasis

    content = NarrativePlanContent(canon_basis=CanonBasis(branch_id="main", canon_version_id="v-1"), story_frame="f")
    return NarrativePlan(
        plan_id="plan-1",
        version=1,
        content=content,
        content_hash=compute_plan_content_hash(content),
        committed_at=S_FROM,
        committed_by="lead",
        approval_ref="ap-1",
    )


def _scene(*, entry: list | None = None, forbidden_knowledge: list | None = None) -> SceneContract:
    draft = SceneContract(
        scene_contract_id="scene-1",
        version=1,
        semantic_hash="sh:x",
        sequence_index=0,
        purpose="beat",
        pov=None,
        location_ref=None,
        temporal_window=SceneTemporalWindow(effective_from=S_FROM, effective_until=S_UNTIL),
        entry_state_constraints=entry or [],
        forbidden_knowledge=forbidden_knowledge or [],
    )
    return draft.model_copy(update={"semantic_hash": compute_scene_semantic_hash(draft)})


def test_validate_scene_entry_fact_constraint_pass_and_fail() -> None:
    owns = Fact(fact_id="f-1", subject_ref="obj-ring", predicate="owner", value="char-b", effective_from=S_FROM)
    constraint = SceneFactConstraint(
        constraint_id="c-1", subject_ref="obj-ring", predicate="owner", comparison="PRESENT"
    )
    ok = NarrativeInvariantValidator().validate_scene(
        canon=_canon(facts=[owns]), plan=_plan(), scene=_scene(entry=[constraint])
    )
    assert ok.findings == ()
    bad = NarrativeInvariantValidator().validate_scene(
        canon=_canon(facts=[]), plan=_plan(), scene=_scene(entry=[constraint])
    )
    assert [f.rule_id for f in bad.findings] == ["SCENE_ENTRY_FACT_UNMET"]


def test_validate_scene_forbidden_knowledge_detects_a_window_overlap() -> None:
    state = KnowledgeState(
        knowledge_state_id="k-1",
        subject_entity_id="char-a",
        proposition_ref=RING,
        epistemic_state=EpistemicState.KNOWN,
        effective_from=S_FROM,
    )
    forbidden = SceneKnowledgeConstraint(
        constraint_id="fk-1", subject_entity_id="char-a", proposition_ref=RING, states=[EpistemicState.KNOWN]
    )
    report = NarrativeInvariantValidator().validate_scene(
        canon=_canon(states=[state]), plan=_plan(), scene=_scene(forbidden_knowledge=[forbidden])
    )
    assert "SCENE_KNOWLEDGE_FORBIDDEN_MATCH" in [f.rule_id for f in report.findings]
