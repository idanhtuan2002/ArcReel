"""Blind semantic review of a rendered format projection (M8-E E3, spec §10).

A reviewer opens a packet for one succeeded render: the source master and the projection, labelled
A and B in an order the server draws and keeps. The reviewer sees neither the order nor the plan,
profile or reframe. Each submitted review gives PASS/FAIL for every rubric item. After each review the
service appends a semantic report over every reviewer's review of that plan and artifact; with a
single reviewer the report carries the recorded sponsor deviation.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
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
from server.services.format_render import file_digest

Clock = Callable[[], datetime]


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
    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, clock: Clock | None = None) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))

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
        async with self._sessions() as session:
            render = await session.get(FormatRenderModel, (user_id, project_name, execution_id))
        if render is None or render.state != "SUCCEEDED" or render.artifact_ref is None:
            raise FormatNotFoundError("no succeeded render with this execution id")
        artifact, source = _inside(project_dir, render.artifact_ref), _inside(project_dir, source_ref)
        if await asyncio.to_thread(file_digest, artifact) != render.artifact_digest:
            raise FormatConflictError("the rendered artifact changed since it was rendered")
        if await asyncio.to_thread(file_digest, source) != render.source_digest:
            raise FormatConflictError("the source is not the master this render used")
        packet = FormatReviewPacketModel(
            user_id=user_id,
            project_name=project_name,
            packet_id=str(uuid.uuid4()),
            plan_id=render.plan_id,
            execution_id=execution_id,
            artifact_digest=str(render.artifact_digest),
            artifact_ref=render.artifact_ref,
            source_digest=render.source_digest,
            source_ref=source_ref,
            projection_label=secrets.choice("AB"),
            reviewer_id=reviewer_id,
            created_at=self._clock(),
        )
        async with self._sessions() as session, session.begin():
            session.add(packet)
        return ReviewPacket(packet.packet_id, SEMANTIC_RUBRIC, SEMANTIC_ITEMS, reviewed=False)

    async def _packet(
        self, session: AsyncSession, *, user_id: str, project_name: str, packet_id: str, reviewer_id: str
    ):
        packet = await session.get(FormatReviewPacketModel, (user_id, project_name, packet_id))
        if packet is None or packet.reviewer_id != reviewer_id:
            raise FormatNotFoundError("no such review packet for this reviewer")
        return packet

    async def clip(
        self, *, user_id: str, project_name: str, project_dir: Path, packet_id: str, label: str, reviewer_id: str
    ) -> Path:
        """The file behind label A or B, verified against its recorded digest."""
        if label not in ("A", "B"):
            raise FormatInvalidError("a clip label is A or B")
        async with self._sessions() as session:
            packet = await self._packet(
                session, user_id=user_id, project_name=project_name, packet_id=packet_id, reviewer_id=reviewer_id
            )
        projection = label == packet.projection_label
        path = _inside(project_dir, packet.artifact_ref if projection else packet.source_ref)
        expected = packet.artifact_digest if projection else packet.source_digest
        if await asyncio.to_thread(file_digest, path) != expected:
            raise FormatConflictError("the clip changed since the packet was opened")
        return path

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
            packet = await self._packet(
                session, user_id=user_id, project_name=project_name, packet_id=packet_id, reviewer_id=reviewer_id
            )
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
            packet.review_json = {"reviewer_id": reviewer_id, "items": dict(items), "note": note}
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
            repository = FormatRepository(session)
            plan = await repository.get_plan(user_id=user_id, project_name=project_name, plan_id=packet.plan_id)
            assert plan is not None
            reviews = [
                {"reviewer_id": row.review_json["reviewer_id"], "items": row.review_json["items"]}
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


__all__ = ["FormatReviewService", "ReviewPacket"]
