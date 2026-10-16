"""Digest domains bind semantic fields without renewing server-assigned authority."""

import hashlib
import json
from datetime import UTC, datetime

import pytest

from r2.contracts.opportunity import CommandContext, ProfilePublicationSubject
from r2.opportunity import digests as d

ID = "019a0000-0000-7000-8000-000000000001"
OTHER = "019a0000-0000-7000-8000-000000000002"
H = "sha256:" + "a" * 64


def test_subject_digest_matches_independent_canonical_vector():
    subject = ProfilePublicationSubject(
        user_id="u1", project_name="show-a", actor_id="human-a", profile_id=ID, parent_revision=None, payload_digest=H
    )
    body = {"domain": "m9.profile-publication-subject.v1", "schema_version": "1", "body": subject.model_dump()}
    expected = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert d.digest_profile_publication_subject(subject) == expected
    assert (
        d.digest_profile_publication_subject(subject.model_copy(update={"payload_digest": "sha256:" + "b" * 64}))
        != expected
    )


def test_creative_content_preserves_unicode_and_mapping_order():
    first = {
        "title": "爽型",
        "premise": "重生",
        "angle": "原创",
        "audience": {"z": 2, "a": 1},
        "creator_intent": {"goal": "复仇"},
    }
    second = {**first, "audience": {"a": 1, "z": 2}}
    assert d.digest_creative_content(**first) == d.digest_creative_content(**second)
    assert d.digest_creative_content(**first) != d.digest_creative_content(**{**first, "angle": "反转"})
    assert d.digest_creative_content(**first) != H


def test_command_identity_binds_project_actor_operation_and_full_body():
    context = CommandContext(command_id=ID, user_id="u1", project_name="show-a", actor_id="human-a")
    baseline = d.digest_command_request("publish_cohort_profile", context, {"payload_digest": H})
    for field, value in (("actor_id", "human-b"), ("project_name", "show-b"), ("command_id", OTHER)):
        assert (
            d.digest_command_request(
                "publish_cohort_profile", context.model_copy(update={field: value}), {"payload_digest": H}
            )
            != baseline
        )
    assert d.digest_command_request("decide_greenlight", context, {"payload_digest": H}) != baseline
    assert (
        d.digest_command_request("publish_cohort_profile", context, {"payload_digest": "sha256:" + "b" * 64})
        != baseline
    )


def test_command_guard_uses_full_key_and_signed_big_endian_halves():
    import struct

    context = CommandContext(command_id=ID, user_id="u1", project_name="show-a", actor_id="human-a")
    body = {
        "domain": "m9.command-key-guard.v1",
        "schema_version": "1",
        "body": {"user_id": "u1", "actor_id": "human-a", "operation": "publish_cohort_profile", "command_id": ID},
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).digest()
    assert d.command_guard_key("publish_cohort_profile", context) == struct.unpack(">ii", digest[:8])
    assert d.command_guard_key(
        "publish_cohort_profile", context.model_copy(update={"project_name": "show-b"})
    ) == d.command_guard_key("publish_cohort_profile", context)
    assert d.command_guard_key("other", context) != d.command_guard_key("publish_cohort_profile", context)


def test_result_digest_ignores_only_own_digest_and_covers_server_time():
    result = {
        "command_id": ID,
        "request_digest": H,
        "result_digest": H,
        "committed_at": datetime(2026, 10, 16, tzinfo=UTC),
    }
    baseline = d.digest_command_result("publish_cohort_profile", H, result)
    assert (
        d.digest_command_result("publish_cohort_profile", H, {**result, "result_digest": "sha256:" + "b" * 64})
        == baseline
    )
    assert (
        d.digest_command_result(
            "publish_cohort_profile", H, {**result, "committed_at": datetime(2026, 10, 17, tzinfo=UTC)}
        )
        != baseline
    )


def test_evidence_closure_rejects_policy_pack_substitution():
    from r2.contracts.opportunity import M8LearningEvidenceEntry

    entry = M8LearningEvidenceEntry(
        ref="learning:1",
        kind="OBSERVATION",
        m8_digest=H,
        state="CURRENT",
        superseding_ref=None,
        expires_at=None,
        creative_profile_id="WESTERN_GENERIC",
        creative_profile_version="1",
        creative_policy_pack_digest=H,
    )
    policy = ("WESTERN_GENERIC", "1", H)
    baseline = d.digest_evidence_closure(
        user_id="u1",
        project_name="show-a",
        creative_policy=policy,
        source_rule_digests=(),
        snapshots=(),
        signals=(),
        m8_entries=(entry,),
    )
    assert baseline.startswith("sha256:")
    with pytest.raises(ValueError, match="M9_COHORT_LEAKAGE"):
        d.digest_evidence_closure(
            user_id="u1",
            project_name="show-a",
            creative_policy=("WESTERN_GENERIC", "1", "sha256:" + "b" * 64),
            source_rule_digests=(),
            snapshots=(),
            signals=(),
            m8_entries=(entry,),
        )


def independent_digest(domain, body):
    def serialize(value):
        if isinstance(value, datetime):
            return value.isoformat().replace("+00:00", "Z")
        raise TypeError(type(value).__name__)

    raw = json.dumps(
        {"domain": domain, "schema_version": "1", "body": body},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=serialize,
    )
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


@pytest.mark.parametrize(
    ("function_name", "model_name", "domain", "body", "excluded"),
    [
        (
            "digest_capability_grant",
            "SourceCapabilityGrant",
            "m9.capability-grant.v1",
            {"user_id": "u1", "refresh_after": datetime(2026, 10, 16, tzinfo=UTC), "deletion_deadline_seconds": 60},
            {"grant_digest": H},
        ),
        (
            "digest_cohort_profile_payload",
            "OpportunityCohortProfilePayload",
            "m9.cohort-profile-payload.v1",
            {
                "creative_profile_id": "WESTERN_GENERIC",
                "creative_profile_version": "1",
                "creative_policy_pack_digest": H,
            },
            {},
        ),
        (
            "digest_cohort_profile",
            "OpportunityCohortProfile",
            "m9.cohort-profile.v1",
            {"profile_id": ID, "payload_digest": H, "custodian_evidence_digest": H},
            {"profile_digest": H, "payload": {}},
        ),
        (
            "digest_source_query",
            "SourceQuery",
            "m9.source-query.v1",
            {"user_id": "u1", "capability_evaluation_digest": H, "parameters": {"q": "新作"}},
            {
                "query_id": ID,
                "revision": 1,
                "parent_revision": None,
                "created_by": "human-a",
                "created_at": datetime(2026, 10, 16, tzinfo=UTC),
                "query_digest": H,
            },
        ),
        (
            "digest_source_snapshot",
            "SourceSnapshot",
            "m9.source-snapshot.v1",
            {"snapshot_id": ID, "capability_evaluation_digest": H, "pages": ()},
            {"snapshot_digest": H},
        ),
        (
            "digest_source_observation",
            "NormalizedSourceObservation",
            "m9.source-observation.v1",
            {"snapshot_id": ID, "data_class": "project-owned", "retained_normalized_value_digest": None},
            {
                "observation_id": OTHER,
                "revision": 1,
                "parent_revision": None,
                "observed_at": datetime(2026, 10, 16, tzinfo=UTC),
                "observation_digest": H,
            },
        ),
        (
            "digest_opportunity_signal",
            "DerivedOpportunitySignal",
            "m9.opportunity-signal.v1",
            {
                "data_class": "project-owned",
                "input_closure_digest": H,
                "expires_at": datetime(2026, 10, 16, tzinfo=UTC),
            },
            {
                "signal_id": ID,
                "revision": 1,
                "parent_revision": None,
                "evaluated_by": "human-a",
                "evaluated_at": datetime(2026, 10, 15, tzinfo=UTC),
                "signal_digest": H,
            },
        ),
        (
            "digest_opportunity_payload",
            "OpportunityPayload",
            "m9.opportunity-payload.v1",
            {"creative_content_digest": H, "evidence_closure_digest": H, "source_rule_evidence": ()},
            {},
        ),
        (
            "digest_greenlight_subject",
            "GreenlightSubject",
            "m9.greenlight-subject.v1",
            {"user_id": "u1", "candidate_id": ID, "reason": "Human choice"},
            {},
        ),
        (
            "digest_greenlight_binding",
            "GreenlightDecision",
            "m9.greenlight-binding.v1",
            {"user_id": "u1", "candidate_id": ID, "custodian_evidence_digest": H},
            {"decision_id": OTHER, "decision_version": 1, "binding_digest": H},
        ),
        (
            "digest_invalidation_job",
            "InvalidationJob",
            "m9.invalidation-job.v1",
            {"user_id": "u1", "invalidation_job_id": ID, "propagation_deadline": datetime(2026, 10, 16, tzinfo=UTC)},
            {"job_digest": H},
        ),
        (
            "digest_invalidation_subject",
            "InvalidationSubject",
            "m9.invalidation-subject.v1",
            {"user_id": "u1", "snapshot_ids": (ID,), "reason": "erase"},
            {},
        ),
    ],
)
def test_typed_domain_vectors_cover_semantics_and_exclude_only_declared_fields(
    function_name, model_name, domain, body, excluded
):
    from r2.contracts import opportunity as c

    # These are isolated hashing projections, not admitted contract or authority fixtures.
    model_type = getattr(c, model_name)
    inputs = {**body, **excluded}
    if "parameters" in inputs:
        inputs["parameters"] = c.CanonicalJsonObject.model_validate(inputs["parameters"])
    if "payload" in excluded:
        inputs["payload"] = c.OpportunityCohortProfilePayload.model_construct()
    model = model_type.model_construct(**inputs)
    function = getattr(d, function_name)
    assert function(model) == independent_digest(domain, body)
    key = next(iter(body))
    changed = {**inputs, key: "changed-semantic-value"}
    assert function(model_type.model_construct(**changed)) != function(model)


@pytest.mark.parametrize(
    ("name", "domain", "values"),
    [
        ("digest_signal_input_closure", "m9.signal-input-closure.v1", [(OTHER, H, 2), (ID, H, 1)]),
        ("digest_policy_basis", "m9.signal-policy-basis.v1", [(OTHER, 1, H, ID, H), (ID, 1, H, OTHER, H)]),
        ("digest_assessment_signal_closure", "m9.assessment-signal-closure.v1", [(OTHER, 1, H), (ID, 1, H)]),
    ],
)
def test_reference_closure_vectors_sort_and_refuse_duplicate_members(name, domain, values):
    function = getattr(d, name)
    assert function(values) == independent_digest(domain, sorted(values))
    assert function(values) == function(list(reversed(values)))
    with pytest.raises(ValueError, match="unique"):
        function([values[0], values[0]])


def test_capability_evaluation_binds_actor_and_condition_order():
    from r2.contracts.opportunity import CanonicalJsonObject, EffectiveCapabilityEvaluation

    evaluation = EffectiveCapabilityEvaluation.model_construct(user_id="u1", grant_digest=H, evaluation_digest=H)
    assert d.digest_capability_evaluation(evaluation, actor_id="human-a") == independent_digest(
        "m9.capability-evaluation.v1", {"user_id": "u1", "grant_digest": H, "actor_id": "human-a"}
    )
    assert d.digest_capability_evaluation(evaluation, actor_id="human-a") != d.digest_capability_evaluation(
        evaluation, actor_id="human-b"
    )
    conditions = (CanonicalJsonObject.model_validate({"q": 1}), CanonicalJsonObject.model_validate({"q": 2}))
    first = d.digest_condition_evidence(grant_id=ID, grant_version=1, grant_digest=H, condition_evidence=conditions)
    assert first == independent_digest(
        "m9.capability-condition-evidence.v1",
        {"grant_id": ID, "grant_version": 1, "grant_digest": H, "condition_evidence": [{"q": 1}, {"q": 2}]},
    )
    assert first != d.digest_condition_evidence(
        grant_id=ID, grant_version=1, grant_digest=H, condition_evidence=tuple(reversed(conditions))
    )


def test_cursor_proofs_bind_scope_query_and_adapter_without_inventing_absence_proofs():
    fields = {
        "user_id": "u1",
        "project_name": "show-a",
        "query_id": ID,
        "query_revision": 1,
        "query_digest": H,
        "adapter_version": "manual-import.v1",
    }
    assert d.digest_page_cursor(**fields, cursor=None) is None
    first = d.digest_page_cursor(**fields, cursor="opaque-cursor")
    assert first == independent_digest("m9.page-cursor.v1", {**fields, "cursor": "opaque-cursor"})
    assert first != d.digest_page_cursor(**{**fields, "project_name": "show-b"}, cursor="opaque-cursor")


def test_system_command_and_result_domains_bind_the_scoped_key_and_frozen_result_time():
    key = {"user_id": "u1", "project_name": "show-a", "operation": "sweep_retention", "command_id": ID}
    assert d.digest_system_command_request(**key, command={"batch": 1}) == independent_digest(
        "m9.system-command-request.v1", {**key, "command": {"batch": 1}}
    )
    assert d.digest_system_command_result(
        **key, result={"swept_at": "2026-10-16T00:00:00Z", "result_digest": H}
    ) == independent_digest("m9.system-command-result.v1", {**key, "result": {"swept_at": "2026-10-16T00:00:00Z"}})


def test_source_rule_proof_binds_the_entire_rule_and_exact_profile():
    from r2.contracts.opportunity import CohortSourceEvidence, CohortSourceRule

    rule = CohortSourceRule(
        source_kind="manual-import",
        required=False,
        allowed_intents=["LANDSCAPE"],
        allowed_data_classes=["project-owned"],
        minimum_coverage="PARTIAL",
        maximum_age_seconds=60,
        compatibility_key="manual-v1",
    )
    row = CohortSourceEvidence(
        source_kind="manual-import", snapshots=(), missing_reason="NO_SNAPSHOT_IN_CLOSURE", result_digest=H
    )
    key = {"user_id": "u1", "project_name": "show-a", "profile_id": ID, "profile_revision": 1, "profile_digest": H}
    expected = {
        **key,
        "rule": rule.model_dump(mode="json"),
        "source_kind": "manual-import",
        "snapshots": [],
        "missing_reason": "NO_SNAPSHOT_IN_CLOSURE",
    }
    assert d.digest_cohort_source_evidence(**key, rule=rule, evidence=row) == independent_digest(
        "m9.cohort-source-evidence.v1", expected
    )
    assert d.digest_cohort_source_evidence(**key, rule=rule, evidence=row) != d.digest_cohort_source_evidence(
        **key, rule=rule.model_copy(update={"maximum_age_seconds": 61}), evidence=row
    )


def test_candidate_lineage_binds_scope_and_full_profile_evidence_closure():
    from r2.contracts.opportunity import OpportunityCandidateRevision, OpportunityPayload

    profile = {
        "cohort_profile_id": ID,
        "cohort_profile_revision": 1,
        "cohort_profile_digest": H,
        "evidence_closure_digest": H,
    }
    envelope = {
        "candidate_id": OTHER,
        "revision": 1,
        "parent_revision": None,
        "supersedes_candidate_id": None,
        "payload_digest": H,
        "user_id": "u1",
        "project_name": "show-a",
    }
    candidate = OpportunityCandidateRevision.model_construct(
        **envelope, payload=OpportunityPayload.model_construct(**profile)
    )
    assert d.digest_opportunity_lineage(candidate) == independent_digest(
        "m9.opportunity-lineage.v1", {**envelope, **profile}
    )
    assert d.digest_opportunity_lineage(
        candidate.model_copy(update={"project_name": "show-b"})
    ) != d.digest_opportunity_lineage(candidate)


def test_validity_proof_binds_identity_scope_and_erasable_content_state():
    from r2.contracts.opportunity import EvidenceValidityProjection

    projection = EvidenceValidityProjection(
        state="CURRENT",
        invalidation_job_id=None,
        reason_code=None,
        invalidated_at=None,
        erasable_content_available=True,
        projection_digest=H,
    )
    scope = {"user_id": "u1", "project_name": "show-a", "identity": ID, "revision": 1}
    body = {
        **scope,
        "state": "CURRENT",
        "invalidation_job_id": None,
        "reason_code": None,
        "invalidated_at": None,
        "erasable_content_available": True,
    }
    assert d.digest_evidence_validity(**scope, projection=projection) == independent_digest(
        "m9.evidence-validity-projection.v1", body
    )
    assert d.digest_evidence_validity(**scope, projection=projection) != d.digest_evidence_validity(
        **scope, projection=projection.model_copy(update={"erasable_content_available": False})
    )


def test_factual_selected_content_is_transient_while_closure_binds_only_erasable_refs():
    from r2.contracts.opportunity import ResolvedFactualEvidenceSelection

    refs = {
        "snapshot_id": ID,
        "snapshot_digest": H,
        "page_ordinal": 1,
        "source_identity_ref": "opaque-identity",
        "locator": "page:1",
        "selected_content_ref": "opaque-content",
        "selected_content_integrity_ref": "opaque-integrity",
        "evidence_type": "text",
    }
    selection = ResolvedFactualEvidenceSelection(**refs, selected_content_digest=H, selected_content={"text": "原文"})
    assert d.digest_selected_content(selection) == independent_digest(
        "m9.factual-selected-content.v1", {**refs, "selected_content": {"text": "原文"}}
    )
    assert d.digest_selection_closure(factual_scope="topic", selections=(selection,)) == independent_digest(
        "m9.factual-selection-closure.v1",
        {"factual_scope": "topic", "selections": [{**refs, "selected_content_digest": H}]},
    )
    changed = selection.model_copy(update={"selected_content_ref": "other-opaque-content"})
    assert d.digest_selected_content(changed) != d.digest_selected_content(selection)
    assert d.digest_selection_closure(factual_scope="topic", selections=(changed,)) != d.digest_selection_closure(
        factual_scope="topic", selections=(selection,)
    )


def test_bridge_freeze_dependency_and_learning_proofs_are_distinct_domains():
    from r2.contracts.opportunity import CanonicalJsonObject, M8LearningEvidenceEntry

    frozen = CanonicalJsonObject.model_validate({"m8_append_command_id": ID, "frozen_revision": {"payload_digest": H}})
    assert d.digest_bridge_frozen_request("CANVAS_SEED", frozen) == independent_digest(
        "m9.bridge-frozen-request.v1", {"kind": "CANVAS_SEED", "request": frozen.model_dump()}
    )
    scope = {"user_id": "u1", "project_name": "show-a"}
    dependencies = [("candidate", OTHER, 1, H, ["snapshot:1"])]
    assert d.digest_dependency_closure(**scope, job_id=ID, dependencies=dependencies) == independent_digest(
        "m9.invalidation-dependency-closure.v1", {**scope, "job_id": ID, "dependencies": dependencies}
    )
    refs = CanonicalJsonObject.model_validate({"evidence_closure_digest": H})
    assert d.digest_bridge_closure(**scope, kind="CANVAS_SEED", dependencies=refs) == independent_digest(
        "m9.bridge-closure.v1", {**scope, "kind": "CANVAS_SEED", "dependencies": refs.model_dump()}
    )
    entry = M8LearningEvidenceEntry(
        ref="learning:1",
        kind="OBSERVATION",
        m8_digest=H,
        state="CURRENT",
        superseding_ref=None,
        expires_at=None,
        creative_profile_id="WESTERN_GENERIC",
        creative_profile_version="1",
        creative_policy_pack_digest=H,
    )
    assert d.digest_m8_learning_closure(**scope, entries=(entry,)) == independent_digest(
        "m9.m8-learning-evidence-closure.v1", {**scope, "entries": [entry.model_dump()]}
    )


def test_freshness_proof_cannot_renew_inputs_by_changing_profile_or_expiry():
    from r2.contracts.opportunity import CanonicalJsonObject, OpportunityCohortProfile, OpportunityCohortProfilePayload

    payload = OpportunityCohortProfilePayload.model_construct(
        freshness_policy=CanonicalJsonObject.model_validate({"age": 60})
    )
    profile = OpportunityCohortProfile.model_construct(profile_id=ID, revision=1, profile_digest=H, payload=payload)
    expiry = datetime(2026, 10, 16, tzinfo=UTC)
    assert d.digest_freshness_policy(profile=profile, earliest_expiry=expiry) == independent_digest(
        "m9.greenlight-freshness-policy.v1",
        {
            "profile_id": ID,
            "revision": 1,
            "profile_digest": H,
            "freshness_policy": {"age": 60},
            "earliest_expiry": expiry,
        },
    )
    assert d.digest_freshness_policy(profile=profile, earliest_expiry=expiry) != d.digest_freshness_policy(
        profile=profile, earliest_expiry=None
    )
