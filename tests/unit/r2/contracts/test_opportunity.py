"""Opportunity boundaries reject ambiguous scope, lineage and evidence shapes."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from r2.contracts import opportunity as c

ID = "019a0000-0000-7000-8000-000000000001"
OTHER = "019a0000-0000-7000-8000-000000000002"
DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 10, 16, tzinfo=UTC)


def profile_payload() -> dict:
    return {
        "cohort_id": "western",
        "cohort_version": "1",
        "creative_profile_id": "WESTERN_GENERIC",
        "creative_profile_version": "1",
        "creative_policy_pack_digest": DIGEST,
        "source_rules": [
            {
                "source_kind": "manual-import",
                "required": True,
                "allowed_intents": ["LANDSCAPE"],
                "allowed_data_classes": ["project-owned"],
                "minimum_coverage": "COMPLETE_WITHIN_DECLARED_BOUNDS",
                "maximum_age_seconds": 3600,
                "compatibility_key": "manual-v1",
            }
        ],
        "dimension_rules": [
            {
                "dimension": "NOVELTY",
                "required": True,
                "transform_id": "novelty",
                "transform_version": "1",
                "calibration_ref": "western-v1",
                "missingness_policy": {"reject": True},
            }
        ],
        "originality_corpus_refs": ["western-corpus"],
        "originality_corpus_digest": DIGEST,
        "reviewer_qualification": {
            "rubric_version": "1",
            "languages": ["en"],
            "cultural_cohort": "western",
            "minimum_blind_reviewers": 2,
            "qualification_evidence_schema": {"type": "object"},
        },
        "freshness_policy": {"max_age": 3600},
        "candidate_expiry_seconds": 86400,
    }


def test_profile_freezes_nested_content_and_forbids_extra_fields():
    raw = profile_payload()
    profile = c.OpportunityCohortProfilePayload.model_validate(raw)
    raw["freshness_policy"]["max_age"] = 1
    assert profile.freshness_policy.model_dump() == {"max_age": 3600}
    with pytest.raises(ValidationError):
        profile.cohort_version = "2"
    with pytest.raises(ValidationError):
        c.OpportunityCohortProfilePayload.model_validate({**raw, "overall_score": 1})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("creative_profile_id", "generic-western"),
        ("creative_profile_id", "zh-shuang"),
        ("creative_policy_pack_digest", "sha256:" + "A" * 64),
        ("cohort_id", "Western"),
        ("candidate_expiry_seconds", 86401),
        ("candidate_expiry_seconds", 0),
        ("originality_corpus_refs", [" "]),
    ],
)
def test_profile_refuses_invalid_policy_identity_or_limits(field, value):
    with pytest.raises(ValidationError):
        c.OpportunityCohortProfilePayload.model_validate({**profile_payload(), field: value})


@pytest.mark.parametrize("field", ["source_rules", "dimension_rules"])
def test_profile_rejects_duplicate_rule_keys(field):
    raw = profile_payload()
    raw[field] = raw[field] * 2
    with pytest.raises(ValidationError, match="unique"):
        c.OpportunityCohortProfilePayload.model_validate(raw)


def test_profile_requires_a_required_dimension_and_usable_coverage():
    raw = profile_payload()
    raw["dimension_rules"][0]["required"] = False
    with pytest.raises(ValidationError, match="required dimension"):
        c.OpportunityCohortProfilePayload.model_validate(raw)
    raw = profile_payload()
    raw["source_rules"][0]["minimum_coverage"] = "UNAVAILABLE"
    with pytest.raises(ValidationError, match="coverage"):
        c.OpportunityCohortProfilePayload.model_validate(raw)


@pytest.mark.parametrize(("parent", "head"), [(None, 1), (1, None), (0, 1), (1, 0)])
def test_publication_rejects_inconsistent_genesis_or_append(parent, head):
    with pytest.raises(ValidationError):
        c.PublishOpportunityCohortProfile.model_validate(
            {
                "context": {"command_id": ID, "user_id": "u1", "project_name": "show-a", "actor_id": "human-a"},
                "profile_id": OTHER,
                "parent_revision": parent,
                "expected_head_version": head,
                "payload": profile_payload(),
            }
        )


@pytest.mark.parametrize("command_id", ["", "not-a-uuid", "019a0000-0000-4000-8000-000000000001"])
def test_command_requires_uuid7_identity(command_id):
    with pytest.raises(ValidationError):
        c.CommandContext(command_id=command_id, user_id="u1", project_name="show-a", actor_id="human-a")


def test_lease_normalizes_utc_and_rejects_naive_or_overlong_window():
    body = {
        "authorization_id": ID,
        "command_id": OTHER,
        "authorized": True,
        "subject_digest": DIGEST,
        "custodian_policy_id": "arcreel.showrunner-grant",
        "custodian_policy_version": "governance.showrunner_grant_event.v1",
        "custodian_evidence_digest": DIGEST,
        "issued_at": NOW,
        "admit_not_after": NOW + timedelta(seconds=30),
    }
    lease = c.CustodianAuthorizationLease(**{**body, "issued_at": NOW.astimezone(timezone(timedelta(hours=7)))})
    assert lease.issued_at.tzinfo == UTC
    for changes in (
        {"issued_at": NOW.replace(tzinfo=None)},
        {"admit_not_after": NOW + timedelta(seconds=31)},
        {"admit_not_after": NOW},
    ):
        with pytest.raises(ValidationError):
            c.CustodianAuthorizationLease(**{**body, **changes})


def test_source_rule_evidence_distinguishes_absent_and_present():
    row = {
        "source_kind": "manual-import",
        "snapshots": (),
        "missing_reason": "NO_SNAPSHOT_IN_CLOSURE",
        "result_digest": DIGEST,
    }
    assert c.CohortSourceEvidence(**row).snapshots == ()
    with pytest.raises(ValidationError):
        c.CohortSourceEvidence(**{**row, "missing_reason": None})
    snapshot = {
        "snapshot_id": ID,
        "snapshot_digest": DIGEST,
        "query_digest": DIGEST,
        "coverage_state": "PARTIAL",
        "oldest_capture_at": NOW,
        "usable_until": NOW + timedelta(hours=1),
    }
    with pytest.raises(ValidationError):
        c.CohortSourceEvidence(**{**row, "snapshots": [snapshot]})
    assert (
        c.CohortSourceEvidence(**{**row, "snapshots": [snapshot], "missing_reason": None}).snapshots[0].snapshot_id
        == ID
    )


def test_invalidation_requires_target_and_refuses_caller_time():
    body = {
        "context": {"command_id": ID, "user_id": "u1", "project_name": "show-a", "actor_id": "human-a"},
        "source_kind": "manual-import",
        "snapshot_ids": (),
        "payload_refs": (),
        "m8_learning_evidence_refs": (),
        "factual_authority_evidence_refs": (),
        "capability_grant_id": OTHER,
        "capability_grant_digest": DIGEST,
        "reason": "policy erasure",
    }
    with pytest.raises(ValidationError, match="target"):
        c.InvalidateSourceEvidence(**body)
    assert c.InvalidateSourceEvidence(**{**body, "snapshot_ids": [ID]}).snapshot_ids == (ID,)
    with pytest.raises(ValidationError):
        c.InvalidateSourceEvidence(**{**body, "snapshot_ids": [ID], "requested_at": NOW})


def test_projection_cannot_mark_erased_content_available():
    body = {
        "state": "INVALIDATED",
        "invalidation_job_id": ID,
        "reason_code": "M9_EVIDENCE_STALE",
        "invalidated_at": NOW,
        "erasable_content_available": False,
        "projection_digest": DIGEST,
    }
    assert not c.EvidenceValidityProjection(**body).erasable_content_available
    with pytest.raises(ValidationError):
        c.EvidenceValidityProjection(**{**body, "erasable_content_available": True})


def test_factual_selections_canonicalize_order_and_reject_duplicates():
    selection = {
        "snapshot_id": ID,
        "snapshot_digest": DIGEST,
        "page_ordinal": 1,
        "source_identity_ref": "opaque-identity",
        "locator": "page:1",
        "selected_content_ref": "opaque-content",
        "selected_content_integrity_ref": "opaque-integrity",
        "selected_content_digest": DIGEST,
        "evidence_type": "text",
    }
    context = {"command_id": OTHER, "user_id": "u1", "project_name": "show-a", "actor_id": "human-a"}
    with pytest.raises(ValidationError):
        c.SubmitFactualEvidence(context=context, selections=(), factual_scope="topic")
    with pytest.raises(ValidationError, match="unique"):
        c.SubmitFactualEvidence(context=context, selections=[selection, selection], factual_scope="topic")
    resolved = c.ResolvedFactualEvidenceSelection(**selection, selected_content={"text": "原文"})
    submission = c.FactualEvidenceSubmission(
        command_id=OTHER,
        user_id="u1",
        project_name="show-a",
        actor_id="human-a",
        factual_scope="topic",
        selections=[resolved],
        selection_closure_digest=DIGEST,
    )
    assert submission.selections[0].selected_content.model_dump() == {"text": "原文"}


def test_refs_are_sorted_without_changing_page_order():
    body = {
        "payload_ref": "opaque-payload",
        "payload_integrity_ref": "opaque-integrity",
        "source_identity_refs": ["z", "a"],
        "retained_content_digest": None,
        "raw_size_bytes": 0,
    }
    assert c.PayloadRef(**body).source_identity_refs == ("a", "z")
    with pytest.raises(ValidationError, match="unique"):
        c.PayloadRef(**{**body, "source_identity_refs": ["a", "a"]})


def page_body() -> dict[str, object]:
    return {
        "ordinal": 1,
        "request_cursor_digest": None,
        "response_cursor_digest": None,
        "provider_request_id": None,
        "payload_ref": "opaque-payload",
        "payload_integrity_ref": "opaque-integrity",
        "retained_source_payload_digest": None,
        "raw_media_type": "application/json",
        "raw_size_bytes": 20,
        "data_classes": ["project-owned"],
        "data_class_clocks": [
            {
                "data_class": "project-owned",
                "captured_at": NOW,
                "refresh_due_at": NOW + timedelta(hours=1),
                "retention_due_at": None,
            }
        ],
        "record_count": 1,
        "captured_at": NOW,
        "missing_reason": None,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"data_class_clocks": []},
        {"data_classes": ["foreign-class"]},
        {
            "data_class_clocks": [
                {
                    "data_class": "project-owned",
                    "captured_at": NOW + timedelta(seconds=1),
                    "refresh_due_at": None,
                    "retention_due_at": None,
                }
            ]
        },
        {"payload_integrity_ref": None},
        {"raw_size_bytes": 2097153},
    ],
)
def test_page_rejects_incomplete_class_clocks_or_payload_pair(changes):
    with pytest.raises(ValidationError):
        c.SnapshotPage(**{**page_body(), **changes})


def test_snapshot_rejects_page_order_and_inconsistent_totals():
    body = {
        "snapshot_id": ID,
        "revision": 1,
        "parent_revision": None,
        "user_id": "u1",
        "project_name": "show-a",
        "query_id": OTHER,
        "query_revision": 1,
        "query_digest": DIGEST,
        "attempt_id": OTHER,
        "source_kind": "manual-import",
        "source_contract_version": "1",
        "source_identity_refs": ["opaque-identity"],
        "pages": [page_body()],
        "coverage_state": "PARTIAL",
        "requested_record_limit": 10,
        "returned_record_count": 1,
        "coverage_note": "fixture",
        "provider_observed_at": None,
        "capture_started_at": NOW,
        "capture_completed_at": NOW,
        "adapter_version": "1",
        "capability_grant_digest": DIGEST,
        "capability_evaluation_digest": DIGEST,
        "snapshot_digest": DIGEST,
        "created_at": NOW,
    }
    assert c.SourceSnapshot(**body).pages[0].ordinal == 1
    for changes in (
        {"returned_record_count": 2},
        {"pages": [{**page_body(), "ordinal": 2}]},
        {"capture_completed_at": NOW - timedelta(seconds=1)},
        {"revision": 2, "parent_revision": None},
    ):
        with pytest.raises(ValidationError):
            c.SourceSnapshot(**{**body, **changes})


def test_observation_requires_value_pair_or_explicit_missingness():
    body = {
        "observation_id": ID,
        "revision": 1,
        "parent_revision": None,
        "user_id": "u1",
        "project_name": "show-a",
        "snapshot_id": OTHER,
        "snapshot_digest": DIGEST,
        "page_ordinal": 1,
        "source_kind": "manual-import",
        "source_identity_ref": "opaque-identity",
        "native_field_name": "title",
        "native_field_definition": "original title",
        "native_field_version": "1",
        "data_class": "project-owned",
        "value_ref": "opaque-value",
        "value_integrity_ref": "opaque-integrity",
        "retained_normalized_value_digest": None,
        "unit": None,
        "window_start": None,
        "window_end": None,
        "missing_reason": None,
        "payload_integrity_ref": "opaque-integrity",
        "retained_source_payload_digest": None,
        "normalization_version": "1",
        "observation_digest": DIGEST,
        "observed_at": NOW,
    }
    assert c.NormalizedSourceObservation(**body).value_ref == "opaque-value"
    for changes in (
        {"value_integrity_ref": None},
        {"missing_reason": "NOT_RETURNED"},
        {"value_ref": None, "value_integrity_ref": None},
        {"window_start": NOW, "window_end": NOW - timedelta(seconds=1)},
    ):
        with pytest.raises(ValidationError):
            c.NormalizedSourceObservation(**{**body, **changes})
    missing = c.NormalizedSourceObservation(
        **{**body, "value_ref": None, "value_integrity_ref": None, "missing_reason": "NOT_RETURNED"}
    )
    assert missing.missing_reason is c.MissingReason.NOT_RETURNED


def test_conditional_grant_cannot_omit_conditions_or_duplicate_data_rules():
    body = {
        "grant_id": ID,
        "grant_version": 1,
        "user_id": "u1",
        "project_name": "show-a",
        "source_kind": "manual-import",
        "source_contract_version": "1",
        "account_binding_digest": None,
        "credential_ref": None,
        "allowed_operations": ["import"],
        "allowed_purposes": ["LANDSCAPE"],
        "permission": "CONDITIONAL",
        "conditions": [{"requires": "human"}],
        "state": "ENABLED",
        "policy_documents": [
            {
                "document_id": OTHER,
                "canonical_url": "https://example.test/policy",
                "document_digest": DIGEST,
                "assessed_at": NOW,
                "effective_at": None,
                "expires_at": NOW + timedelta(hours=2),
            }
        ],
        "data_rules": [
            {
                "data_class": "project-owned",
                "refresh_interval_seconds": None,
                "retention_seconds": None,
                "delete_on_revoke": False,
                "digest_proof_may_be_retained": True,
            }
        ],
        "refresh_after": NOW + timedelta(hours=1),
        "deletion_deadline_seconds": 60,
        "issued_by": "host",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(hours=2),
        "grant_digest": DIGEST,
    }
    assert c.SourceCapabilityGrant(**body).permission is c.PermissionDisposition.CONDITIONAL
    for changes in (
        {"conditions": []},
        {"permission": "PERMITTED"},
        {"data_rules": body["data_rules"] * 2},
        {"allowed_operations": ["import", "import"]},
    ):
        with pytest.raises(ValidationError):
            c.SourceCapabilityGrant(**{**body, **changes})
    # Historical expired evidence remains parseable; use-time checks are separate.
    assert c.SourceCapabilityGrant(**{**body, "state": "EXPIRED"}).state is c.CapabilityState.EXPIRED


def test_learning_bundle_recomputes_earliest_expiry_and_state_shape():
    entry = {
        "ref": "learning:1",
        "kind": "OBSERVATION",
        "m8_digest": DIGEST,
        "state": "CURRENT",
        "superseding_ref": None,
        "expires_at": NOW,
        "creative_profile_id": "WESTERN_GENERIC",
        "creative_profile_version": "1",
        "creative_policy_pack_digest": DIGEST,
    }
    with pytest.raises(ValidationError):
        c.M8LearningEvidenceBundle(entries=[entry], evidence_closure_digest=DIGEST, earliest_expiry=None)
    bundle = c.M8LearningEvidenceBundle(entries=[entry], evidence_closure_digest=DIGEST, earliest_expiry=NOW)
    assert bundle.earliest_expiry == NOW
    with pytest.raises(ValidationError):
        c.M8LearningEvidenceEntry(**{**entry, "state": "SUPERSEDED"})


def test_stable_errors_expose_stop_code_without_arbitrary_provider_details():
    from r2.opportunity.errors import OpportunityError, StopCode

    error = OpportunityError(StopCode.M9_COHORT_LEAKAGE)
    assert str(error) == "M9_COHORT_LEAKAGE"
    assert error.code.value == "M9_COHORT_LEAKAGE"


def opportunity_payload() -> dict:
    return {
        "title": "原创故事",
        "premise": "主人公重生",
        "angle": "反转",
        "audience": {},
        "creator_intent": {},
        "cohort_id": "western",
        "cohort_version": "1",
        "cohort_profile_id": ID,
        "cohort_profile_revision": 1,
        "cohort_profile_digest": DIGEST,
        "creative_content_digest": DIGEST,
        "assessments": [
            {
                "dimension": "NOVELTY",
                "signal_ids": [OTHER],
                "signal_closure_digest": DIGEST,
                "assessment_schema_version": "1",
                "assessment_ref": "opaque-assessment",
                "assessment_integrity_ref": "opaque-integrity",
                "retained_assessment_digest": None,
                "calibration_ref": "western-v1",
            }
        ],
        "source_rule_evidence": [
            {
                "source_kind": "z-source",
                "snapshots": [],
                "missing_reason": "NO_SNAPSHOT_IN_CLOSURE",
                "result_digest": "sha256:" + "a" * 64,
            },
            {
                "source_kind": "a-source",
                "snapshots": [],
                "missing_reason": "NO_SNAPSHOT_IN_CLOSURE",
                "result_digest": "sha256:" + "b" * 64,
            },
        ],
        "snapshot_ids": [ID],
        "signal_ids": [OTHER],
        "evidence_closure_digest": DIGEST,
        "m8_learning_evidence_refs": [],
        "unverified_claim_candidate_refs": [],
        "uncertainties": [],
        "open_questions": [],
    }


def test_source_rule_rows_are_canonical_by_source_kind_and_dimensions_are_unique():
    raw = opportunity_payload()
    payload = c.OpportunityPayload.model_validate(raw)
    assert [row.source_kind for row in payload.source_rule_evidence] == ["a-source", "z-source"]
    raw["assessments"] *= 2
    with pytest.raises(ValidationError, match="unique"):
        c.OpportunityPayload.model_validate(raw)


@pytest.mark.parametrize(("field", "value"), [("snapshot_ids", ["not-uuid7"]), ("signal_ids", ["not-uuid7"])])
def test_opportunity_reference_ids_have_uuid7_shape(field, value):
    with pytest.raises(ValidationError):
        c.OpportunityPayload.model_validate({**opportunity_payload(), field: value})


def test_candidate_revision_ceiling_and_self_supersession_are_rejected():
    body = {
        "candidate_id": ID,
        "revision": 1,
        "parent_revision": None,
        "supersedes_candidate_id": None,
        "user_id": "u1",
        "project_name": "show-a",
        "payload": opportunity_payload(),
        "payload_digest": DIGEST,
        "lineage_digest": DIGEST,
        "created_by": "human-a",
        "created_at": NOW,
    }
    assert c.OpportunityCandidateRevision(**body).revision == 1
    for changes in ({"revision": 251, "parent_revision": 250}, {"supersedes_candidate_id": ID}):
        with pytest.raises(ValidationError):
            c.OpportunityCandidateRevision(**{**body, **changes})


def test_greenlight_expiry_and_supersession_never_become_unbounded_authority():
    body = {
        "decision_id": ID,
        "decision_version": 1,
        "supersedes_decision_id": None,
        "user_id": "u1",
        "project_name": "show-a",
        "candidate_id": OTHER,
        "candidate_revision": 1,
        "candidate_payload_digest": DIGEST,
        "evidence_closure_digest": DIGEST,
        "freshness_policy_digest": DIGEST,
        "disposition": "APPROVE",
        "canvas_scope": "OPPORTUNITY_EXPLORATION",
        "issuer_id": "human-a",
        "custodian_authorization_id": OTHER,
        "custodian_policy_id": "arcreel.showrunner-grant",
        "custodian_policy_version": "governance.showrunner_grant_event.v1",
        "custodian_evidence_digest": DIGEST,
        "custodian_admitted_at": NOW,
        "reason": "Human choice",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(hours=24),
        "binding_digest": DIGEST,
    }
    assert c.GreenlightDecision(**body).disposition is c.GreenlightDisposition.APPROVE
    for changes in (
        {"expires_at": NOW + timedelta(hours=24, seconds=1)},
        {"expires_at": NOW},
        {"disposition": "EXPIRE"},
        {"disposition": "SUPERSEDE"},
        {"canvas_scope": "PRODUCTION"},
    ):
        with pytest.raises(ValidationError):
            c.GreenlightDecision(**{**body, **changes})


@pytest.mark.parametrize(
    ("field", "ceiling"), [("snapshot_ids", 100), ("signal_ids", 256), ("m8_learning_evidence_refs", 32)]
)
def test_candidate_closure_refuses_inputs_above_frozen_v1_ceiling(field, ceiling):
    raw = opportunity_payload()
    ids = [f"019a0000-0000-7000-8000-{number:012x}" for number in range(1, ceiling + 2)]
    assert len(c.OpportunityPayload.model_validate({**raw, field: ids[:-1]}).model_dump()[field]) == ceiling
    with pytest.raises(ValidationError):
        c.OpportunityPayload.model_validate({**raw, field: ids})


def test_signal_requires_inputs_policy_basis_and_ordered_expiry():
    body = {
        "signal_id": ID,
        "revision": 1,
        "parent_revision": None,
        "user_id": "u1",
        "project_name": "show-a",
        "dimension": "NOVELTY",
        "data_class": "project-owned",
        "cohort_id": "western",
        "cohort_version": "1",
        "cohort_profile_id": ID,
        "cohort_profile_revision": 1,
        "cohort_profile_digest": DIGEST,
        "input_observation_ids": [OTHER],
        "input_closure_digest": DIGEST,
        "transform_id": "novelty",
        "transform_version": "1",
        "parameters": {},
        "result_schema_version": "1",
        "result_ref": "opaque-result",
        "result_integrity_ref": "opaque-integrity",
        "retained_signal_result_digest": None,
        "policy_basis_grant_ids": [OTHER],
        "policy_basis_digest": DIGEST,
        "applicability": {},
        "exclusions": [],
        "signal_digest": DIGEST,
        "evaluated_by": "human-a",
        "evaluated_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
    }
    assert c.DerivedOpportunitySignal(**body).input_observation_ids == (OTHER,)
    for changes in ({"input_observation_ids": []}, {"policy_basis_grant_ids": []}, {"expires_at": NOW}):
        with pytest.raises(ValidationError):
            c.DerivedOpportunitySignal(**{**body, **changes})


def test_query_parameter_ceiling_counts_canonical_utf8_bytes():
    body = {
        "source_kind": "manual-import",
        "source_contract_version": "1",
        "operation": "import",
        "intent": "LANDSCAPE",
        "parameters": {},
        "cohort_id": "western",
        "cohort_version": "1",
        "cohort_profile_id": ID,
        "cohort_profile_revision": 1,
        "cohort_profile_digest": DIGEST,
        "capability_grant_id": OTHER,
        "capability_grant_version": 1,
        "capability_grant_digest": DIGEST,
        "capability_evaluation_id": OTHER,
        "capability_evaluation_digest": DIGEST,
        "credential_ref": None,
        "max_pages": 20,
        "max_records": 1000,
        "max_quota_units": 0,
    }
    exact = c.SourceQueryDraft(**{**body, "parameters": {"q": "x" * 65528}})
    assert len(exact.parameters.model_dump()["q"]) == 65528
    for parameters in ({"q": "x" * 65529}, {"q": "爽" * 21843}):
        with pytest.raises(ValidationError):
            c.SourceQueryDraft(**{**body, "parameters": parameters})


def test_invalidation_job_origin_cannot_invent_or_drop_human_authority():
    body = {
        "invalidation_job_id": ID,
        "job_version": 1,
        "user_id": "u1",
        "project_name": "show-a",
        "origin": "HUMAN_REQUEST",
        "origin_key": "opaque-origin",
        "source_kind": "manual-import",
        "snapshot_ids": [OTHER],
        "payload_refs": [],
        "m8_learning_evidence_refs": [],
        "factual_authority_evidence_refs": [],
        "capability_grant_id": OTHER,
        "capability_grant_digest": DIGEST,
        "custodian_authorization_id": ID,
        "custodian_policy_id": "arcreel.showrunner-grant",
        "custodian_policy_version": "governance.showrunner_grant_event.v1",
        "custodian_evidence_digest": DIGEST,
        "custodian_admitted_at": NOW,
        "state": "PLANNED",
        "reason": "erase",
        "dependency_closure_digest": None,
        "erased_payload_count": 0,
        "invalidated_record_count": 0,
        "requested_at": NOW,
        "propagation_deadline": NOW + timedelta(hours=24),
        "updated_at": NOW,
        "operator_reason": None,
        "job_digest": DIGEST,
    }
    assert c.InvalidationJob(**body).origin is c.InvalidationOrigin.HUMAN_REQUEST
    for changes in (
        {"custodian_evidence_digest": None},
        {"origin": "RETENTION_SWEEP"},
        {"propagation_deadline": NOW + timedelta(hours=24, seconds=1)},
        {"updated_at": NOW - timedelta(seconds=1)},
    ):
        with pytest.raises(ValidationError):
            c.InvalidationJob(**{**body, **changes})
    system = {
        **body,
        "origin": "M8_CORRECTION",
        "capability_grant_id": None,
        "capability_grant_digest": None,
        "custodian_authorization_id": None,
        "custodian_policy_id": None,
        "custodian_policy_version": None,
        "custodian_evidence_digest": None,
        "custodian_admitted_at": None,
    }
    assert c.InvalidationJob(**system).origin is c.InvalidationOrigin.M8_CORRECTION


def test_profile_cannot_borrow_a_sibling_cohorts_reviewer_rubric():
    raw = profile_payload()
    raw["reviewer_qualification"]["cultural_cohort"] = "zh-shuang"
    with pytest.raises(ValidationError, match="cohort"):
        c.OpportunityCohortProfilePayload.model_validate(raw)


def test_opaque_scope_identities_are_preserved_exactly_instead_of_unicode_rewritten():
    principal = "reviewer-e\u0301"
    context = c.CommandContext(command_id=ID, user_id="u1", project_name="show-a", actor_id=principal)
    assert context.actor_id == principal
