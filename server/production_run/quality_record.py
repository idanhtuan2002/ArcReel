"""Record a production run's model reviews as M10 Quality evidence, a sealed run and a PASS/REWORK disposition.

Each qualified reviewer contributes one MODEL narrative observation per slot of the project's published automatic
profile; the M10 run is sealed by ``QualityRunService`` and the disposition issued by ``DispositionService``, both
under the run's automation authority, which is re-required inside their own transactions. Identities are derived
from the step command, so a replay returns the same observations, run and disposition instead of new ones.
Nothing here can WAIVE, and an observation from a reviewer whose qualification no longer stands is never admitted.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import r2.contracts.quality as q
from lib.db.models.quality import QualityProfileHeadModel
from lib.db.repositories.model_observations import ModelObservationRepository
from lib.db.repositories.quality import QualityProfileRepository
from lib.db.repositories.quality_dispositions import QualityDispositionRepository
from lib.db.repositories.quality_runs import QualityRunRepository
from r2.artifact_identity import episode_video_key
from r2.automation.assessment import AssessmentVerdict, ModelAssessment
from r2.automation.identity import digest_value
from r2.contracts.automation import AuthorizationSubject, DispatchIntent, OwnerReceipt, ReviewerQualification
from r2.contracts.common import ensure_json_value
from r2.quality.digests import compute_digest
from r2.quality.runs import run_digest
from server.production_run.evaluators import prompt_digest
from server.production_run.final_master_adapter import final_target_ref
from server.production_run.owner_support import OwnerBlocked, Sessions, current_subject
from server.services.automation_grants import RunAutomationAuthority
from server.services.quality_dispositions import AutomaticDispositionCustodian, DispositionService
from server.services.quality_requests import completion_request, disposition_request
from server.services.quality_runs import QualityRunService
from server.services.quality_subjects import resolve_assessed_subject

COMPLETION_DOMAIN = "m10.run-completion-request.v1"
RUBRIC_ID = "r2.production-review-rubric.v1"
DISPOSITION_TTL_SECONDS = 604800


def stable_uuid7(seed: str) -> str:
    """A canonical UUIDv7 derived from ``seed``: the same seed always names the same entity."""
    value = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:16], "big")
    value &= ~(0xF << 76)
    value |= 0x7 << 76
    value &= ~(0b11 << 62)
    value |= 0b10 << 62
    return str(uuid.UUID(int=value))


async def published_profile(
    sessions: Sessions, *, user_id: str, project_name: str, profile_id: str, profile_digest: str
) -> q.QualityProfileRevision:
    async with sessions() as session:
        head = await session.get(QualityProfileHeadModel, (user_id, project_name, profile_id))
        revision = head.current_revision if head is not None else None
        profile = (
            await QualityProfileRepository(session).get_revision(
                user_id=user_id, project_name=project_name, profile_id=profile_id, revision=revision
            )
            if revision is not None
            else None
        )
    if profile is None or profile.profile_digest != profile_digest:
        raise OwnerBlocked("QUALITY_PROFILE_CHANGED")
    return profile


def _observations(
    *,
    seed: str,
    profile: q.QualityProfileRevision,
    subject_digest: str,
    assessments: tuple[ModelAssessment, ...],
    qualifications: dict[str, ReviewerQualification],
    qualification_digests: dict[str, str],
) -> list[q.NarrativeObservation]:
    slots = [
        (requirement.requirement_id, slot)
        for requirement in profile.policy.assessment_requirements
        for slot in requirement.slots
        if slot.assessor_class is q.AssessorClass.MODEL
    ]
    if not slots:
        raise OwnerBlocked("PROFILE_MODEL_ASSESSMENT_INCOMPLETE")
    observations = []
    for review in assessments:
        record = qualifications.get(review.model_identity)
        if record is None:
            raise OwnerBlocked("REVIEWER_NOT_QUALIFIED")
        for requirement_id, slot in slots:
            key = f"{seed}:{review.model_identity}:{requirement_id}:{slot.slot_id}"
            findings = tuple(
                q.QualityFinding(
                    finding_id=stable_uuid7(f"{key}:finding:{index}"),
                    rule_id=slot.rule_ids[0],
                    severity="BLOCKING" if finding.severity in {"CRITICAL", "MAJOR"} else "ADVISORY",
                    subject_locator=f"{finding.code}@whole",
                    evidence_digest=digest_value(
                        "r2.production-review-finding.v1", ensure_json_value(finding.model_dump(mode="json"))
                    ),
                )
                for index, finding in enumerate(review.findings)
            )
            refs = (f"production-review:{review.evidence_digest.removeprefix('sha256:')}",)
            observations.append(
                q.NarrativeObservation(
                    observation_id=stable_uuid7(key),
                    observation_type=q.ObservationType.NARRATIVE,
                    requirement_id=requirement_id,
                    slot_id=slot.slot_id,
                    assessor_identity=record.model_identity,
                    assessor_version=review.prompt_digest,
                    assessor_qualification_ref=qualification_digests[review.model_identity],
                    assessor_qualification_digest=qualification_digests[review.model_identity],
                    independence_group="model:" + record.model_identity,
                    producer_conflict=False,
                    config_digest=record.config_digest,
                    subject_digest=subject_digest,
                    status=q.ObservationStatus.PASS if review.accepts() else q.ObservationStatus.FAIL,
                    findings=findings,
                    evidence_refs=refs,
                    evidence_digest=digest_value("r2.production-review-refs.v1", {"refs": list(refs)}),
                    observed_at=datetime.now(UTC),
                    rubric_id=RUBRIC_ID,
                    rubric_digest=prompt_digest(),
                    segment_closure_digest=digest_value(
                        "r2.production-review-segments.v1", {"subject": subject_digest, "segments": ["whole"]}
                    ),
                    reviewer_evidence_digest=review.evidence_digest,
                )
            )
    return observations


async def record_quality(
    sessions: Sessions,
    *,
    authority: RunAutomationAuthority,
    intent: DispatchIntent,
    subject_digest: str,
    project_root: Path,
    episode: int,
    profile_id: str,
    profile_digest: str,
    assessments: tuple[ModelAssessment, ...],
    verdict: AssessmentVerdict,
    qualifications: dict[str, ReviewerQualification],
    qualification_digests: dict[str, str],
) -> OwnerReceipt:
    """The episode's M10 disposition receipt; PASS only when the sealed M10 run supports it."""
    if verdict.kind not in {"PASS", "REWORK"}:
        raise OwnerBlocked(verdict.reason or "REQUIRED_EVIDENCE_MISSING")
    scope = intent.scope
    seed = f"{intent.identity.command_id}:e{episode}"
    principal_subject = await current_subject(sessions, intent, subject_digest=subject_digest)
    async with sessions() as session, session.begin():
        proof = await authority.require_locked(session, subject=principal_subject)
    actor = proof.principal
    profile = await published_profile(
        sessions,
        user_id=scope.user_id,
        project_name=scope.project_name,
        profile_id=profile_id,
        profile_digest=profile_digest,
    )
    async with sessions() as session:
        assessed = await resolve_assessed_subject(
            session,
            project_root,
            user_id=scope.user_id,
            project_name=scope.project_name,
            root_artifact_key=episode_video_key(episode, final_target_ref(episode)),
        )
    m10_subject = compute_digest("m10.assessed-subject.v1", assessed)
    observations = _observations(
        seed=seed,
        profile=profile,
        subject_digest=m10_subject,
        assessments=assessments,
        qualifications=qualifications,
        qualification_digests=qualification_digests,
    )
    async with sessions() as session, session.begin():
        await authority.require_locked(session, subject=principal_subject)
        for observation in observations:
            await ModelObservationRepository(session).record(
                user_id=scope.user_id,
                project_name=scope.project_name,
                run_id=scope.run_id,
                profile=profile,
                observation=observation,
            )

    async def guard(session) -> None:
        if session is None:
            async with sessions() as fresh, fresh.begin():
                current = await authority.require_locked(fresh, subject=principal_subject)
        else:
            current = await authority.require_locked(session, subject=principal_subject)
        if current != proof:
            raise PermissionError("AUTOMATION_AUTHORITY_PROJECTION_MISMATCH")

    built = completion_request(
        user_id=scope.user_id,
        actor_id=actor,
        project_name=scope.project_name,
        command_id=f"auto-complete:{seed}",
        subject=assessed,
        profile=profile,
        observations=list(observations),
    ).model_dump(mode="json")
    built["subject"]["run_id"] = stable_uuid7(f"{seed}:run")
    built["command"]["request_digest"] = "sha256:" + "0" * 64
    built["command"]["request_digest"] = compute_digest(COMPLETION_DOMAIN, built)
    command = q.CompleteRunCommand.model_validate(built)

    async def reader():
        return authority.reader

    run = await QualityRunService.for_automation(
        command, sessions, guard=guard, grant_reader=reader, project_root=project_root
    ).complete(command)

    async with sessions() as session:
        disposition_head = await QualityDispositionRepository(session).head_disposition(
            user_id=scope.user_id,
            project_name=scope.project_name,
            subject_digest=run.subject_digest,
            profile_id=run.profile_id,
        )
        head_run = await QualityRunRepository(session).head(
            user_id=scope.user_id,
            project_name=scope.project_name,
            subject_digest=run.subject_digest,
            profile_id=run.profile_id,
        )
    if head_run != run.run_id:
        raise OwnerBlocked("QUALITY_RUN_SUPERSEDED")
    disposition = disposition_head if disposition_head and disposition_head.quality_run_id == run.run_id else None
    if disposition is None:
        async with sessions() as session, session.begin():
            _, version = await QualityDispositionRepository(session).lock_head(
                user_id=scope.user_id,
                project_name=scope.project_name,
                subject_digest=run.subject_digest,
                profile_id=run.profile_id,
            )
        request = disposition_request(
            user_id=scope.user_id,
            actor_id=actor,
            project_name=scope.project_name,
            command_id=f"auto-disposition:{seed}",
            run=run,
            run_digest=run_digest(run),
            policy=profile.policy,
            decision=verdict.kind,
            reason="automatic production review",
            waiver_bindings=[],
            expected_version=version,
            requested_ttl_seconds=min(
                DISPOSITION_TTL_SECONDS, profile.policy.disposition_rule.max_disposition_ttl_seconds
            ),
            now=datetime.now(UTC),
        )
        custodian = AutomaticDispositionCustodian(
            request, sessions, authority=authority, subject=AuthorizationSubject.model_validate(principal_subject)
        )
        disposition = await DispositionService(sessions, custodian=custodian, project_root=project_root).issue(request)
    if disposition.decision != q.DispositionDecision(verdict.kind):
        raise OwnerBlocked("QUALITY_DISPOSITION_MISMATCH")
    return OwnerReceipt(
        owner="quality",
        receipt_ref=f"episode:{episode}:quality@{disposition.disposition_id}",
        digest=compute_digest("m10.quality-disposition.v1", disposition),
    )


__all__ = ["published_profile", "record_quality", "stable_uuid7"]
