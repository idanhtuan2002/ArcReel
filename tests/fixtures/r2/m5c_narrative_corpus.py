"""Combined M5 v1/v2 acceptance corpus (spec Section 16.9).

Extends — never replaces — the accepted M5B v1 corpus: ``m5b_v1_corpus`` replays
``tests.fixtures.r2.m5b_narrative_corpus.full_corpus`` byte for byte under its original
v1 selectors, and everything else here is the M5C v2 surface layered beside it: a mixed
v1/v2 plan, a directional relationship Fact with entry/exit constraints over exact
effective instants, a presentation-order thread lifecycle carried across a story-time
jump, accepted and unaccepted thread-payoff proofs, the two halves of the no-POV
``AUTHOR_DRAFT`` gate, R9/R10 regression scenes, and the exact pure-compiler inputs
(policy, reviewed change sets, resolutions) the acceptance suite drives.

Plain builder functions only — no fixtures, no service wiring, no database. Every
instant, id, span, and hash is fixed, so two calls produce equal values.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from r2.contracts import (
    AddFactOperation,
    CanonBasis,
    CanonContent,
    Entity,
    EntityType,
    Fact,
    NarrativePlan,
    NarrativePlanContentV2,
    SceneContract,
    SceneContractV2,
    SceneFactConstraint,
    SceneRelationshipConstraint,
    SceneTemporalWindow,
    SceneThreadConstraint,
)
from r2.contracts.narrative import CANON_SCHEMA_V1
from r2.contracts.narrative_lifecycle import (
    AcceptedThreadPayoffProof,
    CompilationSelectedChangeSet,
    ConflictResolutionCommand,
    NarrativeChangeSet,
    SourceSpan,
    ThreadPayoffEffectKey,
)
from r2.narrative.canon_state import ResolvedCanonView
from r2.narrative.hashing import compute_canon_content_hash
from r2.narrative.relationship_facts import relationship_fact_predicate
from r2.narrative_lifecycle.compiler import (
    COMPILER_POLICY_VERSION,
    COMPILER_VERSION,
    RESOLUTION_INSTRUCTION_VERSION,
    CanonMutationRule,
    CompilationOutputIdentity,
    CompilerPolicy,
    ExactCanonBase,
    ReplacementEffectRule,
    ReviewedChangeSet,
)
from r2.narrative_plan.hashing import (
    compute_plan_content_hash_v2,
    compute_scene_semantic_hash,
    compute_scene_semantic_hash_v2,
)
from tests.factories import (
    make_canon_mutation_effect_key,
    make_compilation_attempt,
    make_conflict_resolution_command,
    make_narrative_change_set,
    make_narrative_revision,
    make_narrative_work_scope,
)
from tests.fixtures.r2.m5b_narrative_corpus import FullCorpus
from tests.fixtures.r2.m5b_narrative_corpus import full_corpus as _m5b_full_corpus

USER = "u1"
PROJECT = "project-a"
BRANCH = "main"
CANON_VERSION = "m5c-canon-1"
PLAN_ID = "m5c-plan"

# Presentation order and story time are deliberately different sequences below, so a
# mutation that confuses the two is observable rather than accidentally equivalent.
C0 = datetime(2026, 5, 1, 8, tzinfo=UTC)
C1 = datetime(2026, 5, 1, 10, tzinfo=UTC)
C2 = datetime(2026, 5, 1, 12, tzinfo=UTC)
C3 = datetime(2026, 5, 1, 14, tzinfo=UTC)
C4 = datetime(2026, 5, 1, 16, tzinfo=UTC)

HERO = "char-hero"
MENTOR = "char-mentor"
RIVAL = "char-rival"
TRUST = "trust_level"
TRUST_STATE = "high"

THREAD = "thread-vow"
PAYOFF = "payoff-vow-kept"
PAYOFF_SPAN = SourceSpan(start=0, end=4)


# --- the accepted M5B v1 corpus, replayed under its original selectors ----------


def m5b_v1_corpus() -> FullCorpus:
    """The accepted M5B corpus, unmodified. Its scenes stay ``SceneContract`` (v1) with
    ``r2-scene-contract-content-v1`` selectors and their original v1 semantic hashes."""
    return _m5b_full_corpus()


# --- Canon: entities plus one directional relationship Fact ---------------------


def relationship_predicate(*, target: str = MENTOR, key: str = TRUST) -> str:
    """The one legal relationship predicate mapping. Nothing in this corpus builds an
    ``r2rel:`` string any other way."""
    return relationship_fact_predicate(target, key)


def corpus_canon_content() -> CanonContent:
    """Three characters and one directional ``hero -> mentor`` trust Fact effective over
    the half-open interval ``[C1, C3)``."""
    return CanonContent(
        entities_by_id={
            HERO: Entity(entity_id=HERO, entity_type=EntityType.CHARACTER, canonical_name="Hero"),
            MENTOR: Entity(entity_id=MENTOR, entity_type=EntityType.CHARACTER, canonical_name="Mentor"),
            RIVAL: Entity(entity_id=RIVAL, entity_type=EntityType.CHARACTER, canonical_name="Rival"),
        },
        facts_by_id={
            "fact-trust": Fact(
                fact_id="fact-trust",
                subject_ref=HERO,
                predicate=relationship_predicate(),
                value=TRUST_STATE,
                effective_from=C1,
                effective_until=C3,
            )
        },
        events_by_id={},
        epistemic_propositions_by_ref={},
        knowledge_states_by_id={},
        temporal_relations_by_id={},
    )


def corpus_canon(*, content: CanonContent | None = None) -> ResolvedCanonView:
    content = content or corpus_canon_content()
    return ResolvedCanonView(
        canon_version_id=CANON_VERSION,
        branch_id=BRANCH,
        content_hash=compute_canon_content_hash(content, schema_version="r2-canon-schema-v2"),
        content_schema_version="r2-canon-schema-v2",
        content=content,
    )


# --- relationship constraints over exact effective instants ---------------------


def relationship_constraint(
    *,
    constraint_id: str = "rc-entry",
    source: str = HERO,
    target: str = MENTOR,
    key: str = TRUST,
    comparison: str = "EQUALS",
    expected_state: str | None = TRUST_STATE,
) -> SceneRelationshipConstraint:
    return SceneRelationshipConstraint(
        constraint_id=constraint_id,
        source_character_ref=source,
        target_character_ref=target,
        relationship_key=key,
        comparison=comparison,
        expected_state=expected_state,
    )


def entry_relationship_constraint() -> SceneRelationshipConstraint:
    """Met at ``C1``: the trust Fact is active from ``C1`` inclusive."""
    return relationship_constraint(constraint_id="rc-entry")


def exit_relationship_constraint() -> SceneRelationshipConstraint:
    """Met at ``C3``: the interval is half-open, so the Fact is already gone."""
    return relationship_constraint(constraint_id="rc-exit", comparison="ABSENT", expected_state=None)


def relationship_scene(
    *,
    scene_id: str = "scene-rel",
    entry: SceneRelationshipConstraint | None = None,
    exit_target: SceneRelationshipConstraint | None = None,
) -> SceneContractV2:
    """One v2 scene whose window is exactly the trust Fact's interval, so the entry
    comparison runs at ``C1`` and the exit comparison at ``C3``."""
    return _sealed_v2(
        SceneContractV2(
            scene_contract_id=scene_id,
            version=1,
            semantic_hash="sh:placeholder",
            sequence_index=0,
            purpose="the vow is spoken",
            pov=None,
            location_ref=None,
            temporal_window=SceneTemporalWindow(effective_from=C1, effective_until=C3),
            entry_state_constraints=[entry or entry_relationship_constraint()],
            exit_state_targets=[exit_target or exit_relationship_constraint()],
        )
    )


# --- mixed-version plan: unchanged v1 scenes beside upgraded v2 scenes ----------


def unchanged_v1_scene(*, scene_id: str = "scene-v1", sequence_index: int = 0) -> SceneContract:
    """A v1 scene that keeps its exact v1 bytes, selector, and hash inside a v2 plan."""
    draft = SceneContract(
        scene_contract_id=scene_id,
        version=1,
        semantic_hash="sh:placeholder",
        sequence_index=sequence_index,
        purpose="the road out",
        pov=HERO,
        location_ref=None,
        temporal_window=SceneTemporalWindow(effective_from=C0, effective_until=C1),
        entry_state_constraints=[
            SceneFactConstraint(constraint_id="c-v1", subject_ref=HERO, predicate="mood", comparison="ABSENT")
        ],
    )
    return draft.model_copy(update={"semantic_hash": compute_scene_semantic_hash(draft)})


def upgraded_v2_scene(*, scene_id: str = "scene-v2", sequence_index: int = 1) -> SceneContractV2:
    return relationship_scene(scene_id=scene_id).model_copy(update={"sequence_index": sequence_index})


def mixed_version_plan_content() -> NarrativePlanContentV2:
    v2_scene = _sealed_v2(upgraded_v2_scene())
    return NarrativePlanContentV2(
        canon_basis=CanonBasis(branch_id=BRANCH, canon_version_id=CANON_VERSION),
        story_frame="the vow and the road",
        scene_contracts=[unchanged_v1_scene(), v2_scene],
    )


def mixed_version_plan() -> NarrativePlan:
    content = mixed_version_plan_content()
    return NarrativePlan(
        plan_id=PLAN_ID,
        version=1,
        content=content,
        content_hash=compute_plan_content_hash_v2(content),
        content_hash_version="r2-narrative-plan-content-v2",
        committed_at=C0,
        committed_by="lead",
        approval_ref="m5c-approval",
    )


# --- thread lifecycle in presentation order, across a story-time jump -----------


def thread_scene(
    *,
    scene_id: str,
    sequence_index: int,
    story_from: datetime,
    story_until: datetime,
    active_threads: list[str] | None = None,
    promise_payoff_refs: list[str] | None = None,
    entry: list[object] | None = None,
    exit_targets: list[object] | None = None,
) -> SceneContractV2:
    return _sealed_v2(
        SceneContractV2(
            scene_contract_id=scene_id,
            version=1,
            semantic_hash="sh:placeholder",
            sequence_index=sequence_index,
            purpose=f"beat {sequence_index}",
            pov=None,
            location_ref=None,
            temporal_window=SceneTemporalWindow(effective_from=story_from, effective_until=story_until),
            active_threads=active_threads or [],
            promise_payoff_refs=promise_payoff_refs or [],
            entry_state_constraints=entry or [],
            exit_state_targets=exit_targets or [],
        )
    )


def thread_plan_content() -> NarrativePlanContentV2:
    """The required thread shape, in presentation order:

    - ``scene-t0`` opens ``thread-vow`` (story time ``C0``);
    - ``scene-t1`` is an intermediate unrelated scene that omits the thread entirely;
    - ``scene-t2`` carries the thread across a story-time jump — it is authored third but
      happens *earliest* of the three that follow, at ``C0``-adjacent time;
    - ``scene-t3`` resolves the thread exactly once, by the exact payoff ref it also
      declares in ``promise_payoff_refs``.

    Presentation order (``sequence_index``) is the lifecycle order; story time is not.
    """
    open_entry = SceneThreadConstraint(constraint_id="tc-open", thread_ref=THREAD, required_state="OPEN")
    resolve_exit = SceneThreadConstraint(
        constraint_id="tc-resolve", thread_ref=THREAD, required_state="RESOLVED", payoff_ref=PAYOFF
    )
    return NarrativePlanContentV2(
        canon_basis=CanonBasis(branch_id=BRANCH, canon_version_id=CANON_VERSION),
        story_frame="the vow thread",
        scene_contracts=[
            thread_scene(scene_id="scene-t0", sequence_index=0, story_from=C2, story_until=C3, active_threads=[THREAD]),
            thread_scene(scene_id="scene-t1", sequence_index=1, story_from=C3, story_until=C4),
            thread_scene(
                scene_id="scene-t2",
                sequence_index=2,
                story_from=C0,  # the story-time jump: authored third, happens first
                story_until=C1,
                active_threads=[THREAD],
                entry=[open_entry],
            ),
            thread_scene(
                scene_id="scene-t3",
                sequence_index=3,
                story_from=C1,
                story_until=C2,
                active_threads=[THREAD],
                promise_payoff_refs=[PAYOFF],
                exit_targets=[resolve_exit],
            ),
        ],
    )


def story_time_ordered_plan_content() -> NarrativePlanContentV2:
    """The same four scenes re-indexed by story time instead of presentation order — the
    mutation that treats story-time order as lifecycle order. The thread's entry
    expectation now precedes the scene that opens it."""
    scenes = sorted(thread_plan_content().scene_contracts, key=lambda scene: scene.temporal_window.effective_from)
    reindexed = [_sealed_v2(scene.model_copy(update={"sequence_index": index})) for index, scene in enumerate(scenes)]
    return NarrativePlanContentV2(
        canon_basis=CanonBasis(branch_id=BRANCH, canon_version_id=CANON_VERSION),
        story_frame="the vow thread",
        scene_contracts=reindexed,
    )


def thread_resolved_before_open_plan_content() -> NarrativePlanContentV2:
    """A thread resolved before it opens, resolved twice, and re-introduced after
    resolution — the three ``SCENE_THREAD_LIFECYCLE_*`` mutations in one plan."""
    ghost = SceneThreadConstraint(
        constraint_id="tc-ghost", thread_ref="thread-ghost", required_state="RESOLVED", payoff_ref="payoff-ghost"
    )
    resolve = SceneThreadConstraint(
        constraint_id="tc-r1", thread_ref=THREAD, required_state="RESOLVED", payoff_ref=PAYOFF
    )
    resolve_again = SceneThreadConstraint(
        constraint_id="tc-r2", thread_ref=THREAD, required_state="RESOLVED", payoff_ref=PAYOFF
    )
    return NarrativePlanContentV2(
        canon_basis=CanonBasis(branch_id=BRANCH, canon_version_id=CANON_VERSION),
        story_frame="the broken vow thread",
        scene_contracts=[
            # resolves a thread that was never opened
            thread_scene(
                scene_id="scene-b0",
                sequence_index=0,
                story_from=C0,
                story_until=C1,
                promise_payoff_refs=["payoff-ghost"],
                exit_targets=[ghost],
            ),
            thread_scene(scene_id="scene-b1", sequence_index=1, story_from=C1, story_until=C2, active_threads=[THREAD]),
            thread_scene(
                scene_id="scene-b2",
                sequence_index=2,
                story_from=C2,
                story_until=C3,
                active_threads=[THREAD],
                promise_payoff_refs=[PAYOFF],
                exit_targets=[resolve],
            ),
            # resolves the same thread a second time, and re-opens it by re-listing it
            thread_scene(
                scene_id="scene-b3",
                sequence_index=3,
                story_from=C3,
                story_until=C4,
                active_threads=[THREAD],
                promise_payoff_refs=[PAYOFF],
                exit_targets=[resolve_again],
            ),
        ],
    )


# --- thread-payoff outcome proofs ----------------------------------------------


def payoff_change_set(*, change_set_id: str = "cs-payoff") -> NarrativeChangeSet:
    """The change set that carries the exact ``THREAD_PAYOFF(thread, payoff)`` key and
    covers the proof's source span."""
    return make_narrative_change_set(
        change_set_id=change_set_id,
        key=ThreadPayoffEffectKey(thread_ref=THREAD, payoff_ref=PAYOFF),
        span=PAYOFF_SPAN,
    )


def accepted_payoff_proof(
    *,
    change_set_id: str = "cs-payoff",
    revision_acceptance_decision_id: str = "d-1",
    review_decision_id: str = "d-2",
) -> AcceptedThreadPayoffProof:
    return AcceptedThreadPayoffProof(
        thread_ref=THREAD,
        payoff_ref=PAYOFF,
        revision_id="rev-1",
        revision_acceptance_decision_id=revision_acceptance_decision_id,
        change_set_id=change_set_id,
        review_decision_id=review_decision_id,
        source_spans=(PAYOFF_SPAN,),
    )


def accepted_payoff_decisions() -> set[str]:
    """The exact decision ids ``accepted_payoff_proof`` requires to be effective."""
    return {"d-1", "d-2"}


def unaccepted_payoff_proof() -> AcceptedThreadPayoffProof:
    """Structurally valid — right thread, payoff, change set, and covered span — but its
    decisions were never accepted, so outcome validation must still refuse it."""
    return accepted_payoff_proof()


# --- the two halves of the no-POV AUTHOR_DRAFT gate -----------------------------


def omniscient_scene(*, scene_id: str = "scene-omni") -> SceneContractV2:
    """Passes the SceneContract half: v2, ``pov is None``, scene flag set. Overall
    admission still fails — this build carries no typed CreativePolicy capability."""
    return _gate_scene(scene_id=scene_id, omniscient=True)


def denied_scene(*, scene_id: str = "scene-omni-denied") -> SceneContractV2:
    """Otherwise identical, with the scene flag cleared: denied by the SceneContract half."""
    return _gate_scene(scene_id=scene_id, omniscient=False)


def gate_plan(scene: SceneContractV2) -> NarrativePlan:
    content = NarrativePlanContentV2(
        canon_basis=CanonBasis(branch_id=BRANCH, canon_version_id=CANON_VERSION),
        story_frame="the omniscient draft",
        scene_contracts=[scene],
    )
    return NarrativePlan(
        plan_id=PLAN_ID,
        version=1,
        content=content,
        content_hash=compute_plan_content_hash_v2(content),
        content_hash_version="r2-narrative-plan-content-v2",
        committed_at=C0,
        committed_by="lead",
        approval_ref="m5c-gate-approval",
    )


def _gate_scene(*, scene_id: str, omniscient: bool) -> SceneContractV2:
    return _sealed_v2(
        SceneContractV2(
            scene_contract_id=scene_id,
            version=1,
            semantic_hash="sh:placeholder",
            sequence_index=0,
            purpose="the wide shot",
            pov=None,
            location_ref=None,
            temporal_window=SceneTemporalWindow(effective_from=C1, effective_until=C2),
            omniscient_authoring_allowed_by_scene=omniscient,
        )
    )


# --- R9 / R10 regression scenes -------------------------------------------------


def r9_unresolved_present_ref_scene(*, scene_id: str = "scene-r9") -> SceneContractV2:
    """An entry Fact constraint whose subject is absent from the exact plan Canon basis.
    R9 treats it as an unresolved present-state reference, never as a normal unmet
    comparison that a later Canon state could satisfy."""
    return _sealed_v2(
        SceneContractV2(
            scene_contract_id=scene_id,
            version=1,
            semantic_hash="sh:placeholder",
            sequence_index=0,
            purpose="the ghost reference",
            pov=None,
            location_ref=None,
            temporal_window=SceneTemporalWindow(effective_from=C1, effective_until=C2),
            entry_state_constraints=[
                SceneFactConstraint(
                    constraint_id="c-ghost", subject_ref="char-does-not-exist", predicate="mood", comparison="PRESENT"
                )
            ],
        )
    )


def r10_duplicate_constraint_id_scene(*, scene_id: str = "scene-r10-id") -> SceneContractV2:
    """One constraint id reused across two different lists in one scene."""
    return _sealed_v2(
        SceneContractV2(
            scene_contract_id=scene_id,
            version=1,
            semantic_hash="sh:placeholder",
            sequence_index=0,
            purpose="the reused id",
            pov=None,
            location_ref=None,
            temporal_window=SceneTemporalWindow(effective_from=C1, effective_until=C2),
            entry_state_constraints=[
                SceneFactConstraint(constraint_id="c-dup", subject_ref=HERO, predicate="mood", comparison="ABSENT")
            ],
            exit_state_targets=[
                SceneFactConstraint(constraint_id="c-dup", subject_ref=HERO, predicate="rank", comparison="ABSENT")
            ],
        )
    )


def r10_duplicate_semantic_scene(*, scene_id: str = "scene-r10-semantic") -> SceneContractV2:
    """The same normalized constraint carried twice in one list under two ids."""
    return _sealed_v2(
        SceneContractV2(
            scene_contract_id=scene_id,
            version=1,
            semantic_hash="sh:placeholder",
            sequence_index=0,
            purpose="the duplicated semantic",
            pov=None,
            location_ref=None,
            temporal_window=SceneTemporalWindow(effective_from=C1, effective_until=C2),
            entry_state_constraints=[
                SceneFactConstraint(constraint_id="c-a", subject_ref=HERO, predicate="mood", comparison="ABSENT"),
                SceneFactConstraint(constraint_id="c-b", subject_ref=HERO, predicate="mood", comparison="ABSENT"),
            ],
        )
    )


def clean_v2_scene(*, scene_id: str = "scene-clean") -> SceneContractV2:
    """The R9/R10 control: same shape, no unresolved ref and no duplicate."""
    return _sealed_v2(
        SceneContractV2(
            scene_contract_id=scene_id,
            version=1,
            semantic_hash="sh:placeholder",
            sequence_index=0,
            purpose="the clean scene",
            pov=None,
            location_ref=None,
            temporal_window=SceneTemporalWindow(effective_from=C1, effective_until=C2),
            entry_state_constraints=[
                SceneFactConstraint(constraint_id="c-ok", subject_ref=HERO, predicate="mood", comparison="ABSENT")
            ],
        )
    )


def scene_plan(scene: SceneContractV2) -> NarrativePlan:
    """A minimal v2 plan whose Canon basis is the corpus Canon, for driving one scene
    through ``NarrativeInvariantValidator.validate_scene``."""
    content = NarrativePlanContentV2(
        canon_basis=CanonBasis(branch_id=BRANCH, canon_version_id=CANON_VERSION),
        story_frame="one scene",
        scene_contracts=[scene],
    )
    return NarrativePlan(
        plan_id=PLAN_ID,
        version=1,
        content=content,
        content_hash=compute_plan_content_hash_v2(content),
        content_hash_version="r2-narrative-plan-content-v2",
        committed_at=C0,
        committed_by="lead",
        approval_ref="m5c-scene-approval",
    )


# --- exact pure-compiler inputs -------------------------------------------------

COMPILER_BASE = ExactCanonBase(
    canon_branch_id="branch-1", base_canon_version_id="cv-1", content_schema_version=CANON_SCHEMA_V1
)


def _rule(subject: str, descriptor: str, fact_id: str, value: str) -> CanonMutationRule:
    return CanonMutationRule(
        canon_subject_kind="FACT",
        subject_ref=subject,
        effect_descriptor=descriptor,
        operations=(
            AddFactOperation(
                operation_id="template",
                target_id=fact_id,
                fact=Fact(fact_id=fact_id, subject_ref=subject, predicate=descriptor, value=value),
            ),
        ),
    )


def compiler_policy() -> CompilerPolicy:
    return CompilerPolicy(
        policy_ref="policy-1",
        policy_version=COMPILER_POLICY_VERSION,
        collision_policy="SAME_SUBJECT",
        mutation_rules=(
            _rule("hero", "trust", "fact-trust", "high"),
            _rule("hero", "mood", "fact-mood", "calm"),
            _rule("villain", "fear", "fact-fear", "rising"),
        ),
        replacement_rules=(
            ReplacementEffectRule(
                replacement_ref="merged-mood",
                effect_keys=(
                    make_canon_mutation_effect_key(
                        canon_subject_kind="FACT", subject_ref="hero", effect_descriptor="mood"
                    ),
                ),
            ),
        ),
    )


def compiler_change_set(
    change_set_id: str,
    *,
    subject_ref: str = "hero",
    effect_descriptor: str = "trust",
    span: tuple[int, int] = (0, 4),
) -> NarrativeChangeSet:
    return make_narrative_change_set(
        change_set_id=change_set_id,
        key=make_canon_mutation_effect_key(
            canon_subject_kind="FACT", subject_ref=subject_ref, effect_descriptor=effect_descriptor
        ),
        span=SourceSpan(start=span[0], end=span[1]),
    )


def reviewed(change_set: NarrativeChangeSet, review_decision_id: str) -> ReviewedChangeSet:
    return ReviewedChangeSet(change_set=change_set, review_decision_id=review_decision_id)


def compiler_revision():
    return make_narrative_revision()


def compiler_identity(
    reviewed_change_sets: list[ReviewedChangeSet],
    resolutions: list[ConflictResolutionCommand] | None = None,
    **attempt_overrides: object,
) -> CompilationOutputIdentity:
    arguments: dict[str, object] = {
        "work_scope": make_narrative_work_scope(user_id=USER, project_name=PROJECT),
        "selected_change_sets": tuple(
            CompilationSelectedChangeSet(
                change_set_id=item.change_set.change_set_id, review_decision_id=item.review_decision_id
            )
            for item in reviewed_change_sets
        ),
        "conflict_resolution_decision_ids": tuple(sorted(item.decision_id for item in (resolutions or []))),
        "compiler_version": COMPILER_VERSION,
        "creative_policy_ref": "policy-1",
        "creative_policy_version": COMPILER_POLICY_VERSION,
    }
    arguments.update(attempt_overrides)
    return CompilationOutputIdentity.from_attempt(make_compilation_attempt(**arguments))


def resolution_instruction(kind: str, argument: str) -> str:
    return f"{RESOLUTION_INSTRUCTION_VERSION}:{kind}:{argument}"


def human_keep_resolution(*, decision_id: str = "d-4", keep: str = "cs-a") -> ConflictResolutionCommand:
    """One overlap resolved explicitly by a Human resolution lineage, in the exact
    versioned instruction grammar the compiler parses."""
    return make_conflict_resolution_command(
        decision_id=decision_id,
        work_scope=make_narrative_work_scope(user_id=USER, project_name=PROJECT),
        revision_acceptance_decision_id="d-1",
        conflict_resolution_lineage_id="lin-conflict-1",
        competing_change_set_ids=("cs-a", "cs-b"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=resolution_instruction("KEEP", keep),
    )


def overlapping_reviewed_change_sets() -> list[ReviewedChangeSet]:
    """``cs-a`` and ``cs-b`` collide on the same subject at the same span — an overlap the
    compiler refuses to resolve from prose."""
    return [
        reviewed(compiler_change_set("cs-a", effect_descriptor="trust"), "d-2"),
        reviewed(compiler_change_set("cs-b", effect_descriptor="mood"), "d-3"),
    ]


def non_overlapping_reviewed_change_sets() -> list[ReviewedChangeSet]:
    """One accepted revision producing multiple non-overlapping change-set lineages."""
    return [
        reviewed(compiler_change_set("cs-1", effect_descriptor="trust", span=(0, 4)), "d-2"),
        reviewed(compiler_change_set("cs-2", subject_ref="villain", effect_descriptor="fear", span=(10, 14)), "d-3"),
    ]


def outcome_only_reviewed_change_sets() -> list[ReviewedChangeSet]:
    """A complete valid selection that declares no Canon-mutation effect at all."""
    return [reviewed(payoff_change_set(change_set_id="cs-outcome-only"), "d-2")]


# --- helpers --------------------------------------------------------------------


def _sealed_v2(scene: SceneContractV2) -> SceneContractV2:
    return scene.model_copy(update={"semantic_hash": compute_scene_semantic_hash_v2(scene)})


# --- the aggregated corpus ------------------------------------------------------


class M5CFullCorpus(TypedDict):
    m5b_v1: FullCorpus
    canon: ResolvedCanonView
    mixed_plan: NarrativePlan
    relationship_scene: SceneContractV2
    thread_plan_content: NarrativePlanContentV2
    accepted_payoff_proof: AcceptedThreadPayoffProof
    payoff_change_set: NarrativeChangeSet
    omniscient_scene: SceneContractV2
    denied_scene: SceneContractV2
    r9_scene: SceneContractV2
    r10_duplicate_id_scene: SceneContractV2
    r10_duplicate_semantic_scene: SceneContractV2
    compiler_policy: CompilerPolicy


def full_corpus() -> M5CFullCorpus:
    """Everything Section 16.9 requires, in one value. Deterministic: two calls compare
    equal field by field."""
    return {
        "m5b_v1": m5b_v1_corpus(),
        "canon": corpus_canon(),
        "mixed_plan": mixed_version_plan(),
        "relationship_scene": relationship_scene(),
        "thread_plan_content": thread_plan_content(),
        "accepted_payoff_proof": accepted_payoff_proof(),
        "payoff_change_set": payoff_change_set(),
        "omniscient_scene": omniscient_scene(),
        "denied_scene": denied_scene(),
        "r9_scene": r9_unresolved_present_ref_scene(),
        "r10_duplicate_id_scene": r10_duplicate_constraint_id_scene(),
        "r10_duplicate_semantic_scene": r10_duplicate_semantic_scene(),
        "compiler_policy": compiler_policy(),
    }


__all__ = [
    "BRANCH",
    "C0",
    "C1",
    "C2",
    "C3",
    "C4",
    "CANON_VERSION",
    "COMPILER_BASE",
    "HERO",
    "MENTOR",
    "PAYOFF",
    "PAYOFF_SPAN",
    "PLAN_ID",
    "PROJECT",
    "RIVAL",
    "THREAD",
    "TRUST",
    "TRUST_STATE",
    "USER",
    "M5CFullCorpus",
    "accepted_payoff_decisions",
    "accepted_payoff_proof",
    "clean_v2_scene",
    "compiler_change_set",
    "compiler_identity",
    "compiler_policy",
    "compiler_revision",
    "corpus_canon",
    "corpus_canon_content",
    "denied_scene",
    "entry_relationship_constraint",
    "exit_relationship_constraint",
    "full_corpus",
    "gate_plan",
    "human_keep_resolution",
    "m5b_v1_corpus",
    "mixed_version_plan",
    "mixed_version_plan_content",
    "non_overlapping_reviewed_change_sets",
    "omniscient_scene",
    "outcome_only_reviewed_change_sets",
    "overlapping_reviewed_change_sets",
    "payoff_change_set",
    "r9_unresolved_present_ref_scene",
    "r10_duplicate_constraint_id_scene",
    "r10_duplicate_semantic_scene",
    "relationship_constraint",
    "relationship_predicate",
    "relationship_scene",
    "resolution_instruction",
    "reviewed",
    "scene_plan",
    "story_time_ordered_plan_content",
    "thread_plan_content",
    "thread_resolved_before_open_plan_content",
    "thread_scene",
    "unaccepted_payoff_proof",
    "unchanged_v1_scene",
    "upgraded_v2_scene",
]
