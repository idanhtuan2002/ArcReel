"""Server-owned spatial analysis: one bounded M7 attempt becomes one evidence-bound M8 revision.

The command names two verified frame receipts. The service builds the prompt and the
provider request, submits through ``AttemptSubmitter``, then normalizes the exact raw
response and stages the evidence row, the M8 revision and the command receipt in one
transaction that holds both parent master locks. Any failure leaves no revision.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.base import utc_now
from lib.db.repositories.advanced_creative import APPEND_REVISION, ExplorationRepository
from lib.db.repositories.host_hardening import ExecutionAttemptRepository
from lib.db.repositories.spatial_execution import SpatialExecutionEvidenceRepository
from lib.text_backends.base import ImageInput, TextBackend, TextGenerationRequest
from lib.video_backends.execution_adapter import accepted_submit_receipt
from r2.advanced_creative.digests import digest_canonical, digest_payload
from r2.advanced_creative.errors import CandidateConflictError, CommandConflictError
from r2.advanced_creative.spatial import SpatialNormalizationError, SpatialSourceIdentity, normalize_spatial_candidate
from r2.advanced_creative.spatial_prompt import (
    MASTER_SOURCE_REF,
    REVERSE_SOURCE_REF,
    SPATIAL_PROMPT_VERSION,
    SPATIAL_RESPONSE_SCHEMA_VERSION,
    build_spatial_prompt,
    parse_spatial_response,
    spatial_prompt_digest,
)
from r2.contracts.advanced_creative import (
    CandidateHead,
    ExplorationKind,
    ExplorationRevision,
    LineageBinding,
)
from r2.contracts.execution import ProviderRequest
from r2.contracts.host_hardening import (
    AttemptSnapshot,
    ExecutionAttemptState,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)
from r2.contracts.spatial_execution import (
    SpatialExecutionEvidenceV1,
    SpatialResponseObjectV1,
    SpatialSourceFrameV1,
)
from r2.host_hardening.host_submit import AttemptSubmitter
from r2.host_hardening.route_inventory import HOST_SPATIAL_ADAPTER_VERSION
from server.services.execution_attempts import capability_resolver
from server.services.master_authority import serialized_artifacts
from server.services.spatial_frame_reader import SpatialFrameReader, VerifiedSpatialFrame
from server.services.spatial_source import FrameSourceConflictError

SPATIAL_NORMALIZER_VERSION = "spatial-r2-v1"
SPATIAL_REQUEST_SCHEMA = "r2.m8.spatial.request.v1"


class SpatialExecutionUnavailableError(RuntimeError):
    """The spatial execution produced no usable result; no revision was written."""


class SpatialVisionCall(Protocol):
    async def __call__(self, *, prompt: str, master_png: bytes, reverse_png: bytes) -> bytes: ...


@dataclass(frozen=True)
class SpatialFrameRef:
    receipt_id: str
    receipt_digest: str


@dataclass(frozen=True)
class SpatialExecutionCommand:
    user_id: str
    project_name: str
    command_id: str
    candidate_id: str
    expected_head_version: int | None
    episode: int
    scene_name: str
    master: SpatialFrameRef
    reverse: SpatialFrameRef


def text_backend_spatial_vision(backend: TextBackend) -> SpatialVisionCall:
    """Bind one text backend that accepts image files as the spatial vision call."""

    async def call(*, prompt: str, master_png: bytes, reverse_png: bytes) -> bytes:
        with tempfile.TemporaryDirectory(prefix="r2-spatial-") as directory:
            master_path = Path(directory) / "master.png"
            reverse_path = Path(directory) / "reverse.png"
            master_path.write_bytes(master_png)
            reverse_path.write_bytes(reverse_png)
            result = await backend.generate(
                TextGenerationRequest(
                    prompt=prompt, images=[ImageInput(path=master_path), ImageInput(path=reverse_path)]
                )
            )
        return result.text.encode("utf-8")

    return call


def _task_id(command: SpatialExecutionCommand) -> str:
    scope = digest_canonical(
        {"user_id": command.user_id, "project_name": command.project_name, "command_id": command.command_id}
    )
    return "m8c-spatial:" + scope.removeprefix("sha256:")


def _byte_digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _source_frame(role: str, frame: VerifiedSpatialFrame) -> SpatialSourceFrameV1:
    return SpatialSourceFrameV1.model_validate(
        {
            "role": role,
            "frame_receipt_id": frame.receipt.frame_candidate_id,
            "frame_receipt_digest": frame.receipt_digest,
            "frame_digest": frame.receipt.identity.frame_content_digest,
        }
    )


class SpatialExecutionService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        project_dir: Path,
        route: ProviderRouteSnapshot,
        vision: SpatialVisionCall,
        submitter_for: Callable[[AsyncSession, str, str], AttemptSubmitter],
        lineage_for: Callable[[str, int], Awaitable[LineageBinding]],
        clock: Callable[[], datetime] = utc_now,
        evidence_store: Callable[
            [AsyncSession], SpatialExecutionEvidenceRepository
        ] = SpatialExecutionEvidenceRepository,
    ) -> None:
        if route.adapter_version != HOST_SPATIAL_ADAPTER_VERSION or route.endpoint_id is None:
            raise ValueError("spatial execution requires the host-spatial adapter route")
        self._endpoint = route.endpoint_id
        self._sessions = session_factory
        self._frames = SpatialFrameReader(session_factory=session_factory, project_dir=project_dir)
        self._route = route
        self._vision = vision
        self._submitter_for = submitter_for
        self._lineage_for = lineage_for
        self._clock = clock
        self._evidence_store = evidence_store

    def _request(
        self, command: SpatialExecutionCommand, prompt: str, frames: tuple[SpatialSourceFrameV1, SpatialSourceFrameV1]
    ) -> ProviderRequest:
        task_id = _task_id(command)
        return ProviderRequest(
            id=f"{task_id}:spatial-submit",
            host_task_ref=task_id,
            provider=self._route.provider_id,
            model=self._route.provider_model_id,
            endpoint=self._endpoint,
            payload={
                "schema": SPATIAL_REQUEST_SCHEMA,
                "candidate_id": command.candidate_id,
                "episode": command.episode,
                "prompt_version": SPATIAL_PROMPT_VERSION,
                "prompt_digest": spatial_prompt_digest(prompt),
                "response_schema_version": SPATIAL_RESPONSE_SCHEMA_VERSION,
                "normalizer_version": SPATIAL_NORMALIZER_VERSION,
                "frames": [frame.model_dump(mode="json") for frame in frames],
            },
            adapter_version=self._route.adapter_version,
        )

    async def execute(self, command: SpatialExecutionCommand) -> CandidateHead:
        if command.master.receipt_id == command.reverse.receipt_id:
            raise CandidateConflictError("MASTER and REVERSE must be distinct frames")
        replay = await self._replay(command)
        if replay is not None:
            return replay

        master, reverse = await self._read_current(command)
        frames = (_source_frame("MASTER", master), _source_frame("REVERSE", reverse))
        if frames[0].frame_digest == frames[1].frame_digest:
            raise CandidateConflictError("MASTER and REVERSE must be distinct frame bytes")
        prompt = build_spatial_prompt(command.scene_name)
        request = self._request(command, prompt, frames)

        async def submit(_attempt: object):
            raw = await self._vision(prompt=prompt, master_png=master.png_bytes, reverse_png=reverse.png_bytes)
            return accepted_submit_receipt(raw, provider_job_id=_byte_digest(raw))

        async with self._sessions() as attempt_session:
            submitter = self._submitter_for(attempt_session, command.user_id, command.project_name)
            result = await submitter.submit(
                task_id=_task_id(command), api_call_id=None, route=self._route, request=request, submit=submit
            )
        if result.snapshot.state is not ExecutionAttemptState.ACCEPTED or result.value is None:
            raise SpatialExecutionUnavailableError(
                f"spatial execution {result.execution_id} ended {result.snapshot.state.value} without a usable result"
            )
        raw = result.value
        try:
            candidate = normalize_spatial_candidate(
                parse_spatial_response(raw),
                overlap_analysis=None,
                sources={
                    MASTER_SOURCE_REF: SpatialSourceIdentity(source_digest=frames[0].frame_digest, view="MASTER"),
                    REVERSE_SOURCE_REF: SpatialSourceIdentity(source_digest=frames[1].frame_digest, view="REVERSE"),
                },
                execution_id=result.execution_id,
                normalizer_version=SPATIAL_NORMALIZER_VERSION,
            )
        except SpatialNormalizationError as exc:
            async with self._sessions() as session:
                await self._mark_succeeded(session, command, result.execution_id, raw)
                await session.commit()
            raise SpatialExecutionUnavailableError(f"spatial execution {result.execution_id}: {exc}") from exc
        lineage = await self._lineage_for(command.project_name, command.episode)
        return await self._commit(
            command, request, frames, raw, result.execution_id, candidate, lineage, spatial_prompt_digest(prompt)
        )

    async def _replay(self, command: SpatialExecutionCommand) -> CandidateHead | None:
        async with self._sessions() as session:
            stored = await SpatialExecutionEvidenceRepository(session).get_by_command(
                user_id=command.user_id, project_name=command.project_name, command_id=command.command_id
            )
            if stored is None:
                return None
            receipt = await ExplorationRepository(session).get_command_receipt(
                user_id=command.user_id,
                project_name=command.project_name,
                actor_scope=command.user_id,
                operation=APPEND_REVISION,
                command_id=command.command_id,
            )
        master, reverse = stored.evidence.ordered_source_frames
        head = CandidateHead(
            candidate_id=command.candidate_id,
            current_revision=stored.revision,
            head_version=(command.expected_head_version or 0) + 1,
        )
        if (
            receipt is None
            or receipt.result_digest != digest_canonical(head)
            or stored.candidate_id != command.candidate_id
            or (master.frame_receipt_id, master.frame_receipt_digest)
            != (command.master.receipt_id, command.master.receipt_digest)
            or (reverse.frame_receipt_id, reverse.frame_receipt_digest)
            != (command.reverse.receipt_id, command.reverse.receipt_digest)
            or stored.evidence.prompt_digest != spatial_prompt_digest(build_spatial_prompt(command.scene_name))
        ):
            raise CommandConflictError("command_id was already used for a different spatial execution")
        return head

    async def _read_current(
        self, command: SpatialExecutionCommand
    ) -> tuple[VerifiedSpatialFrame, VerifiedSpatialFrame]:
        try:
            master = await self._frames.read_current(
                user_id=command.user_id,
                project_name=command.project_name,
                receipt_id=command.master.receipt_id,
                expected_receipt_digest=command.master.receipt_digest,
            )
            reverse = await self._frames.read_current(
                user_id=command.user_id,
                project_name=command.project_name,
                receipt_id=command.reverse.receipt_id,
                expected_receipt_digest=command.reverse.receipt_digest,
            )
        except FrameSourceConflictError as exc:
            raise SpatialExecutionUnavailableError(f"spatial source unavailable: {exc}") from exc
        return master, reverse

    async def _commit(
        self,
        command: SpatialExecutionCommand,
        request: ProviderRequest,
        frames: tuple[SpatialSourceFrameV1, SpatialSourceFrameV1],
        raw: bytes,
        execution_id: str,
        candidate: object,
        lineage: LineageBinding,
        prompt_digest: str,
    ) -> CandidateHead:
        from r2.contracts.advanced_creative import SpatialCandidate

        if not isinstance(candidate, SpatialCandidate):
            raise SpatialExecutionUnavailableError("normalizer returned a non-spatial candidate")
        parents = {
            command.master.receipt_id: frames[0],
            command.reverse.receipt_id: frames[1],
        }
        try:
            async with serialized_artifacts(
                self._sessions,
                user_id=command.user_id,
                project_name=command.project_name,
                artifact_keys=await self._parent_keys(command),
            ) as session:
                for receipt_id, frame in parents.items():
                    current = await self._frames.read_locked(
                        session,
                        user_id=command.user_id,
                        project_name=command.project_name,
                        receipt_id=receipt_id,
                        expected_receipt_digest=frame.frame_receipt_digest,
                        expected_parent_artifact_key=await self._parent_key(session, command, receipt_id),
                    )
                    if current.receipt.identity.frame_content_digest != frame.frame_digest:
                        raise SpatialExecutionUnavailableError("spatial source changed during execution")
                request_digest = "sha256:" + hashlib.sha256(_canonical_request(request)).hexdigest()
                attempt = await self._mark_succeeded(session, command, execution_id, raw)
                if attempt.request_digest != request_digest:
                    raise SpatialExecutionUnavailableError("spatial execution attempt is not this request")
                evidence = SpatialExecutionEvidenceV1(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    execution_id=execution_id,
                    task_id=_task_id(command),
                    request_digest=request_digest,
                    route_digest=digest_canonical(attempt.route),
                    provider_job_id=attempt.provider_job_id,
                    terminal_state="SUCCEEDED",
                    terminal_state_version=attempt.state_version,
                    prompt_version=SPATIAL_PROMPT_VERSION,
                    prompt_digest=prompt_digest,
                    normalizer_version=SPATIAL_NORMALIZER_VERSION,
                    raw_response=SpatialResponseObjectV1(
                        object_id=f"spatial-raw:{execution_id}",
                        byte_digest=_byte_digest(raw),
                        schema_version=SPATIAL_RESPONSE_SCHEMA_VERSION,
                    ),
                    overlap_response=None,
                    ordered_source_frames=frames,
                )
                exploration = ExplorationRepository(session)
                head = await exploration.get_head(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    candidate_id=command.candidate_id,
                    for_update=True,
                )
                revision_no = 1 if head is None else head.current_revision + 1
                revision = ExplorationRevision(
                    candidate_id=command.candidate_id,
                    revision=revision_no,
                    kind=ExplorationKind.SPATIAL,
                    parent_revision=None if head is None else head.current_revision,
                    payload=candidate,
                    payload_digest=digest_payload(candidate, lineage),
                    lineage=lineage,
                    created_by=command.user_id,
                    created_at=self._clock(),
                )
                result = await exploration.append_revision(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    candidate=revision,
                    expected_head_version=command.expected_head_version,
                    command_id=command.command_id,
                )
                await self._evidence_store(session).stage(
                    evidence=evidence,
                    candidate_id=command.candidate_id,
                    revision=revision_no,
                    command_id=command.command_id,
                    raw_response=raw,
                    created_at=revision.created_at,
                )
                return result
        except FrameSourceConflictError as exc:
            raise SpatialExecutionUnavailableError(f"spatial source changed during execution: {exc}") from exc

    @staticmethod
    async def _mark_succeeded(
        session: AsyncSession, command: SpatialExecutionCommand, execution_id: str, raw: bytes
    ) -> AttemptSnapshot:
        repository = ExecutionAttemptRepository(session, capability_resolver=capability_resolver())
        attempt = await repository.get_for_task_attempt(
            user_id=command.user_id, project_name=command.project_name, task_id=_task_id(command), attempt_no=1
        )
        if (
            attempt is None
            or attempt.execution_id != execution_id
            or attempt.state is not ExecutionAttemptState.ACCEPTED
            or attempt.provider_job_id != _byte_digest(raw)
        ):
            raise SpatialExecutionUnavailableError("spatial execution attempt is not the accepted response")
        succeeded = await repository.apply_provider_observation(
            user_id=command.user_id,
            project_name=command.project_name,
            execution_id=execution_id,
            expected_version=attempt.state_version,
            observation=ProviderObservation(
                observation_id=f"{execution_id}:succeeded",
                kind=ProviderObservationKind.SUCCEEDED,
                observed_at=utc_now(),
                provider_job_id=attempt.provider_job_id,
                evidence_digest=_byte_digest(raw),
            ),
        )
        if succeeded.state is not ExecutionAttemptState.SUCCEEDED:
            raise SpatialExecutionUnavailableError("spatial execution attempt could not reach SUCCEEDED")
        return succeeded

    async def _parent_keys(self, command: SpatialExecutionCommand) -> tuple[str, ...]:
        from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository

        async with self._sessions() as session:
            repository = SpatialFrameReceiptRepository(session)
            keys: list[str] = []
            for ref in (command.master, command.reverse):
                receipt = await repository.get_exact(
                    user_id=command.user_id, project_name=command.project_name, receipt_id=ref.receipt_id
                )
                if receipt is None:
                    raise SpatialExecutionUnavailableError("spatial source unavailable")
                keys.append(receipt.identity.parent_artifact_key)
        return tuple(keys)

    async def _parent_key(self, session: AsyncSession, command: SpatialExecutionCommand, receipt_id: str) -> str:
        from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository

        receipt = await SpatialFrameReceiptRepository(session).get_exact(
            user_id=command.user_id, project_name=command.project_name, receipt_id=receipt_id
        )
        if receipt is None:
            raise SpatialExecutionUnavailableError("spatial source unavailable")
        return receipt.identity.parent_artifact_key


def _canonical_request(request: ProviderRequest) -> bytes:
    from r2.contracts.common import ensure_json_value
    from r2.contracts.fingerprints import canonical_json_bytes

    return canonical_json_bytes(ensure_json_value(request.model_dump(mode="json")))


__all__ = [
    "SPATIAL_NORMALIZER_VERSION",
    "SpatialExecutionCommand",
    "SpatialExecutionService",
    "SpatialExecutionUnavailableError",
    "SpatialFrameRef",
    "SpatialVisionCall",
    "text_backend_spatial_vision",
]
