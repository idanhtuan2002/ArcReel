from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from r2.contracts.narrative_lifecycle import (
    CanonMutationEffectKey,
    DraftCandidate,
    ExtractionAttempt,
    ExtractionResult,
    NarrativeChangeItem,
    NarrativeChangeSet,
    NarrativeRevision,
    NarrativeSemanticEffectKey,
    NarrativeWorkScope,
    SourceSpan,
    ThreadPayoffEffectKey,
)
from r2.contracts.provenance import Provenance

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
NAIVE = datetime(2026, 9, 9, 12, 0)
SCOPE = NarrativeWorkScope(
    user_id="u-1", project_name="proj", plan_id="plan-1", scene_contract_id="scene-1", canon_branch_id="branch-1"
)
PROV = Provenance(created_by="AGENT", created_at=NOW)
MUT_KEY = CanonMutationEffectKey(
    canon_subject_kind="FACT", subject_ref="hero", effect_descriptor="r2rel:trust", canon_operation_count=1
)
PAYOFF_KEY = ThreadPayoffEffectKey(thread_ref="t1", payoff_ref="p1")
SPAN = SourceSpan(start=0, end=10)


def _change_set(**overrides: object) -> NarrativeChangeSet:
    base: dict[str, object] = {
        "change_set_id": "cs-1",
        "change_set_lineage_id": "lin-1",
        "source_revision_id": "rev-1",
        "extraction_attempt_id": "att-1",
        "extraction_generation": 0,
        "base_canon_version_id": "cv-1",
        "source_spans": [SPAN],
        "semantic_effect_keys": [MUT_KEY],
        "changes": [NarrativeChangeItem(change_id="ch-1", evidence_span=SPAN, effect_keys=[MUT_KEY], summary="s")],
        "confidence": 0.9,
        "extractor_version": "x-1",
        "policy_ref": "pol",
        "policy_version": "1",
        "created_at": NOW,
        "output_fingerprint": "of-1",
    }
    return NarrativeChangeSet(**(base | overrides))


def _result(**overrides: object) -> ExtractionResult:
    base: dict[str, object] = {
        "result_id": "res-1",
        "attempt_id": "att-1",
        "generation": 0,
        "outcome": "ABSTAINED",
        "change_set_ids": [],
        "diagnostics": [],
        "provider_receipt": None,
        "completed_at": NOW,
        "output_fingerprint": "of",
    }
    return ExtractionResult(**(base | overrides))


def test_effect_key_algebra_is_closed_and_typed() -> None:
    assert PAYOFF_KEY.canon_operation_count == 0
    assert MUT_KEY.canon_operation_count == 1
    with pytest.raises(ValidationError):
        CanonMutationEffectKey.model_validate({"kind": "THREAD_PAYOFF"})


def test_semantic_effect_key_union_dispatches_on_kind() -> None:
    adapter: TypeAdapter[NarrativeSemanticEffectKey] = TypeAdapter(NarrativeSemanticEffectKey)
    assert isinstance(adapter.validate_python(PAYOFF_KEY.model_dump()), ThreadPayoffEffectKey)
    assert isinstance(adapter.validate_python(MUT_KEY.model_dump()), CanonMutationEffectKey)


@pytest.mark.parametrize("model", [NarrativeWorkScope, CanonMutationEffectKey, SourceSpan, ThreadPayoffEffectKey])
def test_contracts_forbid_extra_fields(model: type) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"unexpected": "x"})


def test_source_span_is_a_non_empty_half_open_interval() -> None:
    with pytest.raises(ValidationError):
        SourceSpan(start=5, end=5)
    with pytest.raises(ValidationError):
        SourceSpan(start=5, end=1)


def test_draft_and_revision_reject_naive_timestamps() -> None:
    with pytest.raises(ValidationError):
        DraftCandidate(
            candidate_id="cand-1",
            work_scope=SCOPE,
            base_canon_version_id="cv-1",
            plan_version=1,
            scene_contract_version=1,
            context_pack_id="ctx-1",
            normalized_content="hi",
            content_hash="pch:x",
            writer_kind="HUMAN",
            writer_version="n/a",
            provenance=PROV,
            created_at=NAIVE,
            created_by="who",
            semantic_fingerprint="esf:x",
        )


def test_revision_predecessor_cannot_be_itself() -> None:
    with pytest.raises(ValidationError):
        NarrativeRevision(
            revision_id="rev-1",
            work_scope=SCOPE,
            base_candidate_id="cand-1",
            predecessor_revision_id="rev-1",
            base_canon_version_id="cv-1",
            plan_version=1,
            scene_contract_version=1,
            context_pack_id="ctx-1",
            normalized_content="hi",
            content_hash="pch:x",
            review_refs=[],
            provenance=PROV,
            created_at=NOW,
            created_by="who",
            semantic_fingerprint="esf:x",
        )


def test_successful_extraction_result_requires_a_non_empty_unique_ordered_id_list() -> None:
    with pytest.raises(ValidationError):
        _result(outcome="SUCCEEDED", change_set_ids=[])
    with pytest.raises(ValidationError):
        _result(outcome="SUCCEEDED", change_set_ids=["cs-1", "cs-1"])
    ok = _result(outcome="SUCCEEDED", change_set_ids=["cs-2", "cs-1"])
    assert tuple(ok.change_set_ids) == ("cs-2", "cs-1")  # order preserved, not sorted


def test_non_success_extraction_result_must_have_no_change_sets() -> None:
    with pytest.raises(ValidationError):
        _result(outcome="FAILED", change_set_ids=["cs-1"])
    assert _result(outcome="OUTCOME_UNKNOWN").change_set_ids == ()


def test_change_set_requires_spans_effect_keys_and_changes() -> None:
    with pytest.raises(ValidationError):
        _change_set(source_spans=[])
    with pytest.raises(ValidationError):
        _change_set(semantic_effect_keys=[])
    with pytest.raises(ValidationError):
        _change_set(changes=[])


def test_change_item_effect_keys_must_be_declared_on_the_change_set() -> None:
    with pytest.raises(ValidationError):
        _change_set(
            changes=[NarrativeChangeItem(change_id="ch-1", evidence_span=SPAN, effect_keys=[PAYOFF_KEY], summary="s")]
        )


def test_change_evidence_span_must_be_contained_by_declared_coverage() -> None:
    outside = SourceSpan(start=8, end=20)  # SPAN is 0..10; this straddles the gap after it
    with pytest.raises(ValidationError):
        _change_set(
            changes=[NarrativeChangeItem(change_id="ch-1", evidence_span=outside, effect_keys=[MUT_KEY], summary="s")]
        )
    # Adjacent declared spans count as one continuous coverage region.
    ok = _change_set(
        source_spans=[SourceSpan(start=0, end=10), SourceSpan(start=10, end=30)],
        changes=[
            NarrativeChangeItem(
                change_id="ch-1", evidence_span=SourceSpan(start=5, end=25), effect_keys=[MUT_KEY], summary="s"
            )
        ],
    )
    assert ok.changes[0].evidence_span.end == 25


def test_thread_payoff_effect_key_maps_to_zero_canon_operations() -> None:
    with pytest.raises(ValidationError):
        ThreadPayoffEffectKey(thread_ref="t1", payoff_ref="p1", canon_operation_count=1)


def test_extraction_attempt_is_frozen() -> None:
    attempt = ExtractionAttempt(
        attempt_id="att-1",
        generation=0,
        work_scope=SCOPE,
        revision_id="rev-1",
        revision_acceptance_decision_id="dec-1",
        observed_revision_effective_generation=0,
        base_canon_version_id="cv-1",
        plan_version=1,
        scene_contract_version=1,
        context_pack_id="ctx-1",
        extractor_kind="LOCAL",
        extractor_version="x-1",
        policy_ref="pol",
        policy_version="1",
        admitted_at=NOW,
        admitted_by="who",
        input_fingerprint="if",
    )
    with pytest.raises(ValidationError):
        attempt.generation = 1
