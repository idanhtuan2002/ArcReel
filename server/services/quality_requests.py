"""Server-built M10 service requests for the M10-C operator surface.

Every identity, time, binding and digest is computed here from server state and the operator's intent; the
prepared request is sealed and later passed to the accepted service unchanged.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any, Literal

import r2.contracts.quality as q
from r2.advanced_creative.exploration import uuid7
from r2.quality.digests import compute_digest, policy_domain
from r2.quality.ports import ProbeRequest
from r2.quality.runs import HumanObservationRequest
from server.services.quality_template import REQUIREMENTS, REVIEW_RULE_ID, private_digest

RUBRIC_ID = "m10-c.narrative-rubric.v1"
RUBRIC_CRITERIA = ("coherence", "on-screen-text", "audio-presence", "visible-defects")
RUBRIC_DIGEST = private_digest(RUBRIC_ID, {"criteria": list(RUBRIC_CRITERIA)})
MAX_NOTES_CHARS = 20000
MAX_FINDINGS = 32
WEEK_SECONDS = 604800
DAY_SECONDS = 86400


def _sealed_command(domain: str, body: dict[str, Any]) -> dict[str, Any]:
    body["command"]["request_digest"] = compute_digest(domain, body)
    return body


def _command(user_id: str, project_name: str, actor_id: str, operation: str, command_id: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "project_name": project_name,
        "actor_id": actor_id,
        "operation": operation,
        "command_id": command_id,
        "request_digest": "sha256:" + "0" * 64,
    }


def publication_request(
    *,
    user_id: str,
    actor_id: str,
    project_name: str,
    command_id: str,
    profile_id: str | None,
    expected_revision: int,
    cohort_id: str,
    product_surface: str,
    policy: q.QualityPolicyV2,
    supersession_effect: q.SupersessionEffect,
    now: datetime,
) -> q.ProfilePublicationAuthorizationRequest:
    draft = {
        "user_id": user_id,
        "project_name": project_name,
        "profile_id": profile_id or uuid7(),
        "revision": expected_revision + 1,
        "parent_revision": expected_revision or None,
        "cohort_id": cohort_id,
        "product_surface": product_surface,
        "policy": policy.model_dump(mode="json"),
        "policy_digest": compute_digest(policy_domain(policy), policy),
        "supersession_effect": supersession_effect,
        "created_by": actor_id,
        "created_at": now.isoformat(),
    }
    body = {
        "command": _command(user_id, project_name, actor_id, "PUBLISH_PROFILE", command_id),
        "subject": {
            "user_id": user_id,
            "project_name": project_name,
            "actor_id": actor_id,
            "profile_draft": draft,
            "profile_draft_digest": compute_digest("m10.quality-profile-draft.v1", draft),
            "expected_profile_revision": expected_revision,
        },
    }
    return q.ProfilePublicationAuthorizationRequest.model_validate(
        _sealed_command("m10.profile-publication-request.v1", body)
    )


def _slot(profile: q.QualityProfileRevision, requirement_id: str) -> q.AssessmentSlot:
    requirement = next((r for r in profile.policy.assessment_requirements if r.requirement_id == requirement_id), None)
    if requirement is None or len(requirement.slots) != 1:
        raise ValueError("unknown requirement")
    return requirement.slots[0]


def probe_request(
    *,
    user_id: str,
    actor_id: str,
    project_name: str,
    execution_ref: str,
    subject: q.AssessedSubject,
    profile: q.QualityProfileRevision,
    requirement_id: str,
) -> ProbeRequest:
    if requirement_id not in REQUIREMENTS or requirement_id == "review":
        raise ValueError("not a technical requirement")
    slot = _slot(profile, requirement_id)
    rule = next(r for r in profile.policy.probe_rules if r.rule_id in slot.rule_ids)
    return ProbeRequest.model_validate(
        {
            "user_id": user_id,
            "project_name": project_name,
            "actor_id": actor_id,
            "execution_ref": execution_ref,
            "requirement_id": requirement_id,
            "slot_id": slot.slot_id,
            "subject": subject.model_dump(mode="json"),
            "profile": profile.model_dump(mode="json"),
            "rule": rule.model_dump(mode="json"),
        }
    )


def review_request(
    *,
    user_id: str,
    actor_id: str,
    project_name: str,
    command_id: str,
    subject: q.AssessedSubject,
    profile: q.QualityProfileRevision,
    status: Literal["PASS", "FAIL"],
    criteria_verdicts: dict[str, Literal["PASS", "FAIL"]],
    findings: list[dict[str, str]],
    notes: str,
) -> HumanObservationRequest:
    if set(criteria_verdicts) != set(RUBRIC_CRITERIA) or len(notes) > MAX_NOTES_CHARS or len(findings) > MAX_FINDINGS:
        raise ValueError("review out of bounds")
    notes_digest = "sha256:" + hashlib.sha256(notes.encode("utf-8")).hexdigest()
    subject_digest = compute_digest("m10.assessed-subject.v1", subject)
    reviewer = private_digest(
        "m10-c.reviewer-evidence.v1",
        {"criteria_verdicts": dict(sorted(criteria_verdicts.items())), "notes_digest": notes_digest},
    )
    refs = ["m10-c-review:" + reviewer.removeprefix("sha256:")]
    rows = []
    for finding in findings:
        if finding["rule_id"] not in RUBRIC_CRITERIA or finding["severity"] not in {"BLOCKING", "ADVISORY"}:
            raise ValueError("finding out of bounds")
        locator = finding["locator"]
        if locator != "whole" and not (locator.startswith("t=") and locator[2:].isdigit()):
            raise ValueError("finding locator out of bounds")
        evidence = private_digest(
            "m10-c.review-finding.v1",
            {
                "rule_id": finding["rule_id"],
                "severity": finding["severity"],
                "locator": locator,
                "notes_digest": notes_digest,
            },
        )
        rows.append(
            {
                "finding_id": uuid7(),
                "rule_id": REVIEW_RULE_ID,
                "severity": finding["severity"],
                "subject_locator": f"{finding['rule_id']}@{locator}",
                "evidence_digest": evidence,
            }
        )
    slot = _slot(profile, "review")
    return HumanObservationRequest.model_validate(
        {
            "user_id": user_id,
            "project_name": project_name,
            "actor_id": actor_id,
            "command_id": command_id,
            "subject": subject.model_dump(mode="json"),
            "profile": profile.model_dump(mode="json"),
            "requirement_id": "review",
            "slot_id": slot.slot_id,
            "status": status,
            "rubric_id": RUBRIC_ID,
            "rubric_digest": RUBRIC_DIGEST,
            "segment_closure_digest": private_digest(
                "m10-c.review-segments.v1",
                {"subject_digest": subject_digest, "segments": [{"start": "0", "end": "END"}]},
            ),
            "reviewer_evidence_digest": reviewer,
            "findings": rows,
            "evidence_refs": refs,
            "evidence_digest": private_digest("m10-c.review-refs.v1", {"refs": refs}),
        }
    )


def completion_request(
    *,
    user_id: str,
    actor_id: str,
    project_name: str,
    command_id: str,
    subject: q.AssessedSubject,
    profile: q.QualityProfileRevision,
    observations: list[q.TechnicalObservation | q.NarrativeObservation],
) -> q.CompleteRunCommand:
    bindings = tuple(
        q.ObservationBinding(
            observation_id=o.observation_id,
            observation_type=o.observation_type,
            observation_digest=compute_digest(
                "m10.technical-observation.v1"
                if o.observation_type == q.ObservationType.TECHNICAL
                else "m10.narrative-observation.v1",
                o,
            ),
            requirement_id=o.requirement_id,
            slot_id=o.slot_id,
        )
        for o in observations
    )
    ordered = q.RunCompletionSubject.observation_order(bindings)
    body: dict[str, Any] = {
        "command": _command(user_id, project_name, actor_id, "COMPLETE_RUN", command_id),
        "subject": {
            "user_id": user_id,
            "project_name": project_name,
            "actor_id": actor_id,
            "run_id": uuid7(),
            "subject": subject.model_dump(mode="json"),
            "subject_digest": compute_digest("m10.assessed-subject.v1", subject),
            "profile_id": profile.profile_id,
            "profile_revision": profile.revision,
            "profile_digest": profile.profile_digest,
            "observations": [b.model_dump(mode="json") for b in ordered],
            "observation_closure_digest": compute_digest("m10.observation-closure.v1", ordered),
            "requirements_digest": compute_digest(
                "m10.assessment-requirements.v1", profile.policy.assessment_requirements
            ),
            "execution_refs": sorted(
                o.probe_receipt_ref for o in observations if isinstance(o, q.TechnicalObservation)
            ),
        },
    }
    return q.CompleteRunCommand.model_validate(_sealed_command("m10.run-completion-request.v1", body))


def bounded_expiry(policy: q.QualityPolicyFields, decision: str, requested_ttl_seconds: int, now: datetime) -> datetime:
    """`now + ttl`, refused (not widened) above the policy and decision bounds."""
    limit = min(policy.disposition_rule.max_disposition_ttl_seconds, WEEK_SECONDS)
    if decision == "WAIVE":
        limit = min(limit, policy.disposition_rule.max_waiver_ttl_seconds, DAY_SECONDS)
    if not 0 < requested_ttl_seconds <= limit:
        raise ValueError("disposition expiry out of bounds")
    return now + timedelta(seconds=requested_ttl_seconds)


def disposition_request(
    *,
    user_id: str,
    actor_id: str,
    project_name: str,
    command_id: str,
    run: q.QualityRun,
    run_digest: str,
    policy: q.QualityPolicyFields,
    decision: str,
    reason: str,
    waiver_bindings: list[dict[str, Any]],
    expected_version: int,
    requested_ttl_seconds: int,
    now: datetime,
) -> q.DispositionAuthorizationRequest:
    expires = bounded_expiry(policy, decision, requested_ttl_seconds, now)
    body: dict[str, Any] = {
        "command": _command(user_id, project_name, actor_id, "ISSUE_DISPOSITION", command_id),
        "subject": {
            "user_id": user_id,
            "project_name": project_name,
            "actor_id": actor_id,
            "subject_digest": run.subject_digest,
            "quality_run_id": run.run_id,
            "quality_run_digest": run_digest,
            "profile_id": run.profile_id,
            "profile_revision": run.profile_revision,
            "profile_digest": run.profile_digest,
            "decision": decision,
            "waiver_bindings": waiver_bindings,
            "reason": reason,
            "requested_expires_at": expires.isoformat(),
            "expected_disposition_version": expected_version,
        },
    }
    return q.DispositionAuthorizationRequest.model_validate(_sealed_command("m10.disposition-request.v1", body))


__all__ = [
    "RUBRIC_CRITERIA",
    "RUBRIC_DIGEST",
    "RUBRIC_ID",
    "bounded_expiry",
    "completion_request",
    "disposition_request",
    "probe_request",
    "publication_request",
    "review_request",
]
