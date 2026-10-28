"""Publication projection validates data bindings without granting host authority."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any

import pytest

from r2.advanced_creative.digests import canonical_json_bytes
from r2.contracts import quality as q
from r2.quality.digests import compute_digest, policy_domain, verify_caches
from r2.quality.errors import (
    OperationalEnvelopeExceededError,
    PrerequisiteNotAcceptedError,
    ProfilePublicationUnauthorizedError,
)
from r2.quality.profiles import (
    build_published_profile,
    profile_requires_reevaluation,
    publication_bindings,
    validate_publication_envelope,
)
from tests.unit.r2.contracts.test_quality import DIGEST, NOW, OTHER_UUID, draft_data

POLICY_ID = "m10.profile-publication.interactive-human.v1"


def publication_request(**draft_changes: Any) -> q.ProfilePublicationAuthorizationRequest:
    draft = draft_data() | draft_changes
    draft["policy_digest"] = compute_digest(
        policy_domain(q.QualityProfileDraft.model_validate(draft).policy), draft["policy"]
    )
    subject = {
        "user_id": draft["user_id"],
        "project_name": draft["project_name"],
        "actor_id": draft["created_by"],
        "profile_draft": draft,
        "profile_draft_digest": compute_digest("m10.quality-profile-draft.v1", draft),
        "expected_profile_revision": draft["revision"] - 1,
    }
    body = {
        "command": {
            "user_id": subject["user_id"],
            "project_name": subject["project_name"],
            "actor_id": subject["actor_id"],
            "operation": "PUBLISH_PROFILE",
            "command_id": "publish",
            "request_digest": DIGEST,
        },
        "subject": subject,
    }
    body["command"]["request_digest"] = compute_digest("m10.profile-publication-request.v1", body)
    return q.ProfilePublicationAuthorizationRequest.model_validate(body)


def publication_lease(request: q.ProfilePublicationAuthorizationRequest) -> q.ProfilePublicationAuthorizationLease:
    return q.ProfilePublicationAuthorizationLease(
        authorization_id="issued-authorization",
        action="PROFILE_PUBLICATION",
        user_id=request.command.user_id,
        project_name=request.command.project_name,
        actor_id=request.command.actor_id,
        command_id=request.command.command_id,
        request_digest=compute_digest("m10.profile-publication-request.v1", request),
        subject_digest=compute_digest("m10.profile-publication-subject.v1", request.subject),
        policy_id=POLICY_ID,
        policy_version="1",
        evidence_digest=DIGEST,
        issued_at=NOW,
        admit_not_after=NOW + timedelta(seconds=30),
    )


def publish(request: q.ProfilePublicationAuthorizationRequest, **changes: Any) -> q.QualityProfileRevision:
    kwargs = {"policy_id": POLICY_ID, "policy_version": "1"} | changes
    return build_published_profile(request, publication_lease(request), NOW, **kwargs)


def test_projection_builds_complete_digest_bound_profile_without_mutating_inputs() -> None:
    request = publication_request()
    lease = publication_lease(request)
    before = canonical_json_bytes([request, lease])
    admitted_at = NOW + timedelta(seconds=2)
    profile = build_published_profile(request, lease, admitted_at, policy_id=POLICY_ID, policy_version="1")
    expected = request.subject.profile_draft.model_dump(mode="python") | {
        "profile_digest": DIGEST,
        "publication_authorization_id": lease.authorization_id,
        "publication_policy_id": POLICY_ID,
        "publication_policy_version": "1",
        "publication_evidence_digest": DIGEST,
        "publication_admitted_at": admitted_at,
        "publication_subject_digest": compute_digest("m10.profile-publication-subject.v1", request.subject),
        "publication_request_digest": request.command.request_digest,
    }
    expected["profile_digest"] = compute_digest("m10.quality-profile.v1", expected)
    assert profile.model_dump(mode="python") == expected
    assert verify_caches(profile) is None
    assert q.QualityProfileRevision.model_validate_json(profile.model_dump_json()) == profile
    assert canonical_json_bytes([request, lease]) == before
    assert publication_bindings(request) == (lease.request_digest, lease.subject_digest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action", "QUALITY_DISPOSITION"),
        ("user_id", "other"),
        ("project_name", "other"),
        ("actor_id", "other"),
        ("command_id", "other"),
        ("request_digest", "sha256:" + "b" * 64),
        ("subject_digest", "sha256:" + "b" * 64),
        ("policy_id", "other"),
        ("policy_version", "2"),
        ("issued_at", NOW + timedelta(seconds=30)),
        ("admit_not_after", NOW),
        ("admit_not_after", NOW + timedelta(seconds=30, microseconds=1)),
        ("issued_at", NOW.replace(tzinfo=None)),
    ],
)
def test_projection_refuses_forged_or_mismatched_lease(field: str, value: Any) -> None:
    request = publication_request()
    lease = publication_lease(request).model_copy(update={field: value})
    with pytest.raises(ProfilePublicationUnauthorizedError, match=r"^M10_PROFILE_PUBLICATION_UNAUTHORIZED$"):
        build_published_profile(request, lease, NOW, policy_id=POLICY_ID, policy_version="1")


@pytest.mark.parametrize(
    ("admitted_at", "allowed"),
    [
        (NOW - timedelta(microseconds=1), False),
        (NOW, True),
        (NOW + timedelta(seconds=30, microseconds=-1), True),
        (NOW + timedelta(seconds=30), False),
        (NOW.replace(tzinfo=None), False),
    ],
)
def test_final_admission_uses_aware_half_open_lease_window(admitted_at: datetime, allowed: bool) -> None:
    request = publication_request()
    if allowed:
        result = build_published_profile(
            request, publication_lease(request), admitted_at, policy_id=POLICY_ID, policy_version="1"
        )
        assert result.publication_admitted_at == admitted_at
    else:
        with pytest.raises(ProfilePublicationUnauthorizedError):
            build_published_profile(
                request, publication_lease(request), admitted_at, policy_id=POLICY_ID, policy_version="1"
            )


@pytest.mark.parametrize("part", ["command", "scope", "draft_cache", "policy_cache", "parent", "draft_body"])
def test_request_shape_and_every_embedded_cache_are_revalidated(part: str) -> None:
    request = publication_request()
    body = request.model_dump(mode="python")
    if part == "command":
        body["command"]["operation"] = "COMPLETE_RUN"
    elif part == "scope":
        body["subject"]["actor_id"] = "other"
    elif part == "draft_cache":
        body["subject"]["profile_draft_digest"] = DIGEST
    elif part == "policy_cache":
        body["subject"]["profile_draft"]["policy_digest"] = DIGEST
    elif part == "parent":
        body["subject"]["profile_draft"]["parent_revision"] = 1
    else:
        body["subject"]["profile_draft"]["cohort_id"] = "other"
    forged = request.model_copy(update=body)
    for operation in [validate_publication_envelope, publication_bindings]:
        with pytest.raises(ProfilePublicationUnauthorizedError):
            operation(forged)
    with pytest.raises(ProfilePublicationUnauthorizedError):
        build_published_profile(forged, publication_lease(request), NOW, policy_id=POLICY_ID, policy_version="1")


@pytest.mark.parametrize("field", ["user_id", "project_name", "actor_id", "command_id", "cohort_id", "product_surface"])
@pytest.mark.parametrize("size", [254, 255, 256])
@pytest.mark.parametrize("multibyte", [False, True])
def test_identity_bounds_measure_utf8_bytes(field: str, size: int, multibyte: bool) -> None:
    identity = ("é" * (size // 2) + "x" * (size % 2)) if multibyte else "x" * size
    assert len(identity.encode("utf-8")) == size
    draft_changes = {"created_by" if field == "actor_id" else field: identity} if field != "command_id" else {}
    request = publication_request(**draft_changes)
    if field == "command_id":
        request = request.model_copy(update={"command": request.command.model_copy(update={"command_id": identity})})
    if size <= 255:
        assert validate_publication_envelope(request) is None
    else:
        with pytest.raises(OperationalEnvelopeExceededError):
            validate_publication_envelope(request)


def sized_request(size: int) -> q.ProfilePublicationAuthorizationRequest:
    policy = draft_data()["policy"]
    policy["reference_eligibility_policy_id"] = "x"
    baseline = publication_request(policy=policy)
    padding = size - len(canonical_json_bytes(baseline))
    assert padding > 0
    policy["reference_eligibility_policy_id"] += "x" * padding
    result = publication_request(policy=policy)
    assert len(canonical_json_bytes(result)) == size
    return result


@pytest.mark.parametrize("size", [1_048_575, 1_048_576, 1_048_577])
def test_request_envelope_uses_inclusive_canonical_json_byte_limit(size: int) -> None:
    request = sized_request(size)
    if size <= 1_048_576:
        assert validate_publication_envelope(request) is None
    else:
        with pytest.raises(OperationalEnvelopeExceededError):
            validate_publication_envelope(request)


@pytest.mark.parametrize("factual", ["slot", "freshness"])
def test_factual_policy_is_valid_data_but_not_admitted_publication(factual: str) -> None:
    policy = copy.deepcopy(draft_data()["policy"])
    if factual == "slot":
        policy["assessment_requirements"][0]["slots"][0]["kind"] = "FACTUAL"
    else:
        policy["freshness_rules"][0]["evidence_kind"] = "FACTUAL"
    request = publication_request(policy=policy)
    assert verify_caches(request) is None
    for operation in [validate_publication_envelope, publication_bindings, publish]:
        with pytest.raises(PrerequisiteNotAcceptedError, match=r"^M10_PREREQUISITE_NOT_ACCEPTED$"):
            operation(request)


@pytest.mark.parametrize(
    ("changes", "effect", "expected"),
    [
        ({}, "REEVALUATE_CURRENT", True),
        ({}, "HISTORICAL_ONLY", False),
        ({"user_id": "other"}, "REEVALUATE_CURRENT", False),
        ({"project_name": "other"}, "REEVALUATE_CURRENT", False),
        ({"profile_id": OTHER_UUID}, "REEVALUATE_CURRENT", False),
        ({"cohort_id": "other"}, "REEVALUATE_CURRENT", False),
        ({"product_surface": "other"}, "REEVALUATE_CURRENT", False),
        ({"revision": 1, "parent_revision": None}, "REEVALUATE_CURRENT", False),
    ],
)
def test_reevaluation_is_only_same_scope_profile_cohort_surface_and_strictly_newer(
    changes: dict[str, Any], effect: str, expected: bool
) -> None:
    previous = publish(publication_request())
    newer = publish(
        publication_request(**({"revision": 2, "parent_revision": 1, "supersession_effect": effect} | changes))
    )
    before = canonical_json_bytes([previous, newer])
    assert profile_requires_reevaluation(previous, newer) is expected
    assert profile_requires_reevaluation(newer, previous) is False
    assert canonical_json_bytes([previous, newer]) == before


def test_reevaluation_refuses_tampered_historical_profile_cache() -> None:
    previous = publish(publication_request())
    newer = publish(publication_request(revision=2, parent_revision=1, supersession_effect="REEVALUATE_CURRENT"))
    with pytest.raises(ProfilePublicationUnauthorizedError):
        profile_requires_reevaluation(previous.model_copy(update={"profile_digest": DIGEST}), newer)


@pytest.mark.parametrize("field", ["policy_id", "policy_version"])
def test_projection_compares_lease_with_expected_current_policy(field: str) -> None:
    with pytest.raises(ProfilePublicationUnauthorizedError):
        publish(publication_request(), **{field: "different"})


def test_short_lease_and_equivalent_offset_admission_are_valid() -> None:
    from datetime import timezone

    request = publication_request()
    lease = publication_lease(request).model_copy(update={"admit_not_after": NOW + timedelta(seconds=1)})
    admission = NOW.astimezone(timezone(timedelta(hours=7)))
    profile = build_published_profile(request, lease, admission, policy_id=POLICY_ID, policy_version="1")
    assert profile.publication_admitted_at == NOW
    assert verify_caches(profile) is None


def test_strictly_newer_supersession_can_skip_intermediate_revisions() -> None:
    previous = publish(publication_request())
    newer = publish(publication_request(revision=3, parent_revision=2, supersession_effect="REEVALUATE_CURRENT"))
    assert profile_requires_reevaluation(previous, newer) is True
