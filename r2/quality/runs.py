"""Pure M10 run closure and validity projection; sealing records completeness, never acceptability.

Only TECHNICAL/DETERMINISTIC (A4 receipts) and NARRATIVE/HUMAN (qualified showrunner) evidence is
admitted. Every other kind or assessor class, including FACTUAL, fails closed until an accepted producer
exists. Callers must re-verify each observation's stored custody before admitting it here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import model_validator

import r2.contracts.quality as q
from r2.advanced_creative.digests import digest_canonical
from r2.quality.digests import compute_digest, verify_caches
from r2.quality.errors import ProfileStaleError, RequiredEvidenceMissingError, SubjectStaleError

HUMAN_SHOWRUNNER_POLICY_ID = "m10.qualification.human-showrunner.v1"
_HUMAN_SHOWRUNNER_POLICY = {
    "policy_id": HUMAN_SHOWRUNNER_POLICY_ID,
    "proof": "current signed HUMAN_SHOWRUNNER governance grant for the exact user, project and principal",
    "independence_group": "human:<principal>",
}
_KIND = {
    q.ObservationType.TECHNICAL: q.AssessorKind.TECHNICAL,
    q.ObservationType.FACTUAL: q.AssessorKind.FACTUAL,
    q.ObservationType.NARRATIVE: q.AssessorKind.NARRATIVE,
    q.ObservationType.CONTINUITY: q.AssessorKind.CONTINUITY,
    q.ObservationType.PERCEPTUAL_REGRESSION: q.AssessorKind.PERCEPTUAL,
    q.ObservationType.PERCEPTUAL_REVIEW: q.AssessorKind.PERCEPTUAL,
    q.ObservationType.ACCESSIBILITY: q.AssessorKind.ACCESSIBILITY,
}
_ADMITTED = {
    (q.ObservationType.TECHNICAL, q.AssessorClass.DETERMINISTIC): "m10.technical-observation.v1",
    (q.ObservationType.NARRATIVE, q.AssessorClass.HUMAN): "m10.narrative-observation.v1",
}

type AdmittedBody = q.TechnicalObservation | q.NarrativeObservation
type RunValidityState = Literal["CURRENT", "STALE", "SUPERSEDED", "EXPIRED", "INVALIDATED"]
type SlotState = Literal["SATISFIED", "NOT_APPLICABLE", "FAILED", "INDETERMINATE"]
type _Assessed = SlotState | Literal["DISAGREEMENT"]


def _private_digest(domain: str, body: object) -> str:
    return digest_canonical({"domain": domain, "contract_version": "1", "body": body})


def human_showrunner_policy_digest() -> str:
    return _private_digest("m10.qualification-policy.v1", _HUMAN_SHOWRUNNER_POLICY)


def run_digest(run: q.QualityRun) -> str:
    return compute_digest("m10.quality-run.v1", q.QualityRun.model_validate(run))


class HumanObservationRequest(q.M10ContractModel):
    """A showrunner's rubric judgment; identity, qualification, independence and digests are host-derived."""

    user_id: q.ExactIdentity
    project_name: q.ExactIdentity
    actor_id: q.ExactIdentity
    command_id: q.ExactIdentity
    subject: q.AssessedSubject
    profile: q.QualityProfileRevision
    requirement_id: q.ExactIdentity
    slot_id: q.ExactIdentity
    status: q.ObservationStatus
    rubric_id: q.ExactIdentity
    rubric_digest: q.Sha256Digest
    segment_closure_digest: q.Sha256Digest
    reviewer_evidence_digest: q.Sha256Digest
    findings: tuple[q.QualityFinding, ...]
    evidence_refs: tuple[q.ExactIdentity, ...]
    evidence_digest: q.Sha256Digest

    @model_validator(mode="after")
    def coherent_scope(self) -> Self:
        scope = (self.user_id, self.project_name)
        binding = self.subject.master_binding
        if scope != (self.profile.user_id, self.profile.project_name) or scope != (
            binding.user_id,
            binding.project_name,
        ):
            raise ValueError("human observation scope mismatch")
        return self


def human_request_digest(request: HumanObservationRequest) -> str:
    return _private_digest("m10.human-observation-request.v1", HumanObservationRequest.model_validate(request))


@dataclass(frozen=True)
class AdmittedObservation:
    """An observation whose stored custody the caller already re-verified, with its producing class."""

    observation: AdmittedBody
    assessor_class: q.AssessorClass


@dataclass(frozen=True)
class _Evaluated:
    requirement: q.AssessmentRequirement
    slot: q.AssessmentSlot
    observations: tuple[AdmittedBody, ...]


def _admit(
    item: AdmittedObservation,
    slots: dict[tuple[str, str], tuple[q.AssessmentRequirement, q.AssessmentSlot]],
    *,
    subject_digest: str,
    policy: q.QualityPolicyV1,
) -> tuple[tuple[str, str], q.ObservationBinding]:
    observation = item.observation
    key = (observation.requirement_id, observation.slot_id)
    placement = slots.get(key)
    domain = _ADMITTED.get((observation.observation_type, item.assessor_class))
    if placement is None or domain is None:
        raise RequiredEvidenceMissingError()
    _, slot = placement
    if (_KIND[observation.observation_type], item.assessor_class) != (slot.kind, slot.assessor_class):
        raise RequiredEvidenceMissingError()
    if observation.subject_digest != subject_digest:
        raise SubjectStaleError()
    if observation.status not in slot.allowed_applicability_states:
        raise RequiredEvidenceMissingError()
    if observation.producer_conflict and slot.producer_conflict_forbidden:
        raise RequiredEvidenceMissingError()
    if isinstance(observation, q.TechnicalObservation):
        rule = next((rule for rule in policy.probe_rules if rule.rule_id == observation.rule_id), None)
        if rule is None or observation.rule_id not in slot.rule_ids:
            raise RequiredEvidenceMissingError()
        if observation.config_digest != rule.config_digest:
            raise ProfileStaleError()
    else:
        if observation.status == q.ObservationStatus.INAPPLICABLE:
            raise RequiredEvidenceMissingError()
        if (slot.qualification_policy_id, slot.qualification_policy_digest) != (
            HUMAN_SHOWRUNNER_POLICY_ID,
            human_showrunner_policy_digest(),
        ):
            raise RequiredEvidenceMissingError()
    binding = q.ObservationBinding(
        observation_id=observation.observation_id,
        observation_type=observation.observation_type,
        observation_digest=compute_digest(domain, observation),
        requirement_id=observation.requirement_id,
        slot_id=observation.slot_id,
    )
    return (key, binding)


def _slot_state(slot: q.AssessmentSlot, observations: tuple[AdmittedBody, ...]) -> _Assessed:
    statuses = {o.status for o in observations}
    if len({o.independence_group for o in observations}) < slot.required_independence_groups:
        return "INDETERMINATE"
    if q.ObservationStatus.INDETERMINATE in statuses:
        return "INDETERMINATE"
    if q.ObservationStatus.FAIL in statuses and q.ObservationStatus.PASS in statuses:
        return "DISAGREEMENT"
    if q.ObservationStatus.FAIL in statuses:
        return "FAILED"
    if q.ObservationStatus.PASS in statuses:
        return "SATISFIED"
    return "NOT_APPLICABLE"


def close_run(
    profile: q.QualityProfileRevision,
    subject: q.AssessedSubject,
    observations: Sequence[AdmittedObservation],
    *,
    run_id: str,
    completed_at: datetime,
) -> q.QualityRun:
    """Seal complete evidence into a `QualityRun`; every digest is recomputed, none is trusted."""
    profile = q.QualityProfileRevision.model_validate(profile)
    subject = q.AssessedSubject.model_validate(subject)
    try:
        verify_caches(profile)
        verify_caches(subject)
    except ValueError:
        raise RequiredEvidenceMissingError() from None
    policy = profile.policy
    subject_digest = compute_digest("m10.assessed-subject.v1", subject)
    slots = {
        (requirement.requirement_id, slot.slot_id): (requirement, slot)
        for requirement in policy.assessment_requirements
        for slot in requirement.slots
    }
    grouped: dict[tuple[str, str], list[AdmittedBody]] = {}
    bindings: list[q.ObservationBinding] = []
    for item in observations:
        key, binding = _admit(item, slots, subject_digest=subject_digest, policy=policy)
        if any(existing.observation_id == binding.observation_id for existing in bindings):
            raise RequiredEvidenceMissingError()
        bindings.append(binding)
        grouped.setdefault(key, []).append(item.observation)
    escalation_targets = {r.escalation_requirement_id for r in policy.assessment_requirements} - {None}
    evaluated: dict[str, list[_Evaluated]] = {}
    for requirement in policy.assessment_requirements:
        present = [
            _Evaluated(requirement, slot, tuple(grouped[(requirement.requirement_id, slot.slot_id)]))
            for slot in requirement.slots
            if (requirement.requirement_id, slot.slot_id) in grouped
        ]
        if requirement.requirement_id in escalation_targets and not present:
            evaluated[requirement.requirement_id] = []
            continue
        needed = (
            len(requirement.slots) if requirement.mode == q.RequirementMode.ALL else requirement.minimum_satisfied_slots
        )
        if len(present) < needed:
            raise RequiredEvidenceMissingError()
        evaluated[requirement.requirement_id] = present
    states: dict[tuple[str, str], _Assessed] = {
        (item.requirement.requirement_id, item.slot.slot_id): _slot_state(item.slot, item.observations)
        for items in evaluated.values()
        for item in items
    }
    results: list[q.AssessmentSlotResult] = []
    for requirement in policy.assessment_requirements:
        items = evaluated[requirement.requirement_id]
        own = {states[(requirement.requirement_id, item.slot.slot_id)] for item in items}
        disagreement = "DISAGREEMENT" in own or {"SATISFIED", "FAILED"} <= own
        escalation: tuple[str, ...] = ()
        resolved: SlotState | None = None
        if disagreement:
            target = requirement.escalation_requirement_id
            arbiters = evaluated.get(target, []) if target is not None else []
            escalation = tuple(sorted(o.observation_id for item in arbiters for o in item.observations))
            arbiter_states = {states[(target, item.slot.slot_id)] for item in arbiters} if target else set()
            resolved = "INDETERMINATE"
            if arbiter_states == {"SATISFIED"}:
                resolved = "SATISFIED"
            elif arbiter_states == {"FAILED"}:
                resolved = "FAILED"
        finals: dict[str, SlotState] = {}
        for item in items:
            assessed = states[(requirement.requirement_id, item.slot.slot_id)]
            state: SlotState = "INDETERMINATE" if assessed == "DISAGREEMENT" else assessed
            # Escalation resolves only judgment disagreement, never an independence or admission deficiency.
            if disagreement and assessed in {"SATISFIED", "FAILED", "DISAGREEMENT"}:
                state = resolved or "INDETERMINATE"
            finals[item.slot.slot_id] = state
        groups = {item.slot.slot_id: {o.independence_group for o in item.observations} for item in items}
        counted = [slot_id for slot_id, state in finals.items() if state != "INDETERMINATE"]
        for slot_id in counted:
            if any(other != slot_id and groups[slot_id] & groups[other] for other in counted):
                finals[slot_id] = "INDETERMINATE"
        for item in items:
            ordered = sorted(item.observations, key=lambda o: o.observation_id)
            results.append(
                q.AssessmentSlotResult(
                    requirement_id=requirement.requirement_id,
                    slot_id=item.slot.slot_id,
                    observation_refs=tuple(o.observation_id for o in ordered),
                    observation_digests=tuple(
                        next(b.observation_digest for b in bindings if b.observation_id == o.observation_id)
                        for o in ordered
                    ),
                    distinct_independence_groups=tuple(sorted({o.independence_group for o in ordered})),
                    state=finals[item.slot.slot_id],
                    escalation_observation_refs=escalation,
                )
            )
    closure = q.RunCompletionSubject.observation_order(tuple(bindings))
    technical = sorted(
        {
            item.observation.probe_receipt_ref
            for item in observations
            if isinstance(item.observation, q.TechnicalObservation)
        }
    )
    return q.QualityRun(
        run_id=run_id,
        subject=subject,
        subject_digest=subject_digest,
        profile_id=profile.profile_id,
        profile_revision=profile.revision,
        profile_digest=profile.profile_digest,
        observation_refs=tuple(binding.observation_id for binding in closure),
        observation_closure_digest=compute_digest("m10.observation-closure.v1", closure),
        slot_results=tuple(results),
        requirements_digest=compute_digest("m10.assessment-requirements.v1", policy.assessment_requirements),
        execution_refs=tuple(technical),
        completed_at=completed_at,
    )


@dataclass(frozen=True)
class ValidityInputs:
    """Current facts read by the host; the projection never reads storage itself."""

    evidence_intact: bool
    subject_current: bool
    newer_run: bool
    newer_profile_reevaluates: bool


@dataclass(frozen=True)
class RunValidity:
    state: RunValidityState
    reasons: tuple[str, ...]


def project_validity(
    run: q.QualityRun,
    profile: q.QualityProfileRevision,
    observations: Sequence[AdmittedBody],
    inputs: ValidityInputs,
    *,
    now: datetime,
) -> RunValidity:
    """Recompute operational validity with precedence INVALIDATED > STALE > SUPERSEDED > EXPIRED > CURRENT."""
    reasons: list[str] = []
    if not inputs.evidence_intact or {o.observation_id for o in observations} != set(run.observation_refs):
        reasons.append("EVIDENCE_NOT_INTACT")
        return RunValidity("INVALIDATED", tuple(reasons))
    if not inputs.subject_current:
        return RunValidity("STALE", ("SUBJECT_NOT_CURRENT",))
    if inputs.newer_run:
        reasons.append("NEWER_RUN")
    if inputs.newer_profile_reevaluates:
        reasons.append("PROFILE_REEVALUATES")
    if reasons:
        return RunValidity("SUPERSEDED", tuple(reasons))
    reasons.extend(
        f"EXPIRED:{observation.observation_id}"
        for observation in observations
        for rule in profile.policy.freshness_rules
        if rule.evidence_kind == _KIND[observation.observation_type]
        and now - observation.observed_at > timedelta(seconds=rule.max_age_seconds)
    )
    if reasons:
        return RunValidity("EXPIRED", tuple(sorted(reasons)))
    return RunValidity("CURRENT", ())


__all__ = [
    "HUMAN_SHOWRUNNER_POLICY_ID",
    "AdmittedObservation",
    "HumanObservationRequest",
    "RunValidity",
    "ValidityInputs",
    "close_run",
    "human_request_digest",
    "human_showrunner_policy_digest",
    "project_validity",
    "run_digest",
]
