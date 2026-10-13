"""A typed spatial promotion preview binds one current LOCATION binding version, approval and selection."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.advanced_creative import ExplorationRepository
from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository
from r2.advanced_creative.errors import CandidateConflictError, CommandConflictError, PromotionBindingStaleError
from r2.contracts.advanced_creative import PromotionTargetKind
from server.services.governance_grants import CurrentShowrunnerGrantReader, ShowrunnerGrantUnavailableError
from server.services.spatial_pair_current_v2 import CurrentApprovedSpatialPairReaderV2
from server.services.spatial_promotion import SpatialPreviewCommand, SpatialPromotionService
from tests.integration.server.routers.spatial_approval_support import ApprovedLocation, approved_location
from tests.integration.server.routers.test_gates_export import PROJECT, USER
from tests.unit.r2.production_binding import spatial_constraint_fixture as fixture

type Factory = async_sessionmaker[AsyncSession]


async def spatial_candidate(factory: Factory, project_dir: Path, approved: ApprovedLocation) -> dict[str, str]:
    """Append the fixture SPATIAL revision normalized against the approved pair's exact frames."""
    current = await CurrentApprovedSpatialPairReaderV2(
        session_factory=factory, project_dir=project_dir, grants=approved.grants
    ).read_current(user_id=USER.id, project_name=PROJECT, target_id=approved.target_id)
    digests = {}
    async with factory() as session:
        for view in current.body.command.views:
            receipt = await SpatialFrameReceiptRepository(session).get_exact(
                user_id=USER.id, project_name=PROJECT, receipt_id=view.receipt_id
            )
            assert receipt is not None
            digests[view.role] = receipt.identity.frame_content_digest
    revision = fixture.revision(
        master_digest=digests["MASTER"], reverse_digest=digests["REVERSE"], project_name=PROJECT
    )
    async with factory() as session:
        await ExplorationRepository(session).append_revision(
            user_id=USER.id,
            project_name=PROJECT,
            candidate=revision,
            expected_head_version=None,
            command_id="spatial-rev-1",
        )
        await session.commit()
    return {
        assertion.subject_refs[0] if assertion.subject_refs else assertion.assertion_id: assertion.assertion_id
        for assertion in revision.payload.spatial.assertions
    }


def command(approved: ApprovedLocation, ids: dict[str, str], **overrides: object) -> SpatialPreviewCommand:
    base = SpatialPreviewCommand(
        user_id=USER.id,
        project_name=PROJECT,
        candidate_id="spatial-candidate-1",
        candidate_revision=1,
        target_id=approved.target_id,
        expected_binding_version=1,
        selected_assertion_ids=(ids["red fire extinguisher cabinet"], ids["yellow painting"]),
        command_id="spatial-preview-1",
    )
    return replace(base, **overrides)


@pytest.mark.asyncio
async def test_a_preview_derives_the_set_from_the_approved_pair_and_replays(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = await approved_location(gate_export_client, project_dir, session_factory, monkeypatch)
    ids = await spatial_candidate(session_factory, project_dir, approved)
    service = SpatialPromotionService(session_factory=session_factory, project_dir=project_dir, grants=approved.grants)

    preview = await service.create_preview(command(approved, ids))

    base = preview.base_preview
    assert (base.target.kind, base.target.target_ref, base.target.expected_target_version) == (
        PromotionTargetKind.PRODUCTION_BINDING,
        approved.binding_id,
        1,
    )
    proposal = preview.binding.proposal
    assert [c.relation_kind for c in proposal.constraints] == ["PRESERVE_ON_WALL", "SHARED_SIDE_ANCHOR"]
    assert (proposal.pair_version, proposal.pair_decision_digest) == (
        approved.approval.pair_version,
        approved.approval.decision_digest,
    )
    assert await service.create_preview(command(approved, ids)) == preview
    with pytest.raises(CommandConflictError):
        await service.create_preview(command(approved, ids, selected_assertion_ids=(ids["blue exit door"],)))


@pytest.mark.asyncio
async def test_a_stale_version_a_non_visible_selection_or_no_grant_is_refused(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = await approved_location(gate_export_client, project_dir, session_factory, monkeypatch)
    ids = await spatial_candidate(session_factory, project_dir, approved)
    service = SpatialPromotionService(session_factory=session_factory, project_dir=project_dir, grants=approved.grants)

    with pytest.raises(PromotionBindingStaleError):
        await service.create_preview(command(approved, ids, expected_binding_version=2, command_id="p-stale"))
    with pytest.raises(CandidateConflictError):
        await service.create_preview(
            command(approved, ids, selected_assertion_ids=(ids["radiator"],), command_id="p-inf")
        )
    foreign = CurrentShowrunnerGrantReader(key_id="other-key", public_key=bytes(32))
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await SpatialPromotionService(
            session_factory=session_factory, project_dir=project_dir, grants=foreign
        ).create_preview(command(approved, ids, command_id="p-grant"))
