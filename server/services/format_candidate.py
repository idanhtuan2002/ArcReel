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

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.candidate_store import CandidateStoreError, prepare_candidate
from lib.db.models.formats import FormatRenderModel
from lib.db.repositories.advanced_creative import ExplorationRepository
from lib.db.repositories.formats import FormatRepository, report_digest
from lib.db.repositories.host_hardening import CandidateObjectRepository, MasterAuthorityRepository
from r2.advanced_creative.digests import digest_canonical, digest_payload
from r2.advanced_creative.errors import (
    FormatConflictError,
    FormatMediaMissingError,
    FormatNotFoundError,
    PromotionBindingStaleError,
)
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


async def _verified_evidence(session: AsyncSession, *, user_id: str, project_name: str, execution_id: str):
    """The render, plan, passing reports and source master; refuses anything stale."""
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
    artifact_key, master_version = parse_source_master_id(plan.source_master_id)
    master = await MasterAuthorityRepository(session).get_current(
        user_id=user_id, project_name=project_name, artifact_key=artifact_key
    )
    if master is None or master.master_version != master_version or master.content_digest != plan.source_master_digest:
        raise PromotionBindingStaleError("the source master moved since the plan")
    return render, plan, reports, artifact_key, master


async def prepare_format_candidate(
    sessions: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    project_name: str,
    project_dir: Path,
    execution_id: str,
    author: str,
) -> PreparedFormatCandidate:
    """Verify, register the candidate object outside any transaction, then append under locks.

    The final transaction re-reads every input under the plan's report lock, so the revision binds
    exactly the evidence that is current when it commits.
    """
    async with sessions() as session:
        render, plan, _reports, artifact_key, _master = await _verified_evidence(
            session, user_id=user_id, project_name=project_name, execution_id=execution_id
        )
    slot_key = format_slot_key(artifact_key, plan.output_profile.profile_ref)
    object_id = m7_candidate_id(slot_key, execution_id)
    artifact = project_dir / render.artifact_ref
    if not await asyncio.to_thread(artifact.is_file):
        raise FormatMediaMissingError("the rendered projection is missing; render it again")
    try:
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
    except FileNotFoundError as error:
        raise FormatMediaMissingError("the rendered projection is missing; render it again") from error
    except CandidateStoreError as error:
        raise FormatConflictError("the rendered projection changed or is not a valid candidate") from error

    async with sessions() as session, session.begin():
        await FormatRepository(session).lock_plan_reports(
            user_id=user_id, project_name=project_name, plan_id=plan.plan_id
        )
        render, plan, (technical, semantic), artifact_key, master = await _verified_evidence(
            session, user_id=user_id, project_name=project_name, execution_id=execution_id
        )
        authorities = MasterAuthorityRepository(session)
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
        slot = await authorities.get_current(user_id=user_id, project_name=project_name, artifact_key=slot_key)
        slot_version = 0 if slot is None else slot.master_version
        if head is not None:
            current = await exploration.get_exact(
                user_id=user_id, project_name=project_name, candidate_id=candidate_id, revision=head.current_revision
            )
            if current is not None and current.payload == payload:
                # The same evidence is already the candidate's current revision.
                return PreparedFormatCandidate(
                    candidate_id, head.current_revision, head.head_version, slot_key, slot_version
                )
        revision = ExplorationRevision(
            candidate_id=candidate_id,
            revision=1 if head is None else head.current_revision + 1,
            kind=ExplorationKind.FORMAT,
            parent_revision=None if head is None else head.current_revision,
            payload=payload,
            payload_digest=digest_payload(payload, lineage),
            lineage=lineage,
            created_by=author,
            created_at=datetime.now(UTC),
        )
        appended = await exploration.append_revision(
            user_id=user_id,
            project_name=project_name,
            candidate=revision,
            expected_head_version=None if head is None else head.head_version,
            command_id=f"format-candidate:{execution_id}:{technical.report_id}:{semantic.report_id}",
        )
        return PreparedFormatCandidate(
            candidate_id, appended.current_revision, appended.head_version, slot_key, slot_version
        )


__all__ = ["PreparedFormatCandidate", "format_lineage", "prepare_format_candidate"]
