from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from r2.contracts import (
    ContextDescriptorBasis,
    DescriptorAuthorityClass,
    DescriptorVisibilityPolicy,
    NarrativeContextRequest,
    NarrativeSourceDescriptor,
    RetrievalCandidate,
    RetrievalSnapshot,
    SelectionTrace,
    compute_descriptor_ref,
    compute_source_content_hash,
)

NOW = datetime(2026, 3, 1, 10, tzinfo=UTC)
LATER = datetime(2026, 3, 1, 12, tzinfo=UTC)


def descriptor(
    *,
    authority_class: str = "RETRIEVED_REFERENCE",
    visibility_policy: str = "AUTHOR_ONLY",
    visibility_subjects: list[str] | None = None,
    proposition_refs: list[str] | None = None,
    visibility_knowledge_state_refs: list[str] | None = None,
    canon_basis: ContextDescriptorBasis | None = None,
    plan_basis: ContextDescriptorBasis | None = None,
    effective_from: datetime | None = None,
    effective_until: datetime | None = None,
    source_ref: str = "src-1",
) -> NarrativeSourceDescriptor:
    fields: dict[str, object] = {
        "descriptor_ref": "nsd:placeholder",
        "source_ref": source_ref,
        "user_id": "u1",
        "project_name": "proj",
        "authority_class": DescriptorAuthorityClass(authority_class),
        "source_basis_refs": ["basis-1"],
        "canon_basis": canon_basis,
        "plan_basis": plan_basis,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "visibility_policy": DescriptorVisibilityPolicy(visibility_policy),
        "proposition_refs": sorted(set(proposition_refs or [])),
        "visibility_subjects": sorted(set(visibility_subjects or [])),
        "visibility_knowledge_state_refs": sorted(set(visibility_knowledge_state_refs or [])),
        "content_hash": compute_source_content_hash("prose"),
    }
    draft = NarrativeSourceDescriptor.model_construct(**fields)
    fields["descriptor_ref"] = compute_descriptor_ref(draft)
    return NarrativeSourceDescriptor.model_validate(fields)


def _canon_basis() -> ContextDescriptorBasis:
    return ContextDescriptorBasis(branch_id="main", canon_version_id="canon-v1")


def _plan_basis() -> ContextDescriptorBasis:
    return ContextDescriptorBasis(plan_id="plan-1", plan_version=1)


def test_author_only_descriptor_round_trips_and_forbids_subject_claims() -> None:
    author = descriptor(visibility_policy="AUTHOR_ONLY")
    assert author.descriptor_ref.startswith("nsd:")
    with pytest.raises(ValidationError):
        descriptor(visibility_policy="AUTHOR_ONLY", visibility_subjects=["char-a"])


def test_subject_visibility_requires_explicit_exact_basis_and_proofs() -> None:
    with pytest.raises(ValidationError):
        descriptor(
            visibility_policy="SUBJECTS",
            visibility_subjects=["char-a"],
            proposition_refs=[],
            canon_basis=_canon_basis(),
        )
    with pytest.raises(ValidationError):
        descriptor(
            visibility_policy="SUBJECTS",
            visibility_subjects=["char-a"],
            proposition_refs=["ep:x"],
            visibility_knowledge_state_refs=["k-1"],
            canon_basis=None,
        )
    ok = descriptor(
        visibility_policy="SUBJECTS",
        visibility_subjects=["char-a"],
        proposition_refs=["ep:x"],
        visibility_knowledge_state_refs=["k-1"],
        canon_basis=_canon_basis(),
    )
    assert ok.visibility_policy.value == "SUBJECTS"


def test_accepted_narrative_and_summary_require_both_exact_bases() -> None:
    with pytest.raises(ValidationError):
        descriptor(authority_class="ACCEPTED_NARRATIVE", canon_basis=_canon_basis())
    ok = descriptor(authority_class="SUMMARY", canon_basis=_canon_basis(), plan_basis=_plan_basis())
    assert ok.authority_class.value == "SUMMARY"


def test_descriptor_ref_and_interval_are_validated() -> None:
    good = descriptor()
    with pytest.raises(ValidationError):
        NarrativeSourceDescriptor.model_validate({**good.model_dump(mode="json"), "descriptor_ref": "nsd:tampered"})
    with pytest.raises(ValidationError):
        descriptor(effective_from=LATER, effective_until=NOW)


def test_descriptor_refs_are_sorted_and_duplicate_free() -> None:
    made = descriptor(
        visibility_policy="SUBJECTS",
        visibility_subjects=["char-b", "char-a", "char-b"],
        proposition_refs=["ep:2", "ep:1"],
        visibility_knowledge_state_refs=["k-2", "k-1"],
        canon_basis=_canon_basis(),
    )
    assert made.visibility_subjects == ["char-a", "char-b"]
    assert made.proposition_refs == ["ep:1", "ep:2"]


def test_retrieval_snapshot_holds_inline_descriptors() -> None:
    snapshot = RetrievalSnapshot(
        snapshot_ref="snap-1",
        user_id="u1",
        project_name="proj",
        query_fingerprint="qf",
        candidates=[RetrievalCandidate(candidate_id="c-1", source_descriptor=descriptor(), content="prose", score=0.5)],
        created_at=NOW,
        retriever_version="ret-v1",
    )
    assert snapshot.candidates[0].source_descriptor.descriptor_ref.startswith("nsd:")


def test_context_request_strict_modes_and_positive_budget() -> None:
    base = {
        "user_id": "u1",
        "project_name": "proj",
        "canon_branch_id": "main",
        "canon_version_id": "canon-v1",
        "plan_id": "plan-1",
        "plan_version": 1,
        "scene_contract_id": "scene-1",
        "scene_contract_version": 1,
        "creative_policy_ref": "policy-1",
        "creative_policy_version": "v1",
        "mode": "CHARACTER_SIMULATION",
        "story_time": NOW,
        "token_budget": 100,
        "compiler_version": "compiler-v1",
    }
    with pytest.raises(ValidationError):
        NarrativeContextRequest.model_validate(base)  # simulation without POV
    with pytest.raises(ValidationError):
        NarrativeContextRequest.model_validate({**base, "mode": "AUTHOR_DRAFT", "token_budget": 0})
    ok = NarrativeContextRequest.model_validate({**base, "pov_subject_entity_id": "char-a"})
    assert ok.mode.value == "CHARACTER_SIMULATION"
    with pytest.raises(ValidationError):
        NarrativeContextRequest.model_validate({**base, "pov_subject_entity_id": "char-a", "provider": "openai"})


def test_selection_trace_is_visibility_tiered() -> None:
    with pytest.raises(ValidationError):
        SelectionTrace(
            candidate_id="c-1", source_ref="src-1", status="OMITTED", reason="NOT_VISIBLE", content_hash="nsc:x"
        )
    with pytest.raises(ValidationError):
        SelectionTrace(candidate_id="c-1", source_ref="src-1", status="INCLUDED", reason="BUDGET")
    duplicate = SelectionTrace(
        candidate_id="c-1",
        source_ref="src-1",
        status="OMITTED",
        reason="DUPLICATE",
        content_hash="nsc:x",
        token_count=3,
    )
    assert duplicate.token_count == 3
