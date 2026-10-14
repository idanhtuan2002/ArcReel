"""Preview-bound M8 promotion on a real database (plan Task A3, ADR-0097)."""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.candidate_store import prepare_candidate
from lib.db.models.advanced_creative import (
    M8CandidateRevisionModel,
    M8CommandReceiptModel,
    M8PromotionAuthorizationModel,
    M8PromotionReceiptModel,
)
from lib.db.models.host_hardening import MasterHeadVersionModel
from lib.db.repositories.advanced_creative import ExplorationRepository
from lib.db.repositories.host_hardening import CandidateObjectRepository, MasterAuthorityRepository
from r2.advanced_creative.digests import digest_canonical, digest_payload
from r2.advanced_creative.errors import (
    CandidateConflictError,
    CommandConflictError,
    ExplorationNotFoundError,
    PromotionBindingStaleError,
    PromotionTargetUnavailableError,
)
from r2.advanced_creative.promotion import ExplorationPromotion
from r2.contracts.advanced_creative import (
    CanvasCandidate,
    ExplorationKind,
    ExplorationRevision,
    FormatCandidate,
    LineageBinding,
    PromotionAuthorization,
    PromotionPreview,
    PromotionTarget,
    PromotionTargetKind,
)
from r2.contracts.host_hardening import CandidateIdentity
from r2.host_hardening.master_authority import MasterAuthorityUnit, stream_probe_digest
from server.services import advanced_creative as composition
from server.services.master_authority import master_authority_unit

type Factory = async_sessionmaker[AsyncSession]

USER = "default"
PROJECT = "demo"
SLOT = "m8-slot:demo:vertical-1"
DIGEST = "sha256:" + "a" * 64


class _AcceptFormatEvidence:
    """Tests of the M8-A flow itself; the format evidence gate has its own tests."""

    async def verify(self, **_kwargs: object) -> None:
        return None


def _video(path: Path, tag: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x36:d=0.2",
            "-metadata",
            f"comment={tag}",
            "-y",
            str(path),
        ],
        check=True,
    )
    return path.resolve()


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


async def _slot_with_master(factory: Factory, root: Path) -> tuple[str, str]:
    """A slot whose master is object A, and a registered object B; returns B's id and digest."""
    first = _video(root / "objects" / "a.mp4", "a")
    async with factory() as session:
        await master_authority_unit(session).promote_staged(
            user_id=USER,
            project_name=PROJECT,
            project_dir=root,
            artifact_key=SLOT,
            generation_candidate_id="render-a",
            version_file=first,
            expected_content_digest=_sha(first),
            approval_record="APR-a",
            command_id="seed-a",
        )
    return await _registered_object(factory, root, "b")


async def _registered_object(factory: Factory, root: Path, tag: str, artifact_key: str = SLOT) -> tuple[str, str]:
    """Register a new candidate object for ``artifact_key``; returns its id and digest."""
    video = _video(root / "objects" / f"{tag}.mp4", tag)
    candidate_id = f"m7c:render-{tag}"
    verified = prepare_candidate(
        identity=CandidateIdentity(
            candidate_id=candidate_id,
            user_id=USER,
            project_name=PROJECT,
            artifact_key=artifact_key,
            expected_content_digest=_sha(video),
        ),
        source_file=video,
        final_path=video,
        media_root=root,
        media_probe=stream_probe_digest,
    )
    async with factory() as session:
        await CandidateObjectRepository(session).insert(
            user_id=USER, project_name=PROJECT, candidate=verified, created_at=datetime.now(UTC)
        )
        await session.commit()
    return candidate_id, verified.content_digest


def _lineage() -> LineageBinding:
    return LineageBinding(
        project_name=PROJECT,
        content_basis_digest=DIGEST,
        approved_master_id=None,
        approved_master_digest=None,
        creative_profile_id="profile",
        creative_profile_version="1",
        policy_digest=DIGEST,
    )


def _format_revision(object_id: str, object_digest: str, *, candidate_id: str = "c-format") -> ExplorationRevision:
    payload = FormatCandidate(
        kind=ExplorationKind.FORMAT,
        plan_digest=DIGEST,
        rendered_artifact_ref=object_id,
        rendered_artifact_digest=object_digest,
        technical_report_id="t",
        technical_report_digest=DIGEST,
        semantic_report_id="s",
        semantic_report_digest=DIGEST,
        execution_id="exec-1",
    )
    return ExplorationRevision(
        candidate_id=candidate_id,
        revision=1,
        kind=ExplorationKind.FORMAT,
        parent_revision=None,
        payload=payload,
        payload_digest=digest_payload(payload, _lineage()),
        lineage=_lineage(),
        created_by=USER,
        created_at=datetime.now(UTC),
    )


async def _append(factory: Factory, revision: ExplorationRevision, command: str = "append-1") -> None:
    async with factory() as session:
        await composition.exploration_service(session, format_evidence=_AcceptFormatEvidence()).append_revision(
            user_id=USER, project_name=PROJECT, candidate=revision, expected_head_version=None, command_id=command
        )


async def _preview(
    factory: Factory,
    *,
    candidate_id: str = "c-format",
    target_ref: str = SLOT,
    kind: PromotionTargetKind = PromotionTargetKind.ARTIFACT_SLOT,
    version: int = 1,
    command: str = "preview-1",
) -> PromotionPreview:
    async with factory() as session:
        return await composition.exploration_service(session, format_evidence=_AcceptFormatEvidence()).create_preview(
            user_id=USER,
            project_name=PROJECT,
            candidate_id=candidate_id,
            revision=1,
            target=PromotionTarget(kind=kind, target_ref=target_ref, expected_target_version=version),
            command_id=command,
        )


def _authorization(
    preview: PromotionPreview, command: str = "promote-1", **overrides: object
) -> PromotionAuthorization:
    fields: dict[str, object] = {
        "command_id": command,
        "project_name": PROJECT,
        "preview_id": preview.preview_id,
        "preview_digest": digest_canonical(preview),
        "actor_id": USER,
        "actor_scope": USER,
        "decision": "APPROVE",
        "authorized_at": datetime.now(UTC),
    }
    return PromotionAuthorization(**(fields | overrides))


async def _promote(factory: Factory, authorization: PromotionAuthorization, head_version: int = 1, *, clock=None):
    async with factory() as session:
        service = (
            composition.exploration_promotion(session, format_evidence=_AcceptFormatEvidence())
            if clock is None
            else ExplorationPromotion(
                store=ExplorationRepository(session),
                slots=composition.HostSlotAuthority(session),
                commit=session.commit,
                clock=clock,
                format_evidence=_AcceptFormatEvidence(),
            )
        )
        return await service.promote(
            user_id=USER,
            project_name=PROJECT,
            authorization=authorization,
            expected_candidate_head_version=head_version,
        )


async def _count(factory: Factory, model) -> int:
    async with factory() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def _master(factory: Factory):
    async with factory() as session:
        return await MasterAuthorityRepository(session).get_current(
            user_id=USER, project_name=PROJECT, artifact_key=SLOT
        )


async def test_a_previewed_format_candidate_replaces_the_slot_master_once(
    session_factory: Factory, tmp_path: Path
) -> None:
    object_id, object_digest = await _slot_with_master(session_factory, tmp_path)
    await _append(session_factory, _format_revision(object_id, object_digest))
    preview = await _preview(session_factory)

    authorization = _authorization(preview)
    receipt = await _promote(session_factory, authorization)
    replay = await _promote(session_factory, authorization)
    with pytest.raises(CommandConflictError):
        await _promote(session_factory, _authorization(preview, authorized_at=datetime.now(UTC) + timedelta(seconds=1)))

    master = await _master(session_factory)
    assert master is not None
    assert (master.master_version, master.candidate_id, master.content_digest) == (2, object_id, object_digest)
    assert (receipt.result_master_id, receipt.result_digest, receipt.result_artifact_ref) == (
        object_id,
        object_digest,
        SLOT,
    )
    assert replay == receipt
    assert await _count(session_factory, M8PromotionReceiptModel) == 1
    assert await _count(session_factory, MasterHeadVersionModel) == 2


async def test_a_preview_replays_and_a_reused_preview_command_conflicts(
    session_factory: Factory, tmp_path: Path
) -> None:
    object_id, object_digest = await _slot_with_master(session_factory, tmp_path)
    await _append(session_factory, _format_revision(object_id, object_digest))

    first = await _preview(session_factory)
    again = await _preview(session_factory)

    assert again == first
    with pytest.raises(CommandConflictError):
        await _preview(session_factory, version=7)


@pytest.mark.parametrize("case", ["expired", "digest", "scope"])
async def test_a_stale_or_foreign_binding_writes_nothing(session_factory: Factory, tmp_path: Path, case: str) -> None:
    object_id, object_digest = await _slot_with_master(session_factory, tmp_path)
    await _append(session_factory, _format_revision(object_id, object_digest))
    preview = await _preview(session_factory)
    authorization = _authorization(preview)
    clock = None
    if case == "expired":
        clock = lambda: preview.expires_at + timedelta(seconds=1)  # noqa: E731
    elif case == "digest":
        authorization = _authorization(preview, preview_digest="sha256:" + "b" * 64)
    else:
        authorization = _authorization(preview, actor_scope="someone-else")

    with pytest.raises(PromotionBindingStaleError):
        await _promote(session_factory, authorization, clock=clock)

    assert await _count(session_factory, M8PromotionAuthorizationModel) == 0
    assert (await _master(session_factory)).master_version == 1


async def test_a_moved_master_or_candidate_head_refuses_the_promotion(session_factory: Factory, tmp_path: Path) -> None:
    object_id, object_digest = await _slot_with_master(session_factory, tmp_path)
    await _append(session_factory, _format_revision(object_id, object_digest))
    preview = await _preview(session_factory)
    with pytest.raises(CandidateConflictError):
        await _promote(session_factory, _authorization(preview), head_version=5)
    # Another writer moves the slot master after the preview.
    third = _video(tmp_path / "objects" / "c.mp4", "c")
    async with session_factory() as session:
        await master_authority_unit(session).promote_staged(
            user_id=USER,
            project_name=PROJECT,
            project_dir=tmp_path,
            artifact_key=SLOT,
            generation_candidate_id="render-c",
            version_file=third,
            expected_content_digest=_sha(third),
            approval_record="APR-c",
            command_id="seed-c",
        )

    with pytest.raises(PromotionBindingStaleError):
        await _promote(session_factory, _authorization(preview, command="promote-2"))

    assert await _count(session_factory, M8PromotionReceiptModel) == 0


async def test_unavailable_targets_are_refused_before_any_write(session_factory: Factory, tmp_path: Path) -> None:
    object_id, object_digest = await _slot_with_master(session_factory, tmp_path)
    await _append(session_factory, _format_revision(object_id, object_digest))
    canvas_payload = CanvasCandidate(
        kind=ExplorationKind.CANVAS,
        graph_schema_version="1",
        nodes=(),
        edges=(),
        groups=(),
        storyboard_order=(),
        viewport_bookmarks=(),
    )
    canvas = ExplorationRevision(
        candidate_id="c-canvas",
        revision=1,
        kind=ExplorationKind.CANVAS,
        parent_revision=None,
        payload=canvas_payload,
        payload_digest=digest_payload(canvas_payload, _lineage()),
        lineage=_lineage(),
        created_by=USER,
        created_at=datetime.now(UTC),
    )
    await _append(session_factory, canvas, command="append-canvas")

    with pytest.raises(PromotionTargetUnavailableError):
        await _preview(session_factory, candidate_id="c-canvas", command="p-canvas")
    with pytest.raises(PromotionTargetUnavailableError):
        await _preview(
            session_factory, target_ref="artifact-key-v1:WyJlcGlzb2RlLXZpZGVvIiwxLCJTSDAxIl0", command="p-manifest"
        )
    with pytest.raises(PromotionTargetUnavailableError):
        await _preview(session_factory, kind=PromotionTargetKind.PRODUCTION_BINDING, version=0, command="p-binding")
    with pytest.raises(ExplorationNotFoundError):
        await _preview(session_factory, candidate_id="c-missing", command="p-missing")
    assert await _count(session_factory, M8CommandReceiptModel) == 2  # the two appends


async def test_an_authority_failure_rolls_every_row_back(
    session_factory: Factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    object_id, object_digest = await _slot_with_master(session_factory, tmp_path)
    await _append(session_factory, _format_revision(object_id, object_digest))
    preview = await _preview(session_factory)

    async def fail(self, **kwargs):
        raise RuntimeError("authority unavailable")

    monkeypatch.setattr(MasterAuthorityUnit, "promote_registered", fail)
    with pytest.raises(RuntimeError, match="authority unavailable"):
        await _promote(session_factory, _authorization(preview))

    assert await _count(session_factory, M8PromotionAuthorizationModel) == 0
    assert await _count(session_factory, M8PromotionReceiptModel) == 0
    assert (await _master(session_factory)).master_version == 1


async def test_a_stored_payload_changed_under_its_digest_is_refused(session_factory: Factory, tmp_path: Path) -> None:
    object_id, object_digest = await _slot_with_master(session_factory, tmp_path)
    await _append(session_factory, _format_revision(object_id, object_digest))
    preview = await _preview(session_factory)
    other_id, other_digest = await _registered_object(session_factory, tmp_path, "c")
    async with session_factory() as session:
        row = (await session.execute(select(M8CandidateRevisionModel))).scalar_one()
        row.payload_json = row.payload_json | {
            "rendered_artifact_ref": other_id,
            "rendered_artifact_digest": other_digest,
        }
        await session.commit()

    with pytest.raises(PromotionBindingStaleError):
        await _promote(session_factory, _authorization(preview))

    assert await _count(session_factory, M8PromotionReceiptModel) == 0
    assert (await _master(session_factory)).master_version == 1


async def test_an_object_registered_for_another_slot_is_refused(session_factory: Factory, tmp_path: Path) -> None:
    await _slot_with_master(session_factory, tmp_path)
    foreign_id, foreign_digest = await _registered_object(
        session_factory, tmp_path, "elsewhere", artifact_key="m8-slot:demo:square-1"
    )
    await _append(session_factory, _format_revision(foreign_id, foreign_digest))
    preview = await _preview(session_factory)

    with pytest.raises(PromotionBindingStaleError):
        await _promote(session_factory, _authorization(preview))

    assert await _count(session_factory, M8PromotionAuthorizationModel) == 0
    assert (await _master(session_factory)).master_version == 1


async def test_a_failure_after_the_authority_staged_its_writes_rolls_every_row_back(
    session_factory: Factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    object_id, object_digest = await _slot_with_master(session_factory, tmp_path)
    await _append(session_factory, _format_revision(object_id, object_digest))
    preview = await _preview(session_factory)
    staged: list[int] = []
    original = ExplorationRepository.stage_promotion_receipt

    async def fail_after_the_m7_writes(self, **kwargs):
        staged.append(
            int((await self.session.execute(select(func.count()).select_from(MasterHeadVersionModel))).scalar_one())
        )
        raise RuntimeError("receipt store unavailable")

    monkeypatch.setattr(ExplorationRepository, "stage_promotion_receipt", fail_after_the_m7_writes)
    with pytest.raises(RuntimeError, match="receipt store unavailable"):
        await _promote(session_factory, _authorization(preview))
    monkeypatch.setattr(ExplorationRepository, "stage_promotion_receipt", original)

    assert staged == [2]
    assert await _count(session_factory, MasterHeadVersionModel) == 1
    assert await _count(session_factory, M8PromotionAuthorizationModel) == 0
    assert (await _master(session_factory)).master_version == 1


async def test_concurrent_promotions_of_one_preview_have_one_winner(
    concurrent_session_factory: Factory, tmp_path: Path
) -> None:
    async with concurrent_session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("row locks between sessions need PostgreSQL")
    factory = concurrent_session_factory
    object_id, object_digest = await _slot_with_master(factory, tmp_path)
    await _append(factory, _format_revision(object_id, object_digest))
    preview = await _preview(factory)

    results = await asyncio.gather(
        _promote(factory, _authorization(preview, command="promote-a")),
        _promote(factory, _authorization(preview, command="promote-b")),
        return_exceptions=True,
    )

    winners = [result for result in results if not isinstance(result, BaseException)]
    losers = [result for result in results if isinstance(result, BaseException)]
    assert len(winners) == 1, results
    assert all(isinstance(loser, (PromotionBindingStaleError, CandidateConflictError)) for loser in losers), losers
    assert await _count(factory, M8PromotionReceiptModel) == 1
    assert (await _master(factory)).master_version == 2
