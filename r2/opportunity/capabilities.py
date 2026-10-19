"""Consume exact host capability evidence and preserve database page clocks."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from pydantic import ValidationError

from r2.contracts.opportunity import (
    CapabilityEvaluationRequest,
    CapabilityState,
    EffectiveCapabilityEvaluation,
    EvidenceDataClassClock,
    PermissionDisposition,
    SnapshotPage,
    SourceCapabilityGrant,
    SourceDataRule,
    SourcePageResult,
)
from r2.opportunity import digests
from r2.opportunity.errors import OpportunityError, StopCode


def validate_capability(
    grant: SourceCapabilityGrant,
    evaluation: EffectiveCapabilityEvaluation,
    request: CapabilityEvaluationRequest,
    *,
    now: datetime,
) -> None:
    """Validate trusted-host evidence; never mint, refresh or upgrade permission."""
    forbidden = StopCode.M9_SOURCE_POLICY_FORBIDDEN
    unavailable = StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE
    try:
        grant = SourceCapabilityGrant.model_validate(
            {name: getattr(grant, name) for name in SourceCapabilityGrant.model_fields}
        )
        evaluation = EffectiveCapabilityEvaluation.model_validate(
            {name: getattr(evaluation, name) for name in EffectiveCapabilityEvaluation.model_fields}
        )
        request = CapabilityEvaluationRequest.model_validate(
            {name: getattr(request, name) for name in CapabilityEvaluationRequest.model_fields}
        )
    except ValidationError:
        raise OpportunityError(forbidden) from None
    if now.tzinfo is None or now.utcoffset() is None:
        raise OpportunityError(unavailable)
    if grant.state is not CapabilityState.ENABLED:
        raise OpportunityError(unavailable)
    if grant.grant_digest != digests.digest_capability_grant(grant):
        raise OpportunityError(unavailable)
    if (
        now < grant.issued_at
        or now >= min(grant.refresh_after, grant.expires_at)
        or now < evaluation.evaluated_at
        or now >= evaluation.expires_at
        or any(
            now >= doc.expires_at or now < doc.assessed_at or (doc.effective_at is not None and now < doc.effective_at)
            for doc in grant.policy_documents
        )
    ):
        raise OpportunityError(unavailable)
    if any(
        getattr(request, key) != value
        for key, value in {
            "user_id": grant.user_id,
            "project_name": grant.project_name,
            "grant_id": grant.grant_id,
            "grant_version": grant.grant_version,
            "grant_digest": grant.grant_digest,
            "source_kind": grant.source_kind,
            "account_binding_digest": grant.account_binding_digest,
        }.items()
    ) or any(
        getattr(evaluation, key) != getattr(request, key)
        for key in (
            "user_id",
            "project_name",
            "grant_id",
            "grant_version",
            "grant_digest",
            "source_kind",
            "operation",
            "purpose",
            "account_binding_digest",
        )
    ):
        raise OpportunityError(forbidden)
    if request.operation not in grant.allowed_operations or request.purpose not in grant.allowed_purposes:
        raise OpportunityError(forbidden)
    if evaluation.evaluation_digest != digests.digest_capability_evaluation(evaluation, actor_id=request.actor_id):
        raise OpportunityError(forbidden)
    if evaluation.condition_evidence_digest != digests.digest_condition_evidence(
        grant_id=grant.grant_id,
        grant_version=grant.grant_version,
        grant_digest=grant.grant_digest,
        condition_evidence=evaluation.condition_evidence,
    ):
        raise OpportunityError(forbidden)
    if (
        grant.permission is PermissionDisposition.FORBIDDEN
        or evaluation.effective_permission is not PermissionDisposition.PERMITTED
    ):
        raise OpportunityError(forbidden)
    expected = tuple({"condition": condition.model_dump(), "satisfied": True} for condition in grant.conditions)
    if tuple(item.model_dump() for item in evaluation.condition_evidence) != expected or any(
        item.model_dump().get("satisfied") is not True for item in evaluation.condition_evidence
    ):
        raise OpportunityError(forbidden)
    if grant.source_kind == "manual-import" and (
        grant.credential_ref is not None or grant.account_binding_digest is not None
    ):
        raise OpportunityError(StopCode.M9_CREDENTIAL_REFERENCE_INVALID)


def _page_rules(page: SourcePageResult | SnapshotPage, grant: SourceCapabilityGrant) -> tuple[SourceDataRule, ...]:
    rules = {rule.data_class: rule for rule in grant.data_rules}
    if (
        len(rules) != len(grant.data_rules)
        or not page.data_classes
        or any(key not in rules for key in page.data_classes)
    ):
        raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
    return tuple(rules[key] for key in page.data_classes)


def page_clocks(
    page: SourcePageResult | SnapshotPage, grant: SourceCapabilityGrant, *, captured_at: datetime
) -> tuple[EvidenceDataClassClock, ...]:
    """Stamp once at DB admission after I/O; callers retain these immutable clocks."""
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
    return tuple(
        EvidenceDataClassClock(
            data_class=rule.data_class,
            captured_at=captured_at,
            refresh_due_at=(captured_at + timedelta(seconds=rule.refresh_interval_seconds))
            if rule.refresh_interval_seconds is not None
            else None,
            retention_due_at=(captured_at + timedelta(seconds=rule.retention_seconds))
            if rule.retention_seconds is not None
            else None,
        )
        for rule in _page_rules(page, grant)
    )


def page_deadlines(clocks: Sequence[EvidenceDataClassClock]) -> tuple[datetime | None, datetime | None]:
    if not clocks or len({clock.data_class for clock in clocks}) != len(clocks):
        raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
    return (
        min((c.refresh_due_at for c in clocks if c.refresh_due_at is not None), default=None),
        min((c.retention_due_at for c in clocks if c.retention_due_at is not None), default=None),
    )


def require_clocks_current(clocks: Sequence[EvidenceDataClassClock], *, now: datetime, operational: bool) -> None:
    refresh, retention = page_deadlines(clocks)
    if retention is not None and now >= retention:
        raise OpportunityError(StopCode.M9_EVIDENCE_RETENTION_EXPIRED)
    if operational and refresh is not None and now >= refresh:
        raise OpportunityError(StopCode.M9_EVIDENCE_STALE)


def retain_page_proof(page: SourcePageResult | SnapshotPage, grant: SourceCapabilityGrant) -> bool:
    return all(rule.digest_proof_may_be_retained for rule in _page_rules(page, grant))
