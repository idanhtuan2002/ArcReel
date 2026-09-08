"""Versioned M5B acceptance corpus, built through the real public contracts.

A compact story slice that still carries every phenomenon the required adversarial
mutations exercise: hidden-identity and object-ownership propositions, an injury
(knowledge supersession), an unperceived reveal Event, a presentation-order time
jump, a temporal relation, and an author-only secret retrieval candidate. All
instants, ids, hashes, and token counts are fixed.
"""

from __future__ import annotations

from datetime import UTC, datetime

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


def _proposition(ref: str, subject: str, predicate: str, value: object) -> EpistemicProposition:
    return EpistemicProposition(proposition_ref=ref, subject_ref=subject, predicate=predicate, object_or_value=value)


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
    *, scenes: list[SceneContract] | None = None, canon_version_id: str = "canon-v1"
) -> NarrativePlanContent:
    return NarrativePlanContent(
        canon_basis=CanonBasis(branch_id="main", canon_version_id=canon_version_id),
        story_frame="the heir returns",
        scene_contracts=scenes or [entry_scene()],
    )


def proposal(
    *, revision: str = "rev-1", expected_version: int | None = None, content: NarrativePlanContent | None = None
) -> NarrativePlanRevisionProposal:
    content = content or plan_content()
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
    "add_relation_delta",
    "approval",
    "base_canon_content",
    "entry_scene",
    "known_delta",
    "plan_content",
    "proposal",
    "retrieval_snapshot",
    "secret_descriptor",
    "v2_canon_view",
    "visible_descriptor",
]
