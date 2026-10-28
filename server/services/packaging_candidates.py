"""Append M10-B packaging candidate revisions with server-derived bindings and provenance.

The client supplies only package content and presentation; the server binds the master, assessed subject,
profile, constraint snapshot, closures and M8 lineage from the named sealed run, and stamps provenance from the
authenticated principal (an interactive session is HUMAN, anything else AGENT). An alternative carried unchanged
from the parent revision keeps its recorded author.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Literal

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

import r2.contracts.quality as q
from lib.db.repositories.advanced_creative import APPEND_REVISION, MAX_HISTORY_PAGE, ExplorationRepository
from lib.db.repositories.quality import QualityProfileRepository
from lib.db.repositories.quality_runs import QualityRunRepository
from r2.advanced_creative.digests import digest_canonical, digest_payload
from r2.advanced_creative.exploration import uuid7
from r2.contracts.advanced_creative import (
    AudienceClassification,
    CandidateHead,
    DisclosureSet,
    ExplorationKind,
    ExplorationRevision,
    LineageBinding,
    LocalizedPackagingMetadata,
    M8ContractModel,
    PackagingAsset,
    PackagingCandidate,
    PackagingChapter,
    PackagingProvenance,
    PackagingVariant,
    VariantGroup,
    VariantProvenance,
)
from r2.quality.digests import compute_digest
from r2.quality.errors import ProfileStaleError, StaleHeadError, SubjectStaleError

type Sessions = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type AuthorKind = Literal["HUMAN", "AGENT"]


class DraftVariant(M8ContractModel):
    variant_id: str
    value: dict[str, object] | None
    asset_role: str | None


class DraftVariantGroup(M8ContractModel):
    group_id: str
    field: Literal["title", "description", "tags", "chapters", "thumbnail"]
    variants: tuple[DraftVariant, ...] = Field(min_length=1)


class PackagingDraft(M8ContractModel):
    """What a client may author: no bindings, digests or provenance."""

    title: str
    description: str
    tags: tuple[str, ...]
    hashtags: tuple[str, ...]
    chapters: tuple[PackagingChapter, ...]
    localization_variants: tuple[LocalizedPackagingMetadata, ...]
    audience_classification: AudienceClassification
    disclosure: DisclosureSet
    variant_groups: tuple[DraftVariantGroup, ...]
    assets: tuple[PackagingAsset, ...]


def _carried(parent: PackagingCandidate | None) -> dict[tuple[str, str], PackagingVariant]:
    if parent is None:
        return {}
    return {(g.group_id, v.variant_id): v for g in parent.variant_groups for v in g.variants}


def build_payload(
    draft: PackagingDraft,
    *,
    run: q.QualityRun,
    profile: q.QualityProfileRevision,
    actor_id: str,
    author_kind: AuthorKind,
    parent: PackagingCandidate | None,
) -> PackagingCandidate:
    """The complete PACKAGING payload with server bindings, provenance and both closure digests."""
    policy = profile.policy
    if not isinstance(policy, q.QualityPolicyV2):
        raise ProfileStaleError()
    carried = _carried(parent)
    stamp = VariantProvenance(author_kind=author_kind, actor_id=actor_id)
    groups = []
    for group in draft.variant_groups:
        variants = []
        for variant in group.variants:
            fresh = {"variant_id": variant.variant_id, "value": variant.value, "asset_role": variant.asset_role}
            previous = carried.get((group.group_id, variant.variant_id))
            same = (
                previous is not None
                and PackagingVariant.model_validate(fresh | {"provenance": previous.provenance}) == previous
            )
            variants.append(fresh | {"provenance": previous.provenance if same and previous else stamp})
        groups.append({"group_id": group.group_id, "field": group.field, "variants": variants})
    body = draft.model_dump(mode="python") | {
        "kind": ExplorationKind.PACKAGING,
        "approved_master_id": run.subject.master_binding.root.candidate_id,
        "approved_master_digest": run.subject.artifact_digest,
        "assessed_subject_digest": run.subject_digest,
        "quality_profile_id": profile.profile_id,
        "quality_profile_revision": profile.revision,
        "quality_profile_digest": profile.profile_digest,
        "platform_profile_id": policy.platform_constraints.platform_profile_id,
        "platform_profile_revision": policy.platform_constraints.platform_profile_revision,
        "constraint_snapshot_digest": compute_digest("m10.platform-constraints.v1", policy.platform_constraints),
        "variant_groups": [VariantGroup.model_validate(g) for g in groups],
        "content_closure_digest": "sha256:" + "0" * 64,
        "presentation_closure_digest": "sha256:" + "0" * 64,
        "provenance": [
            PackagingProvenance(field_group="content", author_kind=author_kind, actor_id=actor_id),
            PackagingProvenance(field_group="presentation", author_kind=author_kind, actor_id=actor_id),
        ],
    }
    draft_payload = PackagingCandidate.model_validate(body)
    return PackagingCandidate.model_validate(
        body
        | {
            "content_closure_digest": compute_digest("m10.packaging-content.v1", draft_payload),
            "presentation_closure_digest": compute_digest("m10.packaging-presentation.v1", draft_payload),
        }
    )


async def append_packaging_revision(
    sessions: Sessions,
    *,
    user_id: str,
    project_name: str,
    actor_id: str,
    author_kind: AuthorKind,
    run_id: str,
    candidate_id: str | None,
    expected_head_version: int | None,
    command_id: str,
    draft: PackagingDraft,
    clock: Callable[[], datetime],
) -> tuple[ExplorationRevision, CandidateHead]:
    """Append the next PACKAGING revision (or a new candidate) bound to ``run_id``; M8 CAS and receipts apply."""
    async with sessions() as session:
        run = await QualityRunRepository(session).run(user_id=user_id, project_name=project_name, run_id=run_id)
        if run is None:
            raise SubjectStaleError()
        profile = await QualityProfileRepository(session).get_revision(
            user_id=user_id, project_name=project_name, profile_id=run.profile_id, revision=run.profile_revision
        )
        if profile is None or profile.profile_digest != run.profile_digest:
            raise ProfileStaleError()
        m8 = ExplorationRepository(session)
        replayed = await _replay(m8, user_id=user_id, project_name=project_name, command_id=command_id)
        if replayed is not None:
            return replayed
        identifier = candidate_id or uuid7()
        head = (
            None
            if candidate_id is None
            else await m8.get_head(user_id=user_id, project_name=project_name, candidate_id=identifier)
        )
        parent = None
        if head is not None:
            current = await m8.get_exact(
                user_id=user_id, project_name=project_name, candidate_id=identifier, revision=head.current_revision
            )
            if current is None or current.kind is not ExplorationKind.PACKAGING:
                raise StaleHeadError()
            parent = current.payload if isinstance(current.payload, PackagingCandidate) else None
        elif candidate_id is not None:
            raise StaleHeadError()
        payload = build_payload(
            draft, run=run, profile=profile, actor_id=actor_id, author_kind=author_kind, parent=parent
        )
        lineage = LineageBinding(
            project_name=project_name,
            content_basis_digest=run.subject.content_basis_digest,
            approved_master_id=payload.approved_master_id,
            approved_master_digest=payload.approved_master_digest,
            creative_profile_id=run.profile_id,
            creative_profile_version=str(run.profile_revision),
            policy_digest=profile.policy_digest,
        )
        revision_number = 1 if head is None else head.current_revision + 1
        revision = ExplorationRevision(
            candidate_id=identifier,
            revision=revision_number,
            kind=ExplorationKind.PACKAGING,
            parent_revision=None if head is None else head.current_revision,
            payload=payload,
            payload_digest=digest_payload(payload, lineage),
            lineage=lineage,
            created_by=user_id,
            created_at=clock(),
        )
        appended = await m8.append_revision(
            user_id=user_id,
            project_name=project_name,
            candidate=revision,
            expected_head_version=expected_head_version,
            command_id=command_id,
        )
        await session.commit()
    return revision, appended


async def _replay(
    m8: ExplorationRepository, *, user_id: str, project_name: str, command_id: str
) -> tuple[ExplorationRevision, CandidateHead] | None:
    """Receipt-first: the revision an earlier call of this command appended (head version equals revision)."""
    receipt = await m8.get_command_receipt(
        user_id=user_id,
        project_name=project_name,
        actor_scope=user_id,
        operation=APPEND_REVISION,
        command_id=command_id,
    )
    if receipt is None:
        return None
    after: int | None = None
    while True:
        page = await m8.history(
            user_id=user_id,
            project_name=project_name,
            candidate_id=receipt.result_ref,
            after_revision=after,
            limit=MAX_HISTORY_PAGE,
        )
        for revision in page:
            head = CandidateHead(
                candidate_id=revision.candidate_id, current_revision=revision.revision, head_version=revision.revision
            )
            if digest_canonical(head) == receipt.result_digest and revision.kind is ExplorationKind.PACKAGING:
                return revision, head
        if len(page) < MAX_HISTORY_PAGE:
            raise StaleHeadError()
        after = page[-1].revision


__all__ = ["DraftVariant", "DraftVariantGroup", "PackagingDraft", "append_packaging_revision", "build_payload"]
