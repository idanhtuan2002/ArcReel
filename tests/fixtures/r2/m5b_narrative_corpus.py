"""Versioned M5B acceptance corpus, built through the real public contracts.

A compact story slice that still carries every phenomenon the required adversarial
mutations exercise: hidden-identity and object-ownership propositions, an injury
(knowledge supersession), an unperceived reveal Event, a presentation-order time
jump, a temporal relation, and an author-only secret retrieval candidate. All
instants, ids, hashes, and token counts are fixed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from r2.contracts import (
    AddEventOperation,
    AddFactOperation,
    CanonBasis,
    CanonContent,
    CanonDelta,
    CanonDeltaPayload,
    CanonOperation,
    ContextDescriptorBasis,
    DescriptorAuthorityClass,
    DescriptorVisibilityPolicy,
    Entity,
    EntityType,
    EpistemicProposition,
    EpistemicState,
    Event,
    Fact,
    KnowledgeState,
    NarrativePlan,
    NarrativePlanApproval,
    NarrativePlanContent,
    NarrativePlanRevisionProposal,
    NarrativeSourceDescriptor,
    RetrievalCandidate,
    RetrievalSnapshot,
    SceneContract,
    SceneFactConstraint,
    SceneTemporalWindow,
    UpdateKnowledgeOperation,
    compute_descriptor_ref,
    compute_epistemic_proposition_ref,
    compute_source_content_hash,
)
from r2.narrative.canon_state import ResolvedCanonView
from r2.narrative.hashing import compute_canon_content_hash, seal_canon_delta
from r2.narrative_plan.hashing import compute_plan_content_hash, compute_scene_semantic_hash

T0 = datetime(2026, 3, 1, 8, tzinfo=UTC)
T1 = datetime(2026, 3, 1, 10, tzinfo=UTC)
T2 = datetime(2026, 3, 1, 12, tzinfo=UTC)
T3 = datetime(2026, 3, 1, 14, tzinfo=UTC)

RING_OWNER = compute_epistemic_proposition_ref(subject_ref="obj-ring", predicate="owner", object_or_value="char-b")
IDENTITY = compute_epistemic_proposition_ref(subject_ref="char-x", predicate="true_name", object_or_value="the-heir")

USER = "u1"
PROJECT = "project-a"


def make_proposition(ref: str, subject: str, predicate: str, value: object) -> EpistemicProposition:
    return EpistemicProposition(proposition_ref=ref, subject_ref=subject, predicate=predicate, object_or_value=value)


_proposition = make_proposition


def base_canon_content() -> CanonContent:
    return CanonContent(
        entities_by_id={
            "char-a": Entity(entity_id="char-a", entity_type=EntityType.CHARACTER, canonical_name="Ada"),
            "char-b": Entity(entity_id="char-b", entity_type=EntityType.CHARACTER, canonical_name="Bram"),
            "char-x": Entity(entity_id="char-x", entity_type=EntityType.CHARACTER, canonical_name="The Stranger"),
            "obj-ring": Entity(entity_id="obj-ring", entity_type=EntityType.OBJECT, canonical_name="Signet Ring"),
            "loc-hall": Entity(entity_id="loc-hall", entity_type=EntityType.LOCATION, canonical_name="Great Hall"),
        },
        facts_by_id={
            "fact-owner": Fact(
                fact_id="fact-owner", subject_ref="obj-ring", predicate="owner", value="char-b", effective_from=T0
            ),
        },
        events_by_id={
            "ev-seen": Event(event_id="ev-seen", event_type="SIGHT", participant_refs=["char-a"], temporal_anchor=T0),
        },
        epistemic_propositions_by_ref={},
        knowledge_states_by_id={},
        temporal_relations_by_id={},
    )


def v2_canon_view(*, version_id: str = "canon-v1", content: CanonContent | None = None) -> ResolvedCanonView:
    content = content or base_canon_content()
    return ResolvedCanonView(
        canon_version_id=version_id,
        branch_id="main",
        content_hash=compute_canon_content_hash(content, schema_version="r2-canon-schema-v2"),
        content_schema_version="r2-canon-schema-v2",
        content=content,
    )


def known_delta(**overrides: object) -> tuple[ResolvedCanonView, CanonDelta, ResolvedCanonView]:
    """A v2 delta where char-a comes to KNOW that the ring belongs to char-b."""
    base = v2_canon_view()
    proposition = _proposition(RING_OWNER, "obj-ring", "owner", "char-b")
    op_kwargs: dict[str, object] = {
        "operation_id": "op-k-1",
        "target_id": "k-1",
        "subject_entity_id": "char-a",
        "proposition": proposition,
        "epistemic_state": EpistemicState.KNOWN,
        "effective_from": T1,
        "evidence_event_refs": ["ev-seen"],
    }
    op_kwargs.update(overrides)
    operation = UpdateKnowledgeOperation(**op_kwargs)
    delta = _seal_v2("delta-know", [operation], author_decision_refs=["a-1"])
    candidate_content = base.content.model_copy(
        update={
            "epistemic_propositions_by_ref": {RING_OWNER: proposition},
            "knowledge_states_by_id": {
                "k-1": KnowledgeState(
                    knowledge_state_id="k-1",
                    subject_entity_id="char-a",
                    proposition_ref=RING_OWNER,
                    epistemic_state=EpistemicState.KNOWN,
                    effective_from=T1,
                    effective_until=operation.effective_until,
                    evidence_event_refs=list(operation.evidence_event_refs),
                )
            },
        }
    )
    return base, delta, v2_canon_view(version_id="canon-v2", content=candidate_content)


def _seal_v2(delta_id: str, operations: list[CanonOperation], *, author_decision_refs: list[str]) -> CanonDelta:
    return seal_canon_delta(
        CanonDeltaPayload(
            canon_delta_id=delta_id,
            target_branch_id="main",
            base_canon_version_id=None,
            operations=operations,
            source_change_set_refs=["s-1"],
            author_decision_refs=author_decision_refs,
            validation_report_refs=[],
            content_schema_version="r2-canon-schema-v2",
            created_at=T0,
            created_by="showrunner",
        )
    )


def entry_scene(*, comparison: str = "EQUALS", value: object = "char-b") -> SceneContract:
    draft = SceneContract(
        scene_contract_id="scene-1",
        version=1,
        semantic_hash="sh:x",
        sequence_index=0,
        purpose="the confrontation",
        pov=None,
        location_ref="loc-hall",
        temporal_window=SceneTemporalWindow(effective_from=T1, effective_until=T2),
        entry_state_constraints=[
            SceneFactConstraint(
                constraint_id="c-1",
                subject_ref="obj-ring",
                predicate="owner",
                comparison=comparison,
                expected_value=value,
            )
        ],
    )
    return draft.model_copy(update={"semantic_hash": compute_scene_semantic_hash(draft)})


def plan_content(
    *,
    scenes: list[SceneContract] | None = None,
    canon_version_id: str = "canon-v1",
    parent_version: int | None = None,
) -> NarrativePlanContent:
    return NarrativePlanContent(
        parent_version=parent_version,
        canon_basis=CanonBasis(branch_id="main", canon_version_id=canon_version_id),
        story_frame="the heir returns",
        scene_contracts=scenes or [entry_scene()],
    )


def proposal(
    *, revision: str = "rev-1", expected_version: int | None = None, content: NarrativePlanContent | None = None
) -> NarrativePlanRevisionProposal:
    content = content or plan_content(parent_version=expected_version)
    return NarrativePlanRevisionProposal(
        plan_revision_id=revision,
        plan_id="plan-1",
        expected_version=expected_version,
        proposed_content=content,
        content_hash=compute_plan_content_hash(content),
        created_at=T0,
        created_by="lead",
    )


def approval(prop: NarrativePlanRevisionProposal, *, approval_ref: str = "ap-1") -> NarrativePlanApproval:
    return NarrativePlanApproval(
        approval_ref=approval_ref,
        plan_revision_id=prop.plan_revision_id,
        plan_id=prop.plan_id,
        expected_version=prop.expected_version,
        content_hash=prop.content_hash,
        project_name=PROJECT,
        user_id=USER,
        approved_by="approver",
        approved_at=T0,
    )


def secret_descriptor(
    *, source_ref: str = "secret", prose: str = "char-x is the lost heir"
) -> NarrativeSourceDescriptor:
    fields: dict[str, object] = {
        "descriptor_ref": "nsd:placeholder",
        "source_ref": source_ref,
        "user_id": USER,
        "project_name": PROJECT,
        "authority_class": DescriptorAuthorityClass.RETRIEVED_REFERENCE,
        "source_basis_refs": ["basis-1"],
        "canon_basis": None,
        "plan_basis": None,
        "effective_from": None,
        "effective_until": None,
        "visibility_policy": DescriptorVisibilityPolicy.AUTHOR_ONLY,
        "proposition_refs": [],
        "visibility_subjects": [],
        "visibility_knowledge_state_refs": [],
        "content_hash": compute_source_content_hash(prose),
    }
    draft = NarrativeSourceDescriptor.model_construct(**fields)
    fields["descriptor_ref"] = compute_descriptor_ref(draft)
    return NarrativeSourceDescriptor.model_validate(fields)


def visible_descriptor(
    *, source_ref: str = "visible", prose: str = "ada knows the ring", ks_ref: str = "k-1"
) -> NarrativeSourceDescriptor:
    fields: dict[str, object] = {
        "descriptor_ref": "nsd:placeholder",
        "source_ref": source_ref,
        "user_id": USER,
        "project_name": PROJECT,
        "authority_class": DescriptorAuthorityClass.RETRIEVED_REFERENCE,
        "source_basis_refs": ["basis-1"],
        "canon_basis": ContextDescriptorBasis(branch_id="main", canon_version_id="canon-v1"),
        "plan_basis": None,
        "effective_from": None,
        "effective_until": None,
        "visibility_policy": DescriptorVisibilityPolicy.SUBJECTS,
        "proposition_refs": [RING_OWNER],
        "visibility_subjects": ["char-a"],
        "visibility_knowledge_state_refs": [ks_ref],
        "content_hash": compute_source_content_hash(prose),
    }
    draft = NarrativeSourceDescriptor.model_construct(**fields)
    fields["descriptor_ref"] = compute_descriptor_ref(draft)
    return NarrativeSourceDescriptor.model_validate(fields)


def retrieval_snapshot(*descriptors_and_prose: tuple[NarrativeSourceDescriptor, str]) -> RetrievalSnapshot:
    return RetrievalSnapshot(
        snapshot_ref="snap-1",
        user_id=USER,
        project_name=PROJECT,
        query_fingerprint="qf",
        candidates=[
            RetrievalCandidate(
                candidate_id=descriptor.source_ref, source_descriptor=descriptor, content=prose, score=float(index)
            )
            for index, (descriptor, prose) in enumerate(descriptors_and_prose)
        ],
        created_at=T0,
        retriever_version="ret-v1",
    )


def add_relation_delta(relation_id: str, left: str, right: str) -> CanonDelta:
    from r2.contracts import AddTemporalRelationOperation, TemporalRelation

    relation = TemporalRelation(
        temporal_relation_id=relation_id, left_event_ref=left, relation="BEFORE", right_event_ref=right
    )
    return _seal_v2(
        f"delta-{relation_id}",
        [
            AddTemporalRelationOperation(
                operation_id=f"op-{relation_id}", target_id=relation_id, temporal_relation=relation
            )
        ],
        author_decision_refs=["a-1"],
    )


# --- Full acceptance corpus (spec Section 14.5) --------------------------------
#
# 30 SceneContracts, 8 CHARACTER + 3 LOCATION entities, 2 hidden-identity
# propositions, 2 false beliefs, an injury transition, an object ownership/state
# transition, a presentation-order time jump (scenes 10 and 11 are authored in one
# order but occur in story time in the opposite order), an unperceived reveal
# Event, a BEFORE temporal relation, and an author-only secret retrieval candidate.
# Every instant, id, hash, and token count is fixed.

_HEIR = compute_epistemic_proposition_ref(subject_ref="char-7", predicate="true_name", object_or_value="the-heir")
_SPY = compute_epistemic_proposition_ref(subject_ref="char-8", predicate="true_name", object_or_value="the-spy")
_CROWN_OWNER_1 = compute_epistemic_proposition_ref(subject_ref="obj-crown", predicate="owner", object_or_value="char-1")
_CY = datetime(2026, 3, 1, tzinfo=UTC)


def _t(hour: int) -> datetime:
    return _CY.replace(hour=hour)


class FullCorpus(TypedDict):
    canon: ResolvedCanonView
    plan: NarrativePlan
    scenes: list[SceneContract]
    snapshot: RetrievalSnapshot
    story_time: datetime


def full_corpus() -> FullCorpus:
    entities: dict[str, Entity] = {
        f"char-{i}": Entity(entity_id=f"char-{i}", entity_type=EntityType.CHARACTER, canonical_name=f"Character {i}")
        for i in range(1, 9)
    }
    entities.update(
        {
            f"loc-{i}": Entity(entity_id=f"loc-{i}", entity_type=EntityType.LOCATION, canonical_name=f"Location {i}")
            for i in range(1, 4)
        }
    )
    entities["obj-crown"] = Entity(entity_id="obj-crown", entity_type=EntityType.OBJECT, canonical_name="The Crown")

    events = {
        "ev-fight": Event(event_id="ev-fight", event_type="FIGHT", participant_refs=["char-3"], temporal_anchor=_t(9)),
        "ev-handover": Event(
            event_id="ev-handover", event_type="HANDOVER", participant_refs=["char-1", "char-2"], temporal_anchor=_t(12)
        ),
        "ev-reveal": Event(
            event_id="ev-reveal", event_type="REVEAL", participant_refs=["char-7"], temporal_anchor=_t(13)
        ),
        "ev-witness": Event(
            event_id="ev-witness", event_type="SIGHT", participant_refs=["char-6"], temporal_anchor=_t(8)
        ),
    }
    facts = {
        "fact-crown-1": Fact(
            fact_id="fact-crown-1",
            subject_ref="obj-crown",
            predicate="owner",
            value="char-1",
            effective_from=_t(6),
            effective_until=_t(12),
        ),
        "fact-crown-2": Fact(
            fact_id="fact-crown-2",
            subject_ref="obj-crown",
            predicate="owner",
            value="char-2",
            effective_from=_t(12),
            effective_until=None,
            source_event_refs=["ev-handover"],
        ),
        "fact-injury-1": Fact(
            fact_id="fact-injury-1",
            subject_ref="char-3",
            predicate="condition",
            value="healthy",
            effective_from=_t(6),
            effective_until=_t(9),
        ),
        "fact-injury-2": Fact(
            fact_id="fact-injury-2",
            subject_ref="char-3",
            predicate="condition",
            value="injured",
            effective_from=_t(9),
            effective_until=None,
            source_event_refs=["ev-fight"],
        ),
        "fact-heir": Fact(
            fact_id="fact-heir",
            subject_ref="char-7",
            predicate="true_name",
            value="the-heir",
            effective_from=_t(6),
            effective_until=None,
        ),
        "fact-spy": Fact(
            fact_id="fact-spy",
            subject_ref="char-8",
            predicate="true_name",
            value="an-imposter",
            effective_from=_t(6),
            effective_until=None,
        ),
    }
    propositions = {
        ref: make_proposition(ref, subject, "true_name", value)
        for ref, subject, value in (
            (_HEIR, "char-7", "the-heir"),
            (_SPY, "char-8", "the-spy"),
        )
    }
    propositions[_CROWN_OWNER_1] = make_proposition(_CROWN_OWNER_1, "obj-crown", "owner", "char-1")

    knowledge_states = {
        # char-6 KNOWS the heir's identity from a witnessed event (historical evidence).
        "ks-6-heir": KnowledgeState(
            knowledge_state_id="ks-6-heir",
            subject_entity_id="char-6",
            proposition_ref=_HEIR,
            epistemic_state=EpistemicState.KNOWN,
            effective_from=_t(8),
            evidence_event_refs=["ev-witness"],
        ),
        # false belief 1: char-4 believes char-8 is the spy while the Fact says imposter.
        "ks-4-spy": KnowledgeState(
            knowledge_state_id="ks-4-spy",
            subject_entity_id="char-4",
            proposition_ref=_SPY,
            epistemic_state=EpistemicState.FALSE_BELIEF,
            effective_from=_t(7),
            evidence_event_refs=["ev-witness"],
        ),
        # false belief 2: char-5 still believes char-1 owns the crown after the handover.
        "ks-5-crown": KnowledgeState(
            knowledge_state_id="ks-5-crown",
            subject_entity_id="char-5",
            proposition_ref=_CROWN_OWNER_1,
            epistemic_state=EpistemicState.FALSE_BELIEF,
            effective_from=_t(12),
            evidence_event_refs=["ev-witness"],
        ),
    }
    relations = {
        "rel-fight-handover": add_relation_delta("rel-fight-handover", "ev-fight", "ev-handover")
        .operations[0]
        .temporal_relation
    }

    content = CanonContent(
        entities_by_id=entities,
        facts_by_id=facts,
        events_by_id=events,
        epistemic_propositions_by_ref=propositions,
        knowledge_states_by_id=knowledge_states,
        temporal_relations_by_id=relations,
    )
    canon = ResolvedCanonView(
        canon_version_id="corpus-canon-1",
        branch_id="main",
        content_hash=compute_canon_content_hash(content, schema_version="r2-canon-schema-v2"),
        content_schema_version="r2-canon-schema-v2",
        content=content,
    )

    scenes: list[SceneContract] = []
    for index in range(30):
        # scene-1 is the compiled entry scene; its window brackets story_time _t(9).
        # Presentation-order time jump: scene-11 is authored before scene-12 but occurs
        # one hour later in story time (sequence_index order != temporal_window order).
        if index == 0:
            from_hour, until_hour = 8, 10
        else:
            base_hour = 6 + (index % 12)
            story_hour = base_hour + 1 if index == 10 else base_hour - 1 if index == 11 else base_hour
            from_hour, until_hour = story_hour, story_hour + 1
        draft = SceneContract(
            scene_contract_id=f"scene-{index + 1}",
            version=1,
            semantic_hash="sh:x",
            sequence_index=index,
            purpose=f"beat {index + 1}",
            pov="char-6" if index % 2 == 0 else None,
            location_ref=f"loc-{index % 3 + 1}",
            temporal_window=SceneTemporalWindow(effective_from=_t(from_hour), effective_until=_t(until_hour)),
            participants=[f"char-{index % 8 + 1}"],
            active_threads=[f"thread-{index % 4}"],
            promise_payoff_refs=[f"payoff-{index % 5}"],
        )
        scenes.append(draft.model_copy(update={"semantic_hash": compute_scene_semantic_hash(draft)}))

    plan_content_value = NarrativePlanContent(
        canon_basis=CanonBasis(branch_id="main", canon_version_id="corpus-canon-1"),
        story_frame="the crown changes hands",
        scene_contracts=scenes,
    )
    plan = NarrativePlan(
        plan_id="corpus-plan",
        version=1,
        content=plan_content_value,
        content_hash=compute_plan_content_hash(plan_content_value),
        committed_at=_t(6),
        committed_by="lead",
        approval_ref="corpus-approval",
    )

    author_secret = secret_descriptor(source_ref="corpus-secret", prose="char-8 is really the spy")
    fields: dict[str, object] = {
        "descriptor_ref": "nsd:placeholder",
        "source_ref": "corpus-visible",
        "user_id": USER,
        "project_name": PROJECT,
        "authority_class": DescriptorAuthorityClass.RETRIEVED_REFERENCE,
        "source_basis_refs": ["basis-1"],
        "canon_basis": ContextDescriptorBasis(branch_id="main", canon_version_id="corpus-canon-1"),
        "plan_basis": None,
        "effective_from": None,
        "effective_until": None,
        "visibility_policy": DescriptorVisibilityPolicy.SUBJECTS,
        "proposition_refs": [_HEIR],
        "visibility_subjects": ["char-6"],
        "visibility_knowledge_state_refs": ["ks-6-heir"],
        "content_hash": compute_source_content_hash("char-6 has learned who the heir is"),
    }
    draft = NarrativeSourceDescriptor.model_construct(**fields)
    fields["descriptor_ref"] = compute_descriptor_ref(draft)
    visible = NarrativeSourceDescriptor.model_validate(fields)
    snapshot = RetrievalSnapshot(
        snapshot_ref="corpus-snap",
        user_id=USER,
        project_name=PROJECT,
        query_fingerprint="corpus-qf",
        candidates=[
            RetrievalCandidate(
                candidate_id="corpus-secret",
                source_descriptor=author_secret,
                content="char-8 is really the spy",
                score=9.0,
            ),
            RetrievalCandidate(
                candidate_id="corpus-visible",
                source_descriptor=visible,
                content="char-6 has learned who the heir is",
                score=1.0,
            ),
        ],
        created_at=_t(6),
        retriever_version="corpus-ret",
    )
    return {
        "canon": canon,
        "plan": plan,
        "scenes": scenes,
        "snapshot": snapshot,
        # Equals scene-1.temporal_window.effective_from (compiler hard requirement) and
        # sits at ks-6-heir.effective_from, so char-6's KNOWN view of the heir is active.
        "story_time": _t(8),
    }


__all__ = [
    "IDENTITY",
    "PROJECT",
    "RING_OWNER",
    "T0",
    "T1",
    "T2",
    "T3",
    "USER",
    "AddEventOperation",
    "AddFactOperation",
    "FullCorpus",
    "add_relation_delta",
    "approval",
    "base_canon_content",
    "entry_scene",
    "full_corpus",
    "known_delta",
    "make_proposition",
    "plan_content",
    "proposal",
    "retrieval_snapshot",
    "secret_descriptor",
    "v2_canon_view",
    "visible_descriptor",
]
