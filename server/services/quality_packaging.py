"""M10-B packaging check: one deterministic, package-scoped observation per check command.

Receipt-first: an exact replay returns the recorded observation before any live read. Facts come only from
verified evidence: the M8 revision, the sealed run and its CONTAINER_STREAM probe result, the published V2
profile and host re-hashed asset bytes. Nothing here selects, exports or writes Production Authority.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import os
import stat
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from pathlib import Path, PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.repositories.advanced_creative import ExplorationRepository
from lib.db.repositories.quality import QualityProfileRepository
from lib.db.repositories.quality_packaging import PackagingObservationRepository
from lib.db.repositories.quality_runs import QualityRunRepository
from r2.advanced_creative.digests import digest_canonical, digest_payload
from r2.advanced_creative.exploration import uuid7
from r2.contracts import packaging as p
from r2.contracts import quality as q
from r2.contracts.advanced_creative import ExplorationKind, PackagingCandidate
from r2.quality.digests import compute_digest
from r2.quality.errors import ProfileStaleError, RequiredEvidenceMissingError, SubjectStaleError
from r2.quality.packaging_check import (
    CHECKS,
    PackagingCheckResult,
    PackagingFacts,
    RuleOutcome,
    VerifiedAsset,
    check_package,
)
from r2.quality.probes import ContainerFacts
from r2.quality.runs import run_digest

ASSESSOR_IDENTITY = "host-packaging-check"
ASSESSOR_VERSION = "host-packaging-v1"
INDEPENDENCE_GROUP = "host-deterministic-packaging"
REQUIREMENT_ID = "m10.packaging"
SLOT_ID = "package-check"
#: The check implementation identity: its version and the closed set of checks it runs.
CHECK_CONFIG_DIGEST = digest_canonical(
    {"domain": "m10.packaging-check-config.v1", "version": ASSESSOR_VERSION, "checks": sorted(CHECKS)}
)

type Sessions = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"ftyp", 4, "video/mp4"),
)
_TEXT_TYPES = frozenset({"application/json", "text/plain", "application/x-subrip"})


def _sniff(prefix: bytes, declared: str) -> str:
    """The media type the bytes prove; text types are accepted only as valid UTF-8."""
    for signature, offset, media_type in _SIGNATURES:
        if prefix[offset : offset + len(signature)] == signature:
            return media_type
    if declared in _TEXT_TYPES:
        try:
            prefix.decode("utf-8")
        except UnicodeDecodeError:
            return "application/octet-stream"
        return declared
    return "application/octet-stream"


def _measure(root: Path, source_ref: str, declared: str) -> VerifiedAsset | None:
    """Hash one regular file under the project root without following links; None when it is not safe."""
    relative = PurePosixPath(source_ref)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    path = root.joinpath(*relative.parts)
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root.resolve(strict=True)):
            return None
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    digest = hashlib.sha256()
    size = 0
    prefix = b""
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            return None
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            if not prefix:
                prefix = chunk[:64]
            digest.update(chunk)
            size += len(chunk)
    return VerifiedAsset("sha256:" + digest.hexdigest(), size, _sniff(prefix, declared))


def _master_facts(result_facts: ContainerFacts) -> tuple[int, int, int]:
    video = [stream for stream in result_facts.streams if stream.kind == "VIDEO"]
    if len(video) != 1 or video[0].width is None or video[0].height is None:
        raise RequiredEvidenceMissingError()
    duration = result_facts.duration.as_fraction()
    return int(duration * 1000), video[0].width, video[0].height


def _finding(outcome: RuleOutcome) -> q.QualityFinding:
    return q.QualityFinding(
        finding_id=uuid7(),
        rule_id=outcome.rule_id,
        severity=outcome.severity,
        subject_locator=outcome.locator,
        evidence_digest=digest_canonical(
            {"domain": "m10.packaging-finding.v1", "check_id": outcome.check_id, "code": outcome.code}
        ),
    )


class PackagingCheckService:
    def __init__(
        self,
        *,
        sessions: Sessions,
        project_root: Path,
        clock: Callable[[], datetime],
        measure: Callable[[Path, str, str], VerifiedAsset | None] = _measure,
    ) -> None:
        self._sessions = sessions
        self._project_root = project_root
        self._clock = clock
        self._measure = measure

    async def check(self, request: p.PackageCheckRequest) -> p.PackagingObservation:
        if request.command.request_digest != compute_digest("m10.package-check-request.v1", request):
            raise RequiredEvidenceMissingError()
        async with self._sessions() as session, session.begin():
            repository = PackagingObservationRepository(session)
            await repository.lock_command(request)
            replayed = await repository.replay(request)
        if replayed is not None:
            return replayed
        candidate, facts, constraints, master = await self._inputs(request)
        measured = await asyncio.to_thread(self._assets, candidate, master)
        facts = dataclasses.replace(facts, assets=measured)
        result = check_package(candidate, constraints, facts)
        observation = self._observation(request, candidate, result, facts)
        async with self._sessions() as session, session.begin():
            repository = PackagingObservationRepository(session)
            await repository.lock_command(request)
            replayed = await repository.replay(request)
            if replayed is not None:
                return replayed
            await repository.stage(request, observation, self._clock())
        return observation

    def _assets(
        self, candidate: PackagingCandidate, master: tuple[str, str]
    ) -> dict[tuple[str, str | None], VerifiedAsset]:
        """Re-hash every declared asset; the primary video must be the approved master object itself."""
        master_path, master_digest = master
        measured: dict[tuple[str, str | None], VerifiedAsset] = {}
        for asset in candidate.assets:
            verified = self._measure(self._project_root, asset.source_ref, asset.media_type)
            if verified is None:
                continue
            if (asset.role, asset.variant_id) == ("video", None) and (
                self._project_root.joinpath(*PurePosixPath(asset.source_ref).parts).resolve()
                != Path(master_path).resolve()
                or verified.content_digest != master_digest
            ):
                continue
            measured[(asset.role, asset.variant_id)] = verified
        return measured

    async def _inputs(
        self, request: p.PackageCheckRequest
    ) -> tuple[PackagingCandidate, PackagingFacts, q.PlatformConstraintSnapshot, tuple[str, str]]:
        subject = request.subject
        user_id, project_name = subject.user_id, subject.project_name
        async with self._sessions() as session:
            m8 = ExplorationRepository(session)
            revision = await m8.get_exact(
                user_id=user_id,
                project_name=project_name,
                candidate_id=subject.candidate_id,
                revision=subject.candidate_revision,
            )
            head = await m8.get_head(user_id=user_id, project_name=project_name, candidate_id=subject.candidate_id)
            current = (
                None
                if head is None
                else await m8.get_exact(
                    user_id=user_id,
                    project_name=project_name,
                    candidate_id=subject.candidate_id,
                    revision=head.current_revision,
                )
            )
            if (
                revision is None
                or current is None
                or revision.kind is not ExplorationKind.PACKAGING
                or current.kind is not ExplorationKind.PACKAGING
                or not isinstance(revision.payload, PackagingCandidate)
                or revision.payload_digest != subject.candidate_payload_digest
                or digest_payload(revision.payload, revision.lineage) != revision.payload_digest
            ):
                raise SubjectStaleError()
            runs = QualityRunRepository(session)
            run = await runs.run(user_id=user_id, project_name=project_name, run_id=subject.quality_run_id)
            if run is None or run_digest(run) != subject.quality_run_digest:
                raise SubjectStaleError()
            profile = await QualityProfileRepository(session).get_revision(
                user_id=user_id, project_name=project_name, profile_id=run.profile_id, revision=run.profile_revision
            )
            if profile is None or profile.profile_digest != run.profile_digest:
                raise ProfileStaleError()
            if not isinstance(profile.policy, q.QualityPolicyV2):
                raise ProfileStaleError()
            duration_ms, width, height = await self._container_facts(session, run, user_id, project_name)
        facts = PackagingFacts(
            approved_master_id=run.subject.master_binding.root.candidate_id,
            approved_master_digest=run.subject.artifact_digest,
            assessed_subject_digest=run.subject_digest,
            profile_id=run.profile_id,
            profile_revision=run.profile_revision,
            profile_digest=run.profile_digest,
            duration_ms=duration_ms,
            width=width,
            height=height,
            assets={},
        )
        master = (run.subject.master_binding.root.object_ref, run.subject.artifact_digest)
        return revision.payload, facts, profile.policy.platform_constraints, master

    async def _container_facts(
        self, session: AsyncSession, run: q.QualityRun, user_id: str, project_name: str
    ) -> tuple[int, int, int]:
        """Duration and video size from the run's own verified CONTAINER_STREAM probe of the master."""
        runs = QualityRunRepository(session)
        observations = PackagingObservationRepository(session)
        for observation_id in run.observation_refs:
            found = await runs.technical_observation(
                user_id=user_id, project_name=project_name, observation_id=observation_id
            )
            if found is None:
                continue
            observation, _ = found
            if observation.status is not q.ObservationStatus.PASS or observation.subject_digest != run.subject_digest:
                continue
            result = await observations.probe_result(
                user_id=user_id,
                project_name=project_name,
                execution_id=observation.probe_receipt_ref,
                expected_digest=observation.probe_receipt_digest,
            )
            facts = result.measurement.facts
            if isinstance(facts, ContainerFacts) and run.subject.artifact_digest in result.measurement.input_digests:
                return _master_facts(facts)
        raise RequiredEvidenceMissingError()

    def _observation(
        self,
        request: p.PackageCheckRequest,
        candidate: PackagingCandidate,
        result: PackagingCheckResult,
        facts: PackagingFacts,
    ) -> p.PackagingObservation:
        subject = p.PackagingAssessedSubject(
            base_subject_digest=facts.assessed_subject_digest,
            packaging_candidate_id=request.subject.candidate_id,
            packaging_candidate_revision=request.subject.candidate_revision,
            packaging_candidate_digest=request.subject.candidate_payload_digest,
            constraint_snapshot_digest=candidate.constraint_snapshot_digest,
        )
        outcomes = [
            {"rule_id": o.rule_id, "check_id": o.check_id, "severity": o.severity, "locator": o.locator, "code": o.code}
            for o in result.failures
        ]
        rule_results_digest = digest_canonical(
            {
                "domain": "m10.packaging-rule-results.v1",
                "evaluated": list(result.evaluated_rule_ids),
                "failures": outcomes,
                "facts": {
                    "duration_ms": facts.duration_ms,
                    "width": facts.width,
                    "height": facts.height,
                    "assets": sorted(
                        [role, variant or "", a.content_digest, a.byte_size, a.media_type]
                        for (role, variant), a in facts.assets.items()
                    ),
                },
            }
        )
        return p.PackagingObservation(
            observation_id=uuid7(),
            observation_type=q.ObservationType.PACKAGING,
            requirement_id=REQUIREMENT_ID,
            slot_id=SLOT_ID,
            assessor_identity=ASSESSOR_IDENTITY,
            assessor_version=ASSESSOR_VERSION,
            assessor_qualification_ref=ASSESSOR_VERSION,
            assessor_qualification_digest=CHECK_CONFIG_DIGEST,
            independence_group=INDEPENDENCE_GROUP,
            producer_conflict=False,
            config_digest=CHECK_CONFIG_DIGEST,
            subject_digest=compute_digest("m10.packaging-subject.v1", subject),
            status=result.status,
            findings=tuple(_finding(outcome) for outcome in result.failures),
            evidence_refs=(f"m8:{request.subject.candidate_id}@{request.subject.candidate_revision}",),
            evidence_digest=rule_results_digest,
            observed_at=self._clock(),
            packaging_subject=subject,
            constraint_snapshot_digest=candidate.constraint_snapshot_digest,
            check_config_digest=CHECK_CONFIG_DIGEST,
            rule_results_digest=rule_results_digest,
        )


__all__ = ["CHECK_CONFIG_DIGEST", "PackagingCheckService"]
