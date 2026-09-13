from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from r2.contracts.narrative import AddFactOperation, CanonDeltaPayload, Fact
from r2.contracts.narrative_lifecycle import (
    CanonMutationEffectKey,
    ChangeSetReviewCommand,
    ChangeSetReviewHead,
    CompilationAttempt,
    CompilationResult,
    CompilationSelectedChangeSet,
    CompiledCanonDeltaEvidence,
    ConflictResolutionCommand,
    ConflictResolutionHead,
    ConflictResolutionLineage,
    ConflictSubject,
    DraftCandidate,
    ExtractionAttempt,
    ExtractionResult,
    NarrativeChangeItem,
    NarrativeChangeSet,
    NarrativeDecisionAuthorization,
    NarrativeDecisionReceipt,
    NarrativeDecisionRetryAuthentication,
    NarrativeRevision,
    NarrativeSemanticEffectKey,
    NarrativeWorkScope,
    ObservedEffectiveHead,
    RevisionAcceptanceCommand,
    RevisionAcceptanceHead,
    SourceSpan,
    ThreadPayoffEffectKey,
)
from r2.contracts.provenance import Provenance
from r2.narrative.hashing import seal_canon_delta
from r2.narrative_lifecycle.hashing import compute_compilation_input_fingerprint

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


# --- M5C-2 decision authority contracts ---


def _authorization(**overrides: object) -> NarrativeDecisionAuthorization:
    base: dict[str, object] = {
        "authorization_ref": "auth-1",
        "user_id": "u-1",
        "project_name": "proj",
        "actor_id": "human:1",
        "authority_role": "HUMAN_SHOWRUNNER",
        "decision_family": "REVISION_ACCEPTANCE",
        "action": "ACCEPT",
        "decision_id": "dec-1",
        "stable_subject_fingerprint": "ssf:1",
        "decision_command_fingerprint": "dcf:1",
        "authenticated_at": NOW,
        "authenticated_via": "session:abc",
    }
    return NarrativeDecisionAuthorization(**(base | overrides))


def _retry_authentication(**overrides: object) -> NarrativeDecisionRetryAuthentication:
    base: dict[str, object] = {
        "retry_authentication_ref": "retry-1",
        "user_id": "u-1",
        "project_name": "proj",
        "actor_id": "human:1",
        "authority_role": "HUMAN_SHOWRUNNER",
        "decision_id": "dec-1",
        "authenticated_at": NOW,
        "authenticated_via": "session:xyz",
    }
    return NarrativeDecisionRetryAuthentication(**(base | overrides))


def _revision_command(**overrides: object) -> RevisionAcceptanceCommand:
    base: dict[str, object] = {
        "decision_id": "dec-1",
        "action": "ACCEPT",
        "work_scope": SCOPE,
        "selected_revision_id": "rev-1",
        "expected_latest_decision_id": None,
        "expected_effective_decision_id": None,
        "base_canon_version_id": "cv-1",
        "plan_version": 1,
        "scene_contract_version": 1,
        "context_pack_id": "ctx-1",
        "actor_id": "human:1",
    }
    return RevisionAcceptanceCommand(**(base | overrides))


def _change_set_review_command(**overrides: object) -> ChangeSetReviewCommand:
    base: dict[str, object] = {
        "decision_id": "dec-2",
        "action": "ACCEPT",
        "work_scope": SCOPE,
        "revision_acceptance_decision_id": "dec-1",
        "change_set_lineage_id": "lin-1",
        "selected_change_set_id": "cs-1",
        "expected_latest_decision_id": None,
        "expected_effective_decision_id": None,
        "base_canon_version_id": "cv-1",
        "plan_version": 1,
        "scene_contract_version": 1,
        "context_pack_id": "ctx-1",
        "actor_id": "human:1",
    }
    return ChangeSetReviewCommand(**(base | overrides))


def _conflict_resolution_command(**overrides: object) -> ConflictResolutionCommand:
    base: dict[str, object] = {
        "decision_id": "dec-3",
        "action": "RESOLVE",
        "work_scope": SCOPE,
        "revision_acceptance_decision_id": "dec-1",
        "conflict_resolution_lineage_id": "conf-1",
        "competing_change_set_ids": ["cs-1", "cs-2"],
        "competing_review_decision_ids": ["dec-2", "dec-2b"],
        "chosen_resolution": "resolution:keep-cs-1",
        "expected_latest_decision_id": None,
        "expected_effective_decision_id": None,
        "base_canon_version_id": "cv-1",
        "plan_version": 1,
        "scene_contract_version": 1,
        "context_pack_id": "ctx-1",
        "actor_id": "human:1",
    }
    return ConflictResolutionCommand(**(base | overrides))


def _receipt(**overrides: object) -> NarrativeDecisionReceipt:
    base: dict[str, object] = {
        "decision_id": "dec-1",
        "decision_family": "REVISION_ACCEPTANCE",
        "action": "ACCEPT",
        "decision_generation": 1,
        "effective_decision_id": "dec-1",
        "effective_generation": 1,
    }
    return NarrativeDecisionReceipt(**(base | overrides))


_HEAD_KEY_KWARGS: dict[type, dict[str, object]] = {
    RevisionAcceptanceHead: {"work_scope": SCOPE},
    ChangeSetReviewHead: {"revision_acceptance_decision_id": "dec-1", "change_set_lineage_id": "lin-1"},
    ConflictResolutionHead: {
        "revision_acceptance_decision_id": "dec-1",
        "conflict_resolution_lineage_id": "conf-1",
    },
}


def _head(head_cls: type, **overrides: object):
    base: dict[str, object] = {
        **_HEAD_KEY_KWARGS[head_cls],
        "latest_decision_id": None,
        "decision_generation": 0,
        "effective_decision_id": None,
        "effective_generation": 0,
    }
    return head_cls(**(base | overrides))


def _lineage(**overrides: object) -> ConflictResolutionLineage:
    base: dict[str, object] = {
        "conflict_resolution_lineage_id": "conf-1",
        "revision_acceptance_decision_id": "dec-1",
        "conflict_subject": ConflictSubject(coverage=(SPAN,), effect_key_subjects=("canon:FACT:hero",)),
        "conflict_subject_fingerprint": "csf:1",
        "created_at": NOW,
        "created_by": "human:1",
    }
    return ConflictResolutionLineage(**(base | overrides))


def test_authority_role_is_fixed_to_human_showrunner() -> None:
    with pytest.raises(ValidationError):
        _authorization(authority_role="HUMAN_AUTHOR")
    with pytest.raises(ValidationError):
        _retry_authentication(authority_role="HUMAN_AUTHOR")


@pytest.mark.parametrize(
    ("command_factory", "accepting_action"),
    [
        (_revision_command, "ACCEPT"),
        (_change_set_review_command, "ACCEPT"),
        (_conflict_resolution_command, "RESOLVE"),
    ],
)
def test_genesis_decision_expects_no_predecessors(command_factory, accepting_action: str) -> None:
    ok = command_factory(action=accepting_action, expected_latest_decision_id=None, expected_effective_decision_id=None)
    assert ok.expected_latest_decision_id is None
    assert ok.expected_effective_decision_id is None
    with pytest.raises(ValidationError):
        command_factory(
            action=accepting_action, expected_latest_decision_id=None, expected_effective_decision_id="dec-eff"
        )


@pytest.mark.parametrize(
    ("command_factory", "accepting_action"),
    [
        (_revision_command, "ACCEPT"),
        (_change_set_review_command, "ACCEPT"),
        (_conflict_resolution_command, "RESOLVE"),
    ],
)
def test_accepting_action_forbids_an_existing_effective_selection(command_factory, accepting_action: str) -> None:
    with pytest.raises(ValidationError):
        command_factory(
            action=accepting_action,
            expected_latest_decision_id="dec-0",
            expected_effective_decision_id="dec-eff",
        )
    ok = command_factory(
        action=accepting_action, expected_latest_decision_id="dec-0", expected_effective_decision_id=None
    )
    assert ok.action == accepting_action


@pytest.mark.parametrize(
    "command_factory", [_revision_command, _change_set_review_command, _conflict_resolution_command]
)
def test_supersede_requires_the_exact_current_effective_decision(command_factory) -> None:
    with pytest.raises(ValidationError):
        command_factory(action="SUPERSEDE", expected_latest_decision_id="dec-0", expected_effective_decision_id=None)
    with pytest.raises(ValidationError):
        # Genesis + SUPERSEDE can never be valid: there is no effective decision to supersede.
        command_factory(action="SUPERSEDE", expected_latest_decision_id=None, expected_effective_decision_id=None)
    ok = command_factory(
        action="SUPERSEDE", expected_latest_decision_id="dec-0", expected_effective_decision_id="dec-eff"
    )
    assert ok.expected_effective_decision_id == "dec-eff"


@pytest.mark.parametrize(
    "command_factory", [_revision_command, _change_set_review_command, _conflict_resolution_command]
)
def test_reject_names_a_candidate_and_preserves_the_effective_pointer(command_factory) -> None:
    # REJECT is valid whether or not an effective selection already exists, and never
    # forces that pointer to change or clear.
    without_effective = command_factory(
        action="REJECT", expected_latest_decision_id="dec-0", expected_effective_decision_id=None
    )
    assert without_effective.expected_effective_decision_id is None
    with_effective = command_factory(
        action="REJECT", expected_latest_decision_id="dec-0", expected_effective_decision_id="dec-eff"
    )
    assert with_effective.expected_effective_decision_id == "dec-eff"


def test_conflict_resolution_command_requires_at_least_two_competing_change_sets() -> None:
    with pytest.raises(ValidationError):
        _conflict_resolution_command(competing_change_set_ids=["cs-1"], competing_review_decision_ids=["dec-2"])


def test_conflict_resolution_command_pairs_change_sets_with_review_decisions() -> None:
    with pytest.raises(ValidationError):
        _conflict_resolution_command(competing_change_set_ids=["cs-1", "cs-2"], competing_review_decision_ids=["dec-2"])


def test_conflict_resolution_command_rejects_duplicate_competitors() -> None:
    with pytest.raises(ValidationError):
        _conflict_resolution_command(
            competing_change_set_ids=["cs-1", "cs-1"], competing_review_decision_ids=["dec-2", "dec-2b"]
        )


def test_decision_receipt_has_no_currently_effective_field() -> None:
    assert "currently_effective" not in NarrativeDecisionReceipt.model_fields
    receipt = _receipt()
    assert receipt.decision_id == "dec-1"
    assert receipt.effective_generation == 1


@pytest.mark.parametrize("head_cls", [RevisionAcceptanceHead, ChangeSetReviewHead, ConflictResolutionHead])
def test_head_genesis_is_a_null_pointer_at_zero_generation(head_cls: type) -> None:
    head = _head(head_cls)
    assert head.latest_decision_id is None
    assert head.decision_generation == 0
    assert head.effective_decision_id is None
    assert head.effective_generation == 0


@pytest.mark.parametrize("head_cls", [RevisionAcceptanceHead, ChangeSetReviewHead, ConflictResolutionHead])
def test_head_pointer_and_generation_move_together(head_cls: type) -> None:
    with pytest.raises(ValidationError):
        _head(head_cls, latest_decision_id=None, decision_generation=1)
    with pytest.raises(ValidationError):
        _head(head_cls, latest_decision_id="dec-1", decision_generation=0)
    ok = _head(head_cls, latest_decision_id="dec-1", decision_generation=1)
    assert ok.decision_generation == 1


@pytest.mark.parametrize("head_cls", [RevisionAcceptanceHead, ChangeSetReviewHead, ConflictResolutionHead])
def test_head_effective_generation_cannot_exceed_decision_generation(head_cls: type) -> None:
    with pytest.raises(ValidationError):
        _head(
            head_cls,
            latest_decision_id="dec-1",
            decision_generation=1,
            effective_decision_id="dec-1",
            effective_generation=2,
        )


def test_conflict_resolution_lineage_reuses_the_shared_conflict_subject_shape() -> None:
    lineage = _lineage()
    assert isinstance(lineage.conflict_subject, ConflictSubject)
    assert lineage.conflict_subject.coverage == (SPAN,)


@pytest.mark.parametrize(
    "make_instance",
    [
        _authorization,
        _retry_authentication,
        _revision_command,
        _change_set_review_command,
        _conflict_resolution_command,
        _receipt,
        lambda: _head(RevisionAcceptanceHead),
        lambda: _head(ChangeSetReviewHead),
        lambda: _head(ConflictResolutionHead),
        _lineage,
    ],
)
def test_decision_authority_contracts_forbid_extra_fields(make_instance) -> None:
    instance = make_instance()
    payload = instance.model_dump(mode="json") | {"unexpected_field": "nope"}
    with pytest.raises(ValidationError):
        type(instance).model_validate(payload)


# --- M5C-3 CanonDelta compilation: attempt/result/compiled-delta evidence ---


def _selected_change_sets(*pairs: tuple[str, str]) -> list[CompilationSelectedChangeSet]:
    return [CompilationSelectedChangeSet(change_set_id=cs, review_decision_id=rd) for cs, rd in pairs]


def _observed_heads(*pairs: tuple[str, int]) -> list[ObservedEffectiveHead]:
    return [ObservedEffectiveHead(decision_id=d, effective_generation=g) for d, g in pairs]


def _attempt(**overrides: object) -> CompilationAttempt:
    base: dict[str, object] = {
        "attempt_id": "cattempt-1",
        "generation": 0,
        "work_scope": SCOPE,
        "revision_id": "rev-1",
        "revision_acceptance_decision_id": "dec-rev-1",
        "selected_change_sets": _selected_change_sets(("cs-1", "dec-rev-1-review")),
        "conflict_resolution_decision_ids": [],
        "observed_effective_heads": _observed_heads(("dec-rev-1", 1)),
        "base_canon_version_id": "cv-1",
        "plan_version": 1,
        "scene_contract_version": 1,
        "context_pack_id": "ctx-1",
        "creative_policy_ref": "policy-1",
        "creative_policy_version": "1",
        "compiler_version": "compiler-1",
        "requested_canon_delta_id": "delta-1",
        "delta_created_at": NOW,
        "delta_created_by": "showrunner",
        "admitted_at": NOW,
        "admitted_by": "showrunner",
        "input_fingerprint": "cif:x",
    }
    return CompilationAttempt(**(base | overrides))


def _compilation_result(**overrides: object) -> CompilationResult:
    base: dict[str, object] = {
        "result_id": "cres-1",
        "attempt_id": "cattempt-1",
        "generation": 0,
        "outcome": "ABSTAINED",
        "canon_delta_id": None,
        "canon_delta_payload_hash": None,
        "diagnostics": [],
        "completed_at": NOW,
        "output_fingerprint": "of-1",
    }
    return CompilationResult(**(base | overrides))


def _canon_delta():
    fact = Fact(fact_id="fact-1", subject_ref="hero", predicate="mood", value="calm", effective_from=NOW)
    return seal_canon_delta(
        CanonDeltaPayload(
            canon_delta_id="delta-1",
            target_branch_id="branch-1",
            base_canon_version_id="cv-1",
            operations=[AddFactOperation(operation_id="op-1", target_id="fact-1", fact=fact)],
            source_change_set_refs=["cs-1"],
            author_decision_refs=["dec-rev-1"],
            validation_report_refs=[],
            created_at=NOW,
            created_by="showrunner",
        )
    )


def test_compilation_attempt_requires_at_least_one_selected_change_set() -> None:
    with pytest.raises(ValidationError):
        _attempt(selected_change_sets=[])


def test_compilation_attempt_rejects_duplicate_selected_change_set_ids() -> None:
    with pytest.raises(ValidationError):
        _attempt(selected_change_sets=_selected_change_sets(("cs-1", "r-1"), ("cs-1", "r-2")))


def test_compilation_attempt_rejects_duplicate_review_decision_ids() -> None:
    with pytest.raises(ValidationError):
        _attempt(selected_change_sets=_selected_change_sets(("cs-1", "r-1"), ("cs-2", "r-1")))


def test_compilation_attempt_rejects_duplicate_conflict_resolution_decision_ids() -> None:
    with pytest.raises(ValidationError):
        _attempt(conflict_resolution_decision_ids=["res-1", "res-1"])


def test_compilation_attempt_requires_at_least_one_observed_effective_head() -> None:
    with pytest.raises(ValidationError):
        _attempt(observed_effective_heads=[])


def test_compilation_attempt_rejects_duplicate_observed_head_decision_ids() -> None:
    with pytest.raises(ValidationError):
        _attempt(observed_effective_heads=_observed_heads(("dec-rev-1", 1), ("dec-rev-1", 2)))


def test_successful_compilation_result_requires_delta_id_and_hash() -> None:
    with pytest.raises(ValidationError):
        _compilation_result(outcome="SUCCEEDED")
    with pytest.raises(ValidationError):
        _compilation_result(outcome="SUCCEEDED", canon_delta_id="delta-1")
    ok = _compilation_result(outcome="SUCCEEDED", canon_delta_id="delta-1", canon_delta_payload_hash="h:1")
    assert ok.canon_delta_id == "delta-1"


@pytest.mark.parametrize("outcome", ["NO_CANON_MUTATION", "ABSTAINED", "CONFLICT", "FAILED"])
def test_non_succeeded_compilation_result_must_name_no_delta(outcome: str) -> None:
    with pytest.raises(ValidationError):
        _compilation_result(outcome=outcome, canon_delta_id="delta-1", canon_delta_payload_hash="h:1")
    assert _compilation_result(outcome=outcome).canon_delta_id is None


def test_compiled_canon_delta_evidence_hash_must_match_the_embedded_delta() -> None:
    delta = _canon_delta()
    ok = CompiledCanonDeltaEvidence(
        compilation_result_id="cres-1",
        compilation_attempt_id="cattempt-1",
        generation=0,
        canon_delta=delta,
        canon_delta_payload_hash=delta.payload_hash,
        stored_at=NOW,
    )
    assert ok.canon_delta_payload_hash == delta.payload_hash
    with pytest.raises(ValidationError):
        CompiledCanonDeltaEvidence(
            compilation_result_id="cres-1",
            compilation_attempt_id="cattempt-1",
            generation=0,
            canon_delta=delta,
            canon_delta_payload_hash="wrong-hash",
            stored_at=NOW,
        )


def test_compilation_input_fingerprint_is_deterministic() -> None:
    assert compute_compilation_input_fingerprint(_attempt()) == compute_compilation_input_fingerprint(_attempt())


def test_compilation_input_fingerprint_changes_with_semantic_input() -> None:
    baseline = compute_compilation_input_fingerprint(_attempt())
    changed = compute_compilation_input_fingerprint(
        _attempt(selected_change_sets=_selected_change_sets(("cs-2", "dec-rev-1-review")))
    )
    assert baseline != changed


@pytest.mark.parametrize(
    "override",
    [
        {"attempt_id": "cattempt-2"},
        {"generation": 5},
        {"requested_canon_delta_id": "delta-2"},
        {"delta_created_by": "someone-else"},
        {"admitted_by": "someone-else"},
    ],
)
def test_compilation_input_fingerprint_ignores_workflow_metadata(override: dict[str, object]) -> None:
    assert compute_compilation_input_fingerprint(_attempt()) == compute_compilation_input_fingerprint(
        _attempt(**override)
    )
