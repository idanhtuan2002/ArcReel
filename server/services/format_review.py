"""Blind semantic review of a rendered format projection (M8-E E3, spec §10).

Only a reviewer holding a current HUMAN_SHOWRUNNER grant for the project may open a packet or submit a
review; the grant event digest is recorded on the packet and in the review, so the single-reviewer
sponsor deviation is bound to that authorized principal.

A packet covers one succeeded render: the source master and the projection, labelled A and B in an
order the server draws and keeps. The reviewer is served two per-packet review copies, remuxed from
verified snapshots with metadata stripped and a random per-packet tag, so neither copy carries the
bytes, digest, name or timestamps of a recorded file. What blindness cannot hide is what the clips
show: the projection has the target's shape. After each review the service appends a semantic report
over every reviewer's review of that plan and artifact, serialized per plan.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.formats import FormatRenderModel, FormatReviewPacketModel
from lib.db.repositories.formats import FormatRepository
from r2.advanced_creative.errors import FormatConflictError, FormatNotFoundError
from r2.advanced_creative.formats import (
    SEMANTIC_ITEMS,
    SEMANTIC_RUBRIC,
    SINGLE_REVIEWER_DEVIATION,
    FormatInvalidError,
)
from r2.contracts.advanced_creative import CanonicalJsonObject, SemanticParityReport
from r2.governance.grant_transition import GrantScopeV1
from server.services.format_render import (
    FormatRenderFailedError,
    file_digest,
    run_process,
    snapshot_dir,
    verified_snapshot,
)
from server.services.governance_grants import CurrentShowrunnerGrantReader

Clock = Callable[[], datetime]

REVIEW_DIR = "formats/.review"


@dataclass(frozen=True)
class ReviewPacket:
    packet_id: str
    rubric_version: str
    items: tuple[str, ...]
    reviewed: bool


def _inside(project_dir: Path, ref: str) -> Path:
    path = (project_dir / ref).resolve()
    if not path.is_relative_to(project_dir.resolve()):
        raise FormatInvalidError("media must live inside the project")
    return path


class FormatReviewService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        grants: CurrentShowrunnerGrantReader,
        ffmpeg: str = "ffmpeg",
        clock: Clock | None = None,
    ) -> None:
        self._sessions = sessions
        self._grants = grants
        self._ffmpeg = ffmpeg
        self._clock = clock or (lambda: datetime.now(UTC))

    async def _grant_digest(self, session: AsyncSession, *, user_id: str, project_name: str, reviewer_id: str) -> str:
        event = await self._grants.require_current_locked(
            session, scope=GrantScopeV1(user_id=user_id, project_name=project_name, principal=reviewer_id)
        )
        return event.event_digest

    async def _neutral_copy(self, snapshot: Path, destination: Path) -> str:
        """A stream copy of ``snapshot`` without container metadata, tagged with a random value."""
        command = [
            self._ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(snapshot),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c",
            "copy",
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-metadata",
            f"comment={secrets.token_hex(16)}",
            "-movflags",
            "+faststart",
            "-f",
            "mp4",
            str(destination),
        ]
        async with asyncio.timeout(600):
            code, _output = await run_process(command)
        if code != 0:
            raise FormatRenderFailedError("the review copy could not be prepared")
        return await asyncio.to_thread(file_digest, destination)

    async def open_packet(
        self,
        *,
        user_id: str,
        project_name: str,
        project_dir: Path,
        execution_id: str,
        source_ref: str,
        reviewer_id: str,
    ) -> ReviewPacket:
        if not reviewer_id:
            raise FormatInvalidError("a review packet names its reviewer")
        async with self._sessions() as session, session.begin():
            await self._grant_digest(session, user_id=user_id, project_name=project_name, reviewer_id=reviewer_id)
            render = await session.get(FormatRenderModel, (user_id, project_name, execution_id))
        if render is None:
            raise FormatNotFoundError("no succeeded render with this execution id")
        artifact, source = _inside(project_dir, render.artifact_ref), _inside(project_dir, source_ref)
        packet_id = str(uuid.uuid4())
        projection_label = secrets.choice("AB")
        folder = project_dir / REVIEW_DIR / packet_id
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        clips: dict[str, tuple[str, str]] = {}
        try:
            work = snapshot_dir(project_dir)
            async with (
                verified_snapshot(artifact, render.artifact_digest, work) as projection_copy,
                verified_snapshot(source, render.source_digest, work) as source_copy,
            ):
                for label in ("A", "B"):
                    snapshot = projection_copy if label == projection_label else source_copy
                    name = f"{secrets.token_hex(16)}.mp4"
                    digest = await self._neutral_copy(snapshot, folder / name)
                    clips[label] = (f"{REVIEW_DIR}/{packet_id}/{name}", digest)
            async with self._sessions() as session, session.begin():
                # The grant is re-checked in the transaction that records it.
                grant = await self._grant_digest(
                    session, user_id=user_id, project_name=project_name, reviewer_id=reviewer_id
                )
                session.add(
                    FormatReviewPacketModel(
                        user_id=user_id,
                        project_name=project_name,
                        packet_id=packet_id,
                        plan_id=render.plan_id,
                        execution_id=execution_id,
                        artifact_digest=str(render.artifact_digest),
                        artifact_ref=render.artifact_ref,
                        source_digest=render.source_digest,
                        source_ref=source_ref,
                        projection_label=projection_label,
                        reviewer_id=reviewer_id,
                        grant_event_digest=grant,
                        clip_a_ref=clips["A"][0],
                        clip_a_digest=clips["A"][1],
                        clip_b_ref=clips["B"][0],
                        clip_b_digest=clips["B"][1],
                        created_at=self._clock(),
                    )
                )
        except BaseException:
            await asyncio.to_thread(shutil.rmtree, folder, True)
            raise
        return ReviewPacket(packet_id, SEMANTIC_RUBRIC, SEMANTIC_ITEMS, reviewed=False)

    async def _packet(
        self, session: AsyncSession, *, user_id: str, project_name: str, packet_id: str, reviewer_id: str
    ) -> FormatReviewPacketModel:
        packet = await session.get(FormatReviewPacketModel, (user_id, project_name, packet_id))
        if packet is None or packet.reviewer_id != reviewer_id:
            raise FormatNotFoundError("no such review packet for this reviewer")
        return packet

    async def clip(
        self, *, user_id: str, project_name: str, project_dir: Path, packet_id: str, label: str, reviewer_id: str
    ) -> tuple[Path, str]:
        """The review copy behind label A or B and its recorded digest; the caller snapshots it."""
        if label not in ("A", "B"):
            raise FormatInvalidError("a clip label is A or B")
        async with self._sessions() as session, session.begin():
            await self._grant_digest(session, user_id=user_id, project_name=project_name, reviewer_id=reviewer_id)
            packet = await self._packet(
                session, user_id=user_id, project_name=project_name, packet_id=packet_id, reviewer_id=reviewer_id
            )
        ref, digest = (
            (packet.clip_a_ref, packet.clip_a_digest) if label == "A" else (packet.clip_b_ref, packet.clip_b_digest)
        )
        if ref is None or digest is None:
            raise FormatNotFoundError("this packet has no review copies; open a new packet")
        return _inside(project_dir, ref), digest

    async def submit(
        self,
        *,
        user_id: str,
        project_name: str,
        packet_id: str,
        reviewer_id: str,
        items: dict[str, str],
        note: str,
    ) -> SemanticParityReport:
        if set(items) != set(SEMANTIC_ITEMS) or any(verdict not in ("PASS", "FAIL") for verdict in items.values()):
            raise FormatInvalidError("a review gives PASS or FAIL for every rubric item")
        if len(note) > 2000:
            raise FormatInvalidError("the note is at most 2000 characters")
        async with self._sessions() as session, session.begin():
            grant = await self._grant_digest(
                session, user_id=user_id, project_name=project_name, reviewer_id=reviewer_id
            )
            packet = await self._packet(
                session, user_id=user_id, project_name=project_name, packet_id=packet_id, reviewer_id=reviewer_id
            )
            if packet.grant_event_digest is None:
                raise FormatConflictError("this packet was not opened under a grant; open a new packet")
            repository = FormatRepository(session)
            # Reviews of one plan are serialized: the duplicate checks and the aggregation below read
            # every committed review, so concurrent reviewers cannot each miss the other's verdicts.
            await repository.lock_plan_reports(user_id=user_id, project_name=project_name, plan_id=packet.plan_id)
            await session.refresh(packet)
            if packet.review_json is not None:
                raise FormatConflictError("this packet already has its review")
            model = FormatReviewPacketModel
            earlier = await session.scalar(
                select(model.packet_id).where(
                    model.user_id == user_id,
                    model.project_name == project_name,
                    model.plan_id == packet.plan_id,
                    model.artifact_digest == packet.artifact_digest,
                    model.reviewer_id == reviewer_id,
                    model.review_json.is_not(None),
                )
            )
            if earlier is not None:
                raise FormatConflictError("this reviewer already reviewed this projection")
            packet.review_json = {
                "reviewer_id": reviewer_id,
                "grant_event_digest": grant,
                "items": dict(items),
                "note": note,
            }
            packet.reviewed_at = self._clock()
            await session.flush()
            reviewed = (
                await session.scalars(
                    select(model)
                    .where(
                        model.user_id == user_id,
                        model.project_name == project_name,
                        model.plan_id == packet.plan_id,
                        model.artifact_digest == packet.artifact_digest,
                        model.review_json.is_not(None),
                    )
                    .order_by(model.reviewer_id)
                )
            ).all()
            plan = await repository.get_plan(user_id=user_id, project_name=project_name, plan_id=packet.plan_id)
            assert plan is not None
            reviews = [
                {
                    "reviewer_id": row.review_json["reviewer_id"],
                    "grant_event_digest": row.review_json.get("grant_event_digest"),
                    "items": row.review_json["items"],
                }
                for row in reviewed
                if row.review_json is not None
            ]
            per_item = {item: {review["items"][item] for review in reviews} for item in SEMANTIC_ITEMS}
            disagreement = any(len(verdicts) > 1 for verdicts in per_item.values())
            passed = not disagreement and all(verdicts == {"PASS"} for verdicts in per_item.values())
            reviewers = "\x1f".join(review["reviewer_id"] for review in reviews)
            report = SemanticParityReport(
                report_id="sem-"
                + hashlib.sha256(f"{packet.plan_id}\x1f{packet.artifact_digest}\x1f{reviewers}".encode()).hexdigest()[
                    :32
                ],
                plan_digest=plan.plan_digest,
                source_master_digest=plan.source_master_digest,
                artifact_digest=packet.artifact_digest,
                rubric_version=SEMANTIC_RUBRIC,
                reviews=tuple(CanonicalJsonObject.model_validate(review) for review in reviews),
                material_disagreement=disagreement,
                passed=passed,
            )
            return await repository.append_semantic_report(
                user_id=user_id,
                project_name=project_name,
                plan_id=packet.plan_id,
                report=report,
                deviation=SINGLE_REVIEWER_DEVIATION if len(reviews) < 2 else None,
            )


__all__ = ["REVIEW_DIR", "FormatReviewService", "ReviewPacket"]
