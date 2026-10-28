"""Pure M10 disposition admissibility and readiness; a decision never repairs or exports anything.

PASS needs every requirement met. WAIVE covers exactly the failed slots whose rules the profile marks
waiverable; incomplete (INDETERMINATE) evidence and non-waivable codes are never waived. REWORK is always
admissible and only routes the unmet slots back for repair. Times are supplied by the host from PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import r2.contracts.quality as q
from r2.quality.errors import DispositionStaleError, DispositionUnauthorizedError, WaiverForbiddenError

type ReadinessState = Literal["READY", "NOT_READY"]
_A1_MAX_DISPOSITION_SECONDS = 604800
_A1_MAX_WAIVER_SECONDS = 86400


def unmet_slots(profile: q.QualityProfileRevision, run: q.QualityRun) -> tuple[tuple[str, str, str], ...]:
    """(requirement, slot, state) of every slot that keeps a counted requirement from being met."""
    policy = q.QualityProfileRevision.model_validate(profile).policy
    results = {(r.requirement_id, r.slot_id): r.state for r in run.slot_results}
    escalation_targets = {r.escalation_requirement_id for r in policy.assessment_requirements} - {None}
    unmet: list[tuple[str, str, str]] = []
    for requirement in policy.assessment_requirements:
        present = [
            (slot.slot_id, results[(requirement.requirement_id, slot.slot_id)])
            for slot in requirement.slots
            if (requirement.requirement_id, slot.slot_id) in results
        ]
        if requirement.requirement_id in escalation_targets and not present:
            continue
        satisfied = [slot for slot, state in present if state in {"SATISFIED", "NOT_APPLICABLE"}]
        needed = (
            len(requirement.slots) if requirement.mode == q.RequirementMode.ALL else requirement.minimum_satisfied_slots
        )
        failing = [
            (requirement.requirement_id, slot, state)
            for slot, state in present
            if state not in {"SATISFIED", "NOT_APPLICABLE"}
        ]
        missing = {slot.slot_id for slot in requirement.slots} - {slot for slot, _ in present}
        unmet.extend(failing)
        if len(satisfied) < needed:
            unmet.extend((requirement.requirement_id, slot, "MISSING") for slot in sorted(missing))
    return tuple(sorted(unmet))


def _check_expiry(profile: q.QualityProfileRevision, subject: q.DispositionSubject, now: datetime) -> None:
    rule = profile.policy.disposition_rule
    remaining = (subject.requested_expires_at - now).total_seconds()
    if remaining <= 0:
        raise DispositionStaleError()
    if remaining > min(rule.max_disposition_ttl_seconds, _A1_MAX_DISPOSITION_SECONDS):
        raise WaiverForbiddenError()
    if subject.decision == q.DispositionDecision.WAIVE and remaining > min(
        rule.max_waiver_ttl_seconds, _A1_MAX_WAIVER_SECONDS
    ):
        raise WaiverForbiddenError()


type _Observed = q.TechnicalObservation | q.NarrativeObservation


def waiver_requirements(
    profile: q.QualityProfileRevision, run: q.QualityRun, observations: tuple[_Observed, ...] | list[_Observed]
) -> set[tuple[str, str | None, str]]:
    """(rule, finding, scope) of every BLOCKING finding behind a failed slot; refuses what can never be waived."""
    rule = profile.policy.disposition_rule
    slots = {
        (requirement.requirement_id, slot.slot_id): slot
        for requirement in profile.policy.assessment_requirements
        for slot in requirement.slots
    }
    unmet = unmet_slots(profile, run)
    if not unmet or any(state != "FAILED" for _, _, state in unmet):
        raise WaiverForbiddenError()
    required: set[tuple[str, str | None, str]] = set()
    for requirement_id, slot_id, _ in unmet:
        findings = [
            finding
            for observation in observations
            if (observation.requirement_id, observation.slot_id) == (requirement_id, slot_id)
            and observation.status == q.ObservationStatus.FAIL
            for finding in observation.findings
            if finding.severity == "BLOCKING"
        ]
        if not findings:
            raise WaiverForbiddenError()
        for finding in findings:
            if (
                finding.rule_id not in slots[(requirement_id, slot_id)].rule_ids
                or finding.rule_id not in rule.waiverable_rule_ids
                or finding.rule_id in rule.non_waiverable_failure_codes
            ):
                raise WaiverForbiddenError()
            required.add((finding.rule_id, finding.finding_id, f"{requirement_id}:{slot_id}"))
    return required


def evaluate_decision(
    profile: q.QualityProfileRevision,
    run: q.QualityRun,
    subject: q.DispositionSubject,
    *,
    now: datetime,
    observations: tuple[_Observed, ...] | list[_Observed] = (),
) -> None:
    """Refuse a decision the sealed run does not support; the caller has verified run currentness."""
    profile = q.QualityProfileRevision.model_validate(profile)
    subject = q.DispositionSubject.model_validate(subject)
    if (subject.quality_run_id, subject.subject_digest, subject.profile_id, subject.profile_revision) != (
        run.run_id,
        run.subject_digest,
        run.profile_id,
        run.profile_revision,
    ) or subject.profile_digest != profile.profile_digest:
        raise DispositionStaleError()
    _check_expiry(profile, subject, now)
    unmet = unmet_slots(profile, run)
    if subject.decision == q.DispositionDecision.PASS:
        if unmet:
            raise DispositionUnauthorizedError()
        return
    if subject.decision == q.DispositionDecision.REWORK:
        return
    required = waiver_requirements(profile, run, observations)
    covered = {(binding.rule_id, binding.finding_id, binding.scope) for binding in subject.waiver_bindings}
    if covered != required:
        raise WaiverForbiddenError()


@dataclass(frozen=True)
class Readiness:
    state: ReadinessState
    reasons: tuple[str, ...]
    repair_slots: tuple[tuple[str, str], ...]


def project_readiness(
    disposition: q.QualityDisposition | None,
    profile: q.QualityProfileRevision,
    run: q.QualityRun,
    *,
    run_state: str,
    run_is_head: bool,
    now: datetime,
    observations: tuple[_Observed, ...] | list[_Observed] = (),
) -> Readiness:
    """READY only for an unexpired PASS/WAIVE bound to the current head run; everything else is NOT_READY."""
    repair = tuple((requirement, slot) for requirement, slot, _ in unmet_slots(profile, run))
    if disposition is None:
        return Readiness("NOT_READY", ("NO_DISPOSITION",), repair)
    reasons: list[str] = []
    if (disposition.quality_run_id, disposition.subject_digest, disposition.profile_digest) != (
        run.run_id,
        run.subject_digest,
        run.profile_digest,
    ):
        reasons.append("DISPOSITION_NOT_FOR_RUN")
    if run_state != "CURRENT":
        reasons.append("RUN_" + run_state)
    if not run_is_head:
        reasons.append("NEWER_RUN")
    if disposition.expires_at <= now:
        reasons.append("DISPOSITION_EXPIRED")
    if disposition.decision == q.DispositionDecision.REWORK:
        reasons.append("REWORK")
    elif disposition.decision == q.DispositionDecision.WAIVE:
        waived = {(binding.rule_id, binding.finding_id, binding.scope) for binding in disposition.waiver_bindings}
        try:
            required = waiver_requirements(profile, run, observations)
        except WaiverForbiddenError:
            required = set()
        if not required or waived != required:
            reasons.append("WAIVER_COVERAGE_CHANGED")
    elif repair:
        reasons.append("REQUIREMENTS_UNMET")
    return Readiness("READY" if not reasons else "NOT_READY", tuple(reasons), repair)


__all__ = ["Readiness", "evaluate_decision", "project_readiness", "unmet_slots", "waiver_requirements"]
