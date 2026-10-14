"""Turn one reviewed projection into an M8 FORMAT candidate revision (M8-E E3).

The projection must have a succeeded render whose latest technical and semantic reports both pass,
and its plan's source master must still be the current head. The rendered file is registered as an
M7 candidate object of the projection's format slot, and a ``FormatCandidate`` revision naming the
render, both reports and the slot's candidate object is appended to the exploration candidate
``format:<plan id>``. Preview and promotion then go through the unchanged M8-A flow, which re-verifies
the same evidence through ``HostFormatEvidence``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from lib.candidate_store import prepare_candidate
from lib.db.models.formats import FormatRenderModel
from lib.db.repositories.advanced_creative import ExplorationRepository
from lib.db.repositories.formats import FormatRepository, report_digest
from lib.db.repositories.host_hardening import CandidateObjectRepository, MasterAuthorityRepository
from r2.advanced_creative.digests import digest_canonical, digest_payload
from r2.advanced_creative.errors import FormatNotFoundError, PromotionBindingStaleError
from r2.advanced_creative.formats import format_slot_key, parse_source_master_id
from r2.advanced_creative.lineage import HOST_PROFILE_ID, HOST_PROFILE_VERSION, host_policy_digest
from r2.contracts.advanced_creative import (
    ExplorationKind,
    ExplorationRevision,
    FormatCandidate,
    LineageBinding,
)
from r2.contracts.host_hardening import CandidateIdentity
from r2.host_hardening.master_authority import m7_candidate_id, stream_probe_digest


@dataclass(frozen=True)
class PreparedFormatCandidate:
    candidate_id: str
    revision: int
    head_version: int
    slot_key: str
    expected_target_version: int


def format_lineage(
    project_name: str, artifact_key: str, master_version: int, master_id: str, master_digest: str
) -> LineageBinding:
    """A projection's lineage: the exact source master it was rendered from."""
    return LineageBinding(
        project_name=project_name,
        content_basis_digest=digest_canonical(
            {
                "basis_kind": "format_source_master",
                "artifact_key": artifact_key,
                "master_version": master_version,
                "content_digest": master_digest,
            }
        ),
        approved_master_id=master_id,
        approved_master_digest=master_digest,
        creative_profile_id=HOST_PROFILE_ID,
        creative_profile_version=HOST_PROFILE_VERSION,
        policy_digest=host_policy_digest(),
    )


async def prepare_format_candidate(
    session: AsyncSession, *, user_id: str, project_name: str, project_dir: Path, execution_id: str, author: str
) -> PreparedFormatCandidate:
    render = await session.get(FormatRenderModel, (user_id, project_name, execution_id))
    if render is None:
        raise FormatNotFoundError("no succeeded render with this execution id")
    formats = FormatRepository(session)
    plan = await formats.get_plan(user_id=user_id, project_name=project_name, plan_id=render.plan_id)
    if plan is None:
        raise FormatNotFoundError("unknown format plan")
    reports = await formats.passing_reports(
        user_id=user_id, project_name=project_name, plan_id=plan.plan_id, artifact_digest=render.artifact_digest
    )
    if reports is None:
        raise PromotionBindingStaleError("technical and semantic reports do not both pass")
    technical, semantic = reports
    artifact_key, master_version = parse_source_master_id(plan.source_master_id)
    authorities = MasterAuthorityRepository(session)
    master = await authorities.get_current(user_id=user_id, project_name=project_name, artifact_key=artifact_key)
    if master is None or master.master_version != master_version or master.content_digest != plan.source_master_digest:
        raise PromotionBindingStaleError("the source master moved since the plan")

    slot_key = format_slot_key(artifact_key, plan.output_profile.profile_ref)
    object_id = m7_candidate_id(slot_key, execution_id)
    artifact = project_dir / render.artifact_ref
    verified = await asyncio.to_thread(
        lambda: prepare_candidate(
            identity=CandidateIdentity(
                candidate_id=object_id,
                user_id=user_id,
                project_name=project_name,
                artifact_key=slot_key,
                expected_content_digest=render.artifact_digest,
            ),
            source_file=artifact,
            final_path=artifact,
            media_root=project_dir,
            media_probe=stream_probe_digest,
        )
    )
    objects = CandidateObjectRepository(session)
    if await objects.get_exact(user_id=user_id, project_name=project_name, candidate_id=object_id) is None:
        await objects.insert(
            user_id=user_id, project_name=project_name, candidate=verified, created_at=datetime.now(UTC)
        )

    payload = FormatCandidate(
        kind=ExplorationKind.FORMAT,
        plan_digest=plan.plan_digest,
        rendered_artifact_ref=object_id,
        rendered_artifact_digest=render.artifact_digest,
        technical_report_id=technical.report_id,
        technical_report_digest=report_digest(technical),
        semantic_report_id=semantic.report_id,
        semantic_report_digest=report_digest(semantic),
        execution_id=execution_id,
    )
    lineage = format_lineage(
        project_name, artifact_key, master.master_version, master.candidate_id, master.content_digest
    )
    exploration = ExplorationRepository(session)
    candidate_id = f"format:{plan.plan_id}"
    head = await exploration.get_head(user_id=user_id, project_name=project_name, candidate_id=candidate_id)
    revision_no = 1 if head is None else head.current_revision + 1
    revision = ExplorationRevision(
        candidate_id=candidate_id,
        revision=revision_no,
        kind=ExplorationKind.FORMAT,
        parent_revision=None if head is None else head.current_revision,
        payload=payload,
        payload_digest=digest_payload(payload, lineage),
        lineage=lineage,
        created_by=author,
        created_at=datetime.now(UTC),
    )
    if head is not None:
        current = await exploration.get_exact(
            user_id=user_id, project_name=project_name, candidate_id=candidate_id, revision=head.current_revision
        )
        if current is not None and current.payload == payload:
            # The same evidence is already the candidate's current revision.
            slot = await authorities.get_current(user_id=user_id, project_name=project_name, artifact_key=slot_key)
            return PreparedFormatCandidate(
                candidate_id,
                head.current_revision,
                head.head_version,
                slot_key,
                0 if slot is None else slot.master_version,
            )
    appended = await exploration.append_revision(
        user_id=user_id,
        project_name=project_name,
        candidate=revision,
        expected_head_version=None if head is None else head.head_version,
        command_id=f"format-candidate:{execution_id}:{technical.report_id}:{semantic.report_id}",
    )
    slot = await authorities.get_current(user_id=user_id, project_name=project_name, artifact_key=slot_key)
    return PreparedFormatCandidate(
        candidate_id,
        appended.current_revision,
        appended.head_version,
        slot_key,
        0 if slot is None else slot.master_version,
    )


__all__ = ["PreparedFormatCandidate", "format_lineage", "prepare_format_candidate"]
