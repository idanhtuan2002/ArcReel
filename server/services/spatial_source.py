"""Bounded extraction of a pinned decoded video ordinal into one PNG source frame."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.artifact_manifest import ArtifactKind, decode_artifact_key_parts
from lib.candidate_store import prepare_candidate, verify_candidate
from lib.db.repositories.host_hardening import CandidateObjectRepository, MasterAuthorityRepository
from lib.db.repositories.spatial_source import SpatialFrameReceiptConflictError, SpatialFrameReceiptRepository
from lib.path_safety import safe_join
from r2.advanced_creative.digests import digest_canonical, digest_command
from r2.contracts.host_hardening import CandidateIdentity, MasterHeadSnapshot, VerifiedCandidateObject
from r2.contracts.spatial_source import FrameDerivationReceiptV1, FrameIdentityV1
from r2.host_hardening.master_authority import stream_probe_digest
from server.services.master_authority import serialized_artifacts, verify_masters

FRAME_RECIPE_VERSION = "m8c-frame-rgb24-png-v1"
MAX_DECODED_FRAME_INDEX = 100_000
MAX_FRAME_BYTES = 32 * 1024 * 1024
MAX_FRAME_DIMENSION = 4096
DECODE_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class FrameProbe:
    byte_size: int
    content_digest: str
    probe_digest: str
    width: int
    height: int


def ffmpeg_decoder_identity() -> str:
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True, timeout=5)
    return "ffmpeg:" + hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()


def _probe_png(path: Path) -> tuple[int, int, str]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,width,height,nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    streams = json.loads(result.stdout).get("streams", [])
    if len(streams) != 1:
        raise ValueError("decoded output is not one video frame")
    stream = streams[0]
    width, height = stream.get("width"), stream.get("height")
    if (
        stream.get("codec_name") != "png"
        or stream.get("pix_fmt") != "rgb24"
        or stream.get("nb_read_frames") != "1"
        or not isinstance(width, int)
        or not isinstance(height, int)
        or not 1 <= width <= MAX_FRAME_DIMENSION
        or not 1 <= height <= MAX_FRAME_DIMENSION
    ):
        raise ValueError("decoded PNG has invalid format or dimensions")
    return (
        width,
        height,
        digest_canonical({"codec_name": "png", "pixel_format": "rgb24", "width": width, "height": height, "frames": 1}),
    )


def decode_frame(
    *,
    parent_path: Path,
    decoded_frame_index: int,
    recipe_version: str,
    decoder_identity: str,
    output_temp: Path,
) -> FrameProbe:
    if type(decoded_frame_index) is not int or not 0 <= decoded_frame_index <= MAX_DECODED_FRAME_INDEX:
        raise ValueError("decoded frame index is out of range")
    if recipe_version != FRAME_RECIPE_VERSION:
        raise ValueError("unsupported frame recipe version")
    if decoder_identity != ffmpeg_decoder_identity():
        raise ValueError("frame decoder identity differs from current build")
    if output_temp.exists() or output_temp.is_symlink():
        raise ValueError("output temp already exists")
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(parent_path),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-vf",
            f"select=eq(n\\,{decoded_frame_index}),format=rgb24",
            "-fps_mode",
            "passthrough",
            "-frames:v",
            "1",
            "-f",
            "image2",
            "-fs",
            str(MAX_FRAME_BYTES),
            "-n",
            str(output_temp),
        ],
        capture_output=True,
        check=False,
        timeout=DECODE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise ValueError("frame decoder failed")
    if not output_temp.is_file() or output_temp.is_symlink():
        raise ValueError("decoder produced no frame")
    size = output_temp.stat().st_size
    if not 0 < size <= MAX_FRAME_BYTES:
        raise ValueError("decoded frame exceeds size limit")
    with output_temp.open("rb") as source:
        if source.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError("decoded frame is not PNG")
        hasher = hashlib.sha256()
        hasher.update(b"\x89PNG\r\n\x1a\n")
        while chunk := source.read(1024 * 1024):
            hasher.update(chunk)
    width, height, probe_digest = _probe_png(output_temp)
    return FrameProbe(size, "sha256:" + hasher.hexdigest(), probe_digest, width, height)


def publish_frame(
    *, temp: Path, final: Path, media_root: Path, identity: CandidateIdentity, probe: FrameProbe
) -> VerifiedCandidateObject:
    if identity.expected_content_digest != probe.content_digest:
        raise ValueError("frame identity digest differs from decoded bytes")
    verified = prepare_candidate(
        identity=identity,
        source_file=temp,
        final_path=final,
        media_root=media_root,
        media_probe=lambda path: _probe_png(path)[2],
    )
    if verified.byte_size != probe.byte_size or verified.media_probe_digest != probe.probe_digest:
        raise ValueError("published frame differs from decoded probe")
    return verified


class FrameSourceConflictError(ValueError):
    """The command, parent head or frame bytes differ from the pinned derivation."""


class FramePublisher(Protocol):
    def __call__(
        self, *, temp: Path, final: Path, media_root: Path, identity: CandidateIdentity, probe: FrameProbe
    ) -> VerifiedCandidateObject: ...


class FrameDecoder(Protocol):
    def __call__(
        self,
        *,
        parent_path: Path,
        decoded_frame_index: int,
        recipe_version: str,
        decoder_identity: str,
        output_temp: Path,
    ) -> FrameProbe: ...


def _copy_parent_verified(source_path: Path, snapshot_path: Path, *, expected_digest: str, expected_size: int) -> None:
    hasher = hashlib.sha256()
    copied = 0
    with source_path.open("rb") as source, snapshot_path.open("xb") as snapshot:
        while chunk := source.read(1024 * 1024):
            copied += len(chunk)
            if copied > expected_size:
                raise FrameSourceConflictError("parent video grew during snapshot capture")
            snapshot.write(chunk)
            hasher.update(chunk)
        snapshot.flush()
        os.fsync(snapshot.fileno())
    if copied != expected_size or "sha256:" + hasher.hexdigest() != expected_digest:
        raise FrameSourceConflictError("parent video bytes changed during snapshot capture")


class FrameDerivationService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        project_dir: Path,
        after_decode: Callable[[], Awaitable[None]] | None = None,
        publisher: FramePublisher = publish_frame,
        decoder: FrameDecoder = decode_frame,
    ) -> None:
        self._sessions = session_factory
        self._project_dir = project_dir.resolve()
        self._after_decode = after_decode
        self._publisher = publisher
        self._decoder = decoder

    async def _parent(
        self, session: AsyncSession, *, user_id: str, project_name: str, artifact_key: str, expected_version: int
    ) -> tuple[MasterHeadSnapshot, Path, VerifiedCandidateObject]:
        heads = await verify_masters(session, user_id=user_id, project_name=project_name, project_dir=self._project_dir)
        head = await MasterAuthorityRepository(session).get_current(
            user_id=user_id, project_name=project_name, artifact_key=artifact_key
        )
        if head is None or head.master_version != expected_version:
            raise FrameSourceConflictError("parent video master is missing or superseded")
        if (artifact_key, head.master_version, head.candidate_id) not in heads:
            raise FrameSourceConflictError("parent video master lacks a complete projection")
        candidate = await CandidateObjectRepository(session).get_exact(
            user_id=user_id, project_name=project_name, candidate_id=head.candidate_id
        )
        if (
            candidate is None
            or candidate.project_name != project_name
            or candidate.artifact_key != artifact_key
            or candidate.object_ref != head.object_ref
            or candidate.content_digest != head.content_digest
        ):
            raise FrameSourceConflictError("parent candidate differs from approved master")
        path = safe_join(self._project_dir, head.object_ref, require_file=True)
        if not await asyncio.to_thread(
            verify_candidate, object_ref=path, expected=candidate, media_probe=stream_probe_digest
        ):
            raise FrameSourceConflictError("parent video bytes differ from approved master")
        return head, path, candidate

    async def derive(
        self,
        *,
        user_id: str,
        project_name: str,
        parent_artifact_key: str,
        expected_master_version: int,
        decoded_frame_index: int,
        command_id: str,
    ) -> FrameDerivationReceiptV1:
        parts = decode_artifact_key_parts(parent_artifact_key)
        if parts is None or parts.kind != ArtifactKind.EPISODE_VIDEO.value:
            raise ValueError("frame parent must be an episode video artifact")
        if expected_master_version < 1 or not command_id.strip():
            raise ValueError("frame command requires a master version and command id")
        decoder_identity = await asyncio.to_thread(ffmpeg_decoder_identity)
        command_digest = digest_command(
            "DERIVE_SPATIAL_FRAME",
            user_id,
            project_name,
            "FRAME_SOURCE",
            {
                "parent_artifact_key": parent_artifact_key,
                "expected_master_version": expected_master_version,
                "decoded_frame_index": decoded_frame_index,
                "recipe_version": FRAME_RECIPE_VERSION,
                "decoder_identity": decoder_identity,
            },
        )
        async with self._sessions() as read_session:
            prior_command = await SpatialFrameReceiptRepository(read_session).get_by_command(
                user_id=user_id, project_name=project_name, command_id=command_id
            )
            if prior_command is not None and prior_command.command_digest != command_digest:
                raise FrameSourceConflictError("frame command conflicts with an existing receipt")
            initial, parent_path, parent_candidate = await self._parent(
                read_session,
                user_id=user_id,
                project_name=project_name,
                artifact_key=parent_artifact_key,
                expected_version=expected_master_version,
            )
        with tempfile.TemporaryDirectory(prefix=".m8frame-", dir=self._project_dir) as private_dir:
            parent_snapshot = Path(private_dir) / "parent.mp4"
            await asyncio.to_thread(
                _copy_parent_verified,
                parent_path,
                parent_snapshot,
                expected_digest=initial.content_digest,
                expected_size=parent_candidate.byte_size,
            )
            temp = Path(private_dir) / "frame.png"
            probe = await asyncio.to_thread(
                self._decoder,
                parent_path=parent_snapshot,
                decoded_frame_index=decoded_frame_index,
                recipe_version=FRAME_RECIPE_VERSION,
                decoder_identity=decoder_identity,
                output_temp=temp,
            )
            if self._after_decode is not None:
                await self._after_decode()
            identity = FrameIdentityV1(
                user_id=user_id,
                project_name=project_name,
                parent_artifact_key=parent_artifact_key,
                parent_master_version=initial.master_version,
                parent_candidate_id=initial.candidate_id,
                parent_content_digest=initial.content_digest,
                decoded_frame_index=decoded_frame_index,
                recipe_version=FRAME_RECIPE_VERSION,
                decoder_identity=decoder_identity,
                frame_content_digest=probe.content_digest,
            )
            frame_id = identity.candidate_id
            final = self._project_dir / "spatial" / "frames" / f"{frame_id}.png"
            candidate = await asyncio.to_thread(
                self._publisher,
                temp=temp,
                final=final,
                media_root=self._project_dir,
                identity=CandidateIdentity(
                    candidate_id=frame_id,
                    user_id=user_id,
                    project_name=project_name,
                    artifact_key=f"spatial_frame:{frame_id}",
                    expected_content_digest=probe.content_digest,
                ),
                probe=probe,
            )
            async with serialized_artifacts(
                self._sessions, user_id=user_id, project_name=project_name, artifact_keys=(parent_artifact_key,)
            ) as session:
                current, _, _ = await self._parent(
                    session,
                    user_id=user_id,
                    project_name=project_name,
                    artifact_key=parent_artifact_key,
                    expected_version=expected_master_version,
                )
                if current != initial:
                    raise FrameSourceConflictError("parent video master changed during frame derivation")
                if not await asyncio.to_thread(
                    verify_candidate, object_ref=final, expected=candidate, media_probe=lambda path: _probe_png(path)[2]
                ):
                    raise FrameSourceConflictError("published frame bytes differ from decoded frame")
                receipts = SpatialFrameReceiptRepository(session)
                existing = await receipts.get_by_command(
                    user_id=user_id, project_name=project_name, command_id=command_id
                )
                if existing is not None:
                    if existing.command_digest != command_digest or existing.frame_candidate_id != frame_id:
                        raise FrameSourceConflictError("frame command conflicts with an existing receipt")
                    registered = await CandidateObjectRepository(session).get_exact(
                        user_id=user_id, project_name=project_name, candidate_id=frame_id
                    )
                    if (
                        registered != candidate
                        or existing.frame_byte_size != candidate.byte_size
                        or existing.frame_probe_digest != candidate.media_probe_digest
                    ):
                        raise FrameSourceConflictError("frame receipt candidate differs from registered bytes")
                    return existing
                prior = await receipts.get_exact(user_id=user_id, project_name=project_name, receipt_id=frame_id)
                if prior is not None:
                    raise FrameSourceConflictError("frame identity already belongs to another command")
                registered = await CandidateObjectRepository(session).get_exact(
                    user_id=user_id, project_name=project_name, candidate_id=frame_id
                )
                if registered is None:
                    await CandidateObjectRepository(session).insert(
                        user_id=user_id, project_name=project_name, candidate=candidate, created_at=datetime.now(UTC)
                    )
                elif registered != candidate:
                    raise FrameSourceConflictError("frame candidate id is registered for different bytes")
                receipt = FrameDerivationReceiptV1(
                    identity=identity,
                    frame_candidate_id=frame_id,
                    frame_byte_size=probe.byte_size,
                    frame_probe_digest=probe.probe_digest,
                    created_at=datetime.now(UTC),
                    command_digest=command_digest,
                )
                try:
                    await receipts.insert(command_id=command_id, receipt=receipt)
                except SpatialFrameReceiptConflictError as exc:
                    raise FrameSourceConflictError("frame command conflicts with an existing receipt") from exc
                return receipt


__all__ = [
    "FrameDerivationService",
    "FrameProbe",
    "FrameSourceConflictError",
    "decode_frame",
    "ffmpeg_decoder_identity",
    "publish_frame",
]
