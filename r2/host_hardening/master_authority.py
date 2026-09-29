"""The M7 master head as the sole master authority, with the file manifest as its projection (ADR-0096).

A promotion registers the approved host version file as an immutable candidate object, verified
in place, and promotes the master head through ``AtomicPromotionService`` in one transaction.
The caller then projects the file manifest's ``approved_master``. Master-consuming reads compare
the database head with that projection through ``DatabaseMasterResolver``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from lib.candidate_store import CandidateMediaProbeMismatchError, prepare_candidate
from r2.contracts.host_hardening import CandidateIdentity, MasterHeadSnapshot, VerifiedCandidateObject
from r2.host_hardening.master_resolver import DatabaseMasterResolver, MasterDivergedError
from r2.host_hardening.ports import MasterAuthorityPort, PromotionReceiptPort
from r2.host_hardening.promotion import AtomicPromotionService

_CANDIDATE_ID_PREFIX = "m7c:"
_CANDIDATE_ID_HEX = 40


class CandidateObjectConflictError(RuntimeError):
    """The candidate id is already registered for different bytes or another artifact."""


def m7_candidate_id(artifact_key: str, generation_candidate_id: str) -> str:
    """The M7 candidate id of a host generation candidate, unique per artifact within a project."""
    digest = hashlib.sha256(f"{artifact_key}\n{generation_candidate_id}".encode()).hexdigest()
    return _CANDIDATE_ID_PREFIX + digest[:_CANDIDATE_ID_HEX]


def stream_probe_digest(path: Path) -> str:
    """Digest of the file's stream layout; raises ``CandidateMediaProbeMismatchError`` if unreadable."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise CandidateMediaProbeMismatchError("ffprobe is not available to verify the candidate")
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        streams = json.loads(probe.stdout).get("streams") if probe.returncode == 0 else None
    except ValueError:
        streams = None
    if not streams:
        raise CandidateMediaProbeMismatchError(f"{path.name} is not readable media")
    layout = [
        [stream.get("codec_type"), stream.get("codec_name"), stream.get("width"), stream.get("height")]
        for stream in streams
    ]
    canonical = json.dumps(layout, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


SelectedGenerationCandidate = Callable[[str, str], str | None]
"""``(project_name, artifact_key)`` -> the file manifest's selected generation candidate id."""


class FileMasterProjection:
    """``LegacyMasterProjection`` over the file manifest's ``approved_master``."""

    def __init__(self, selected: SelectedGenerationCandidate) -> None:
        self._selected = selected

    async def get_selected_candidate_id(self, *, user_id: str, project_name: str, artifact_key: str) -> str | None:
        selected = await asyncio.to_thread(self._selected, project_name, artifact_key)
        return None if selected is None else m7_candidate_id(artifact_key, selected)


class CandidateObjectStore(Protocol):
    async def get_exact(
        self, *, user_id: str, project_name: str, candidate_id: str
    ) -> VerifiedCandidateObject | None: ...

    async def insert(
        self, *, user_id: str, project_name: str, candidate: VerifiedCandidateObject, created_at: datetime
    ) -> None: ...


class MasterAuthorityUnit:
    """One transaction's master promotion over the M7 repositories of a single session."""

    def __init__(
        self,
        *,
        candidates: CandidateObjectStore,
        authorities: MasterAuthorityPort,
        receipts: PromotionReceiptPort,
        commit: Callable[[], Awaitable[None]],
        clock: Callable[[], datetime],
        probe: Callable[[Path], str] = stream_probe_digest,
    ) -> None:
        self._candidates = candidates
        self._authorities = authorities
        self._receipts = receipts
        self._clock = clock
        self._probe = probe
        self._service = AtomicPromotionService(
            candidates=candidates, authorities=authorities, receipts=receipts, clock=clock, commit=commit
        )

    async def promote_staged(
        self,
        *,
        user_id: str,
        project_name: str,
        project_dir: Path,
        artifact_key: str,
        generation_candidate_id: str,
        version_file: Path,
        expected_content_digest: str,
        approval_record: str,
        command_id: str,
    ) -> MasterHeadSnapshot:
        """Promote ``version_file`` if its bytes still hash to ``expected_content_digest`` (the staged output)."""
        candidate_id = m7_candidate_id(artifact_key, generation_candidate_id)
        replay = await self._receipts.get_exact(
            user_id=user_id, project_name=project_name, artifact_key=artifact_key, command_id=command_id
        )
        if replay is None:
            await self._register(
                user_id=user_id,
                project_name=project_name,
                project_dir=project_dir,
                artifact_key=artifact_key,
                candidate_id=candidate_id,
                version_file=version_file,
                expected_content_digest=expected_content_digest,
            )
            expected = await self._authorities.get_current_version(
                user_id=user_id, project_name=project_name, artifact_key=artifact_key
            )
        else:
            expected = replay.master_version - 1
        return await self._service.promote(
            user_id=user_id,
            project_name=project_name,
            artifact_key=artifact_key,
            candidate_id=candidate_id,
            expected_master_version=expected,
            approval_record=approval_record,
            command_id=command_id,
        )

    async def promote_registered(
        self,
        *,
        user_id: str,
        project_name: str,
        artifact_key: str,
        candidate_id: str,
        expected_master_version: int,
        approval_record: str,
        command_id: str,
    ) -> MasterHeadSnapshot:
        """Promote an already registered candidate object; commits through this unit's ``commit``."""
        return await self._service.promote(
            user_id=user_id,
            project_name=project_name,
            artifact_key=artifact_key,
            candidate_id=candidate_id,
            expected_master_version=expected_master_version,
            approval_record=approval_record,
            command_id=command_id,
        )

    async def _register(
        self,
        *,
        user_id: str,
        project_name: str,
        project_dir: Path,
        artifact_key: str,
        candidate_id: str,
        version_file: Path,
        expected_content_digest: str,
    ) -> None:
        digest = expected_content_digest
        verified = await asyncio.to_thread(
            lambda: prepare_candidate(
                identity=CandidateIdentity(
                    candidate_id=candidate_id,
                    user_id=user_id,
                    project_name=project_name,
                    artifact_key=artifact_key,
                    expected_content_digest=digest,
                ),
                source_file=version_file,
                final_path=version_file,
                media_root=project_dir,
                media_probe=self._probe,
            )
        )
        existing = await self._candidates.get_exact(
            user_id=user_id, project_name=project_name, candidate_id=candidate_id
        )
        if existing is None:
            await self._candidates.insert(
                user_id=user_id, project_name=project_name, candidate=verified, created_at=self._clock()
            )
        elif existing != verified:
            raise CandidateObjectConflictError(f"candidate {candidate_id!r} is registered for different bytes")


async def verify_project_masters(
    *,
    user_id: str,
    project_name: str,
    authorities: MasterAuthorityPort,
    projection: FileMasterProjection,
    database_keys: Iterable[str],
    projected_keys: Iterable[str],
) -> tuple[tuple[str, int, str], ...]:
    """Raise ``MasterDivergedError`` unless every database head has an equal projection and vice versa.

    Unlike the resolver alone, a database head whose projection is missing is a divergence: every
    promotion is projected before its artifact is read, so a missing projection is an unfinished or
    refused one. Returns the verified heads as ``(artifact_key, master_version, candidate_id)``, so a
    reader can tell whether they moved while it read.
    """
    database = set(database_keys)
    unprojected = sorted(database - set(projected_keys))
    if unprojected:
        raise MasterDivergedError(f"M7_MASTER_DIVERGED: {unprojected[0]!r} has a database head but no projection")
    resolver = DatabaseMasterResolver(authorities=authorities, legacy_projection=projection)
    heads: list[tuple[str, int, str]] = []
    for artifact_key in sorted(database | set(projected_keys)):
        head = await resolver.get_exact(user_id=user_id, project_name=project_name, artifact_key=artifact_key)
        if head is not None:
            heads.append((artifact_key, head.master_version, head.candidate_id))
    return tuple(heads)


__all__ = [
    "CandidateObjectConflictError",
    "FileMasterProjection",
    "MasterAuthorityUnit",
    "MasterDivergedError",
    "m7_candidate_id",
    "stream_probe_digest",
    "verify_project_masters",
]
