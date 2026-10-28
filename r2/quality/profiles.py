"""Pure publication projections; validated data grants no Human authority."""

from __future__ import annotations

from datetime import datetime

import r2.contracts.quality as q
from r2.advanced_creative.digests import canonical_json_bytes
from r2.quality.digests import compute_digest, policy_domain, verify_caches
from r2.quality.errors import (
    OperationalEnvelopeExceededError,
    PrerequisiteNotAcceptedError,
    ProfilePublicationUnauthorizedError,
)


def _request(request: q.ProfilePublicationAuthorizationRequest) -> q.ProfilePublicationAuthorizationRequest:
    try:
        normalized = q.ProfilePublicationAuthorizationRequest.model_validate(request)
        command = normalized.command
        draft = normalized.subject.profile_draft
        identities = (
            command.user_id,
            command.project_name,
            command.actor_id,
            command.command_id,
            draft.profile_id,
            draft.cohort_id,
            draft.product_surface,
        )
        if any(len(value.encode("utf-8")) > 255 for value in identities):
            raise OperationalEnvelopeExceededError()
        if len(canonical_json_bytes(normalized)) > 1_048_576:
            raise OperationalEnvelopeExceededError()
        verify_caches(normalized)
    except (ValueError, TypeError):
        raise ProfilePublicationUnauthorizedError() from None
    policy = normalized.subject.profile_draft.policy
    if any(
        slot.kind == q.AssessorKind.FACTUAL
        for requirement in policy.assessment_requirements
        for slot in requirement.slots
    ) or any(rule.evidence_kind == q.AssessorKind.FACTUAL for rule in policy.freshness_rules):
        raise PrerequisiteNotAcceptedError()
    return normalized


def validate_publication_envelope(request: q.ProfilePublicationAuthorizationRequest) -> None:
    """Reject oversized, unqualified or invalid input before the caller performs I/O."""
    _request(request)


def publication_bindings(request: q.ProfilePublicationAuthorizationRequest) -> tuple[str, str]:
    """Recompute semantic request and subject bindings from fully validated bodies."""
    normalized = _request(request)
    return (
        compute_digest("m10.profile-publication-request.v1", normalized),
        compute_digest("m10.profile-publication-subject.v1", normalized.subject),
    )


def build_published_profile(
    request: q.ProfilePublicationAuthorizationRequest,
    lease: q.ProfilePublicationAuthorizationLease,
    admitted_at: datetime,
    *,
    policy_id: str,
    policy_version: str,
) -> q.QualityProfileRevision:
    """Project resolved lease data at explicit admission time, without resolving its authority."""
    normalized = _request(request)
    try:
        resolved = q.ProfilePublicationAuthorizationLease.model_validate(lease)
        verify_caches(resolved)
        request_digest, subject_digest = publication_bindings(normalized)
        command = normalized.command
        if (
            (resolved.user_id, resolved.project_name, resolved.actor_id, resolved.command_id)
            != (command.user_id, command.project_name, command.actor_id, command.command_id)
            or (resolved.request_digest, resolved.subject_digest) != (request_digest, subject_digest)
            or (resolved.policy_id, resolved.policy_version) != (policy_id, policy_version)
            or admitted_at.tzinfo is None
            or admitted_at.utcoffset() is None
            or not resolved.issued_at <= admitted_at < resolved.admit_not_after
        ):
            raise ProfilePublicationUnauthorizedError()
        draft = normalized.subject.profile_draft
        body = draft.model_dump(mode="python") | {
            "policy_digest": compute_digest(policy_domain(draft.policy), draft.policy),
            "profile_digest": "sha256:" + "0" * 64,
            "publication_authorization_id": resolved.authorization_id,
            "publication_policy_id": resolved.policy_id,
            "publication_policy_version": resolved.policy_version,
            "publication_evidence_digest": resolved.evidence_digest,
            "publication_admitted_at": admitted_at,
            "publication_subject_digest": subject_digest,
            "publication_request_digest": request_digest,
        }
        body["profile_digest"] = compute_digest("m10.quality-profile.v1", body)
        result = q.QualityProfileRevision.model_validate(body)
        verify_caches(result)
        return result
    except (ValueError, TypeError):
        raise ProfilePublicationUnauthorizedError() from None


def profile_requires_reevaluation(previous: q.QualityProfileRevision, newer: q.QualityProfileRevision) -> bool:
    """Compare supersession intent only; this does not update readiness or historical runs."""
    try:
        old = q.QualityProfileRevision.model_validate(previous)
        new = q.QualityProfileRevision.model_validate(newer)
        verify_caches(old)
        verify_caches(new)
    except (ValueError, TypeError):
        raise ProfilePublicationUnauthorizedError() from None
    return (
        (old.user_id, old.project_name, old.profile_id, old.cohort_id, old.product_surface)
        == (new.user_id, new.project_name, new.profile_id, new.cohort_id, new.product_surface)
        and new.revision > old.revision
        and new.supersession_effect == q.SupersessionEffect.REEVALUATE_CURRENT
    )
