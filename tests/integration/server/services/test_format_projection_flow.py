"""The whole M8-E flow on real M7 authority: render, measure, review, candidate, preview, promote."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.formats import FormatRepository
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from r2.advanced_creative.digests import digest_canonical
from r2.advanced_creative.errors import PromotionBindingStaleError
from r2.advanced_creative.formats import (
    SEMANTIC_ITEMS,
    Box,
    ReframeKind,
    build_plan,
    format_slot_key,
    reframe_decision,
    source_master_id,
)
from r2.contracts.advanced_creative import (
    CanonicalJsonObject,
    PromotionAuthorization,
    PromotionTarget,
    PromotionTargetKind,
)
from server.services import advanced_creative as composition
from server.services.format_candidate import prepare_format_candidate
from server.services.format_render import ffmpeg_available, file_digest
from server.services.format_review import FormatReviewService
from server.services.format_validation import FormatValidationService
from server.services.master_authority import master_authority_unit
from tests.integration.r2.advanced_creative.test_format_render import make_source
from tests.integration.server.services.test_format_render import render_service
from tests.integration.server.services.test_format_review import granted, wait_for_advisory_waiter
from tests.unit.r2.advanced_creative.test_formats import overlay, profile

type Factory = async_sessionmaker[AsyncSession]

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="needs ffmpeg and ffprobe")

USER = "default"
PROJECT = "demo"
SOURCE_KEY = "m8-test-source:episode-1"
ALL_PASS = dict.fromkeys(SEMANTIC_ITEMS, "PASS")


async def _seed_master(factory: Factory, root: Path, video: Path, tag: str) -> None:
    async with factory() as session:
        await master_authority_unit(session).promote_staged(
            user_id=USER,
            project_name=PROJECT,
            project_dir=root,
            artifact_key=SOURCE_KEY,
            generation_candidate_id=tag,
            version_file=video,
            expected_content_digest=file_digest(video),
            approval_record=f"APR-{tag}",
            command_id=f"seed-{tag}",
        )


async def _plan(factory: Factory, root: Path, source: Path, version: int, plan_id: str = "plan-1"):
    target = profile(1080, 1080, profile_ref="square@1")
    decision = reframe_decision(
        decision_id="r1",
        kind=ReframeKind.PAD,
        source_size=(1280, 720),
        profile=target,
        focal=None,
        subject=Box(Fraction(2, 5), Fraction(1, 4), Fraction(3, 5), Fraction(3, 4)),
        rationale="keep the whole frame",
    )
    plan = build_plan(
        plan_id=plan_id,
        source_master_id=source_master_id(SOURCE_KEY, version),
        source_master_digest=file_digest(source),
        profile=target,
        overlay=overlay(),
        decisions=(decision,),
    )
    async with factory() as session:
        repository = FormatRepository(session)
        await repository.put_profile(user_id=USER, project_name=PROJECT, profile=target)
        await repository.put_overlay(user_id=USER, project_name=PROJECT, overlay=overlay())
        await repository.create_plan(user_id=USER, project_name=PROJECT, plan=plan)
        await session.commit()
    return plan


async def _reviewed_render(factory: Factory, root: Path, source: Path, plan_id: str, command: str, grants=None):
    rendered = await render_service(factory).render(
        user_id=USER, project_name=PROJECT, project_dir=root, plan_id=plan_id, source=source, command_id=command
    )
    technical = await FormatValidationService(factory).validate(
        user_id=USER, project_name=PROJECT, project_dir=root, execution_id=rendered.execution_id, source=source
    )
    assert technical.passed
    reviews = FormatReviewService(factory, grants=grants or await granted(factory, "sponsor"))
    packet = await reviews.open_packet(
        user_id=USER,
        project_name=PROJECT,
        project_dir=root,
        execution_id=rendered.execution_id,
        source_ref=source.relative_to(root).as_posix(),
        reviewer_id="sponsor",
    )
    semantic = await reviews.submit(
        user_id=USER, project_name=PROJECT, packet_id=packet.packet_id, reviewer_id="sponsor", items=ALL_PASS, note="ok"
    )
    assert semantic.passed
    return rendered


async def _preview(factory: Factory, prepared, command: str):
    target = PromotionTarget(
        kind=PromotionTargetKind.ARTIFACT_SLOT,
        target_ref=prepared.slot_key,
        expected_target_version=prepared.expected_target_version,
    )
    async with factory() as session:
        preview = await composition.exploration_service(session).create_preview(
            user_id=USER,
            project_name=PROJECT,
            candidate_id=prepared.candidate_id,
            revision=prepared.revision,
            target=target,
            command_id=f"{command}-preview",
        )
    return PromotionAuthorization(
        command_id=f"{command}-promote",
        project_name=PROJECT,
        preview_id=preview.preview_id,
        preview_digest=digest_canonical(preview),
        actor_id=USER,
        actor_scope=USER,
        decision="APPROVE",
        authorized_at=datetime.now(UTC),
    )


async def _promote(factory: Factory, prepared, authorization: PromotionAuthorization):
    async with factory() as session:
        return await composition.exploration_promotion(session).promote(
            user_id=USER,
            project_name=PROJECT,
            authorization=authorization,
            expected_candidate_head_version=prepared.head_version,
        )


async def _preview_and_promote(factory: Factory, prepared, command: str):
    return await _promote(factory, prepared, await _preview(factory, prepared, command))


async def _prepare(factory: Factory, root: Path, execution_id: str):
    return await prepare_format_candidate(
        factory, user_id=USER, project_name=PROJECT, project_dir=root, execution_id=execution_id, author=USER
    )


async def _append_failing_technical(factory: Factory, plan_id: str, artifact_digest: str) -> None:
    async with factory() as session, session.begin():
        await _append_failing_technical_in(session, plan_id, artifact_digest)


async def _append_failing_technical_in(session: AsyncSession, plan_id: str, artifact_digest: str) -> None:
    """A later technical report of the same render that fails (a decode error found on re-check)."""
    repository = FormatRepository(session)
    reports = await repository.passing_reports(
        user_id=USER, project_name=PROJECT, plan_id=plan_id, artifact_digest=artifact_digest
    )
    assert reports is not None
    technical = reports[0]
    checks = [
        {**row.model_dump(mode="python"), "observed": 1, "verdict": "FAIL"}
        if row.model_dump(mode="python")["name"] == "decode"
        else row.model_dump(mode="python")
        for row in technical.checks
    ]
    await repository.append_technical_report(
        user_id=USER,
        project_name=PROJECT,
        plan_id=plan_id,
        report=technical.model_copy(
            update={
                "report_id": technical.report_id + "-recheck",
                "checks": tuple(CanonicalJsonObject.model_validate(check) for check in checks),
                "passed": False,
            }
        ),
    )


async def test_a_reviewed_projection_becomes_the_first_master_of_its_format_slot(
    session_factory: Factory, tmp_path: Path
) -> None:
    source = make_source(tmp_path / "masters" / "episode.mp4")
    await _seed_master(session_factory, tmp_path, source, "a")
    plan = await _plan(session_factory, tmp_path, source, version=1)
    rendered = await _reviewed_render(session_factory, tmp_path, source, plan.plan_id, "r-1")

    prepared = await _prepare(session_factory, tmp_path, rendered.execution_id)
    assert prepared.slot_key == format_slot_key(SOURCE_KEY, "square@1")
    assert prepared.expected_target_version == 0
    receipt = await _preview_and_promote(session_factory, prepared, "first")

    assert receipt.result_artifact_ref == prepared.slot_key
    assert receipt.result_digest == rendered.artifact_digest
    async with session_factory() as session:
        head = await MasterAuthorityRepository(session).get_current(
            user_id=USER, project_name=PROJECT, artifact_key=prepared.slot_key
        )
    assert head is not None
    assert (head.master_version, head.content_digest) == (1, rendered.artifact_digest)


async def test_a_moved_source_master_blocks_the_projection(session_factory: Factory, tmp_path: Path) -> None:
    source = make_source(tmp_path / "masters" / "episode.mp4")
    await _seed_master(session_factory, tmp_path, source, "a")
    plan = await _plan(session_factory, tmp_path, source, version=1)
    rendered = await _reviewed_render(session_factory, tmp_path, source, plan.plan_id, "r-1")
    prepared = await _prepare(session_factory, tmp_path, rendered.execution_id)

    newer = make_source(tmp_path / "masters" / "episode-v2.mp4", seconds=1)
    await _seed_master(session_factory, tmp_path, newer, "b")
    with pytest.raises(PromotionBindingStaleError, match="source master moved"):
        await _preview_and_promote(session_factory, prepared, "stale")
    with pytest.raises(PromotionBindingStaleError, match="source master moved"):
        await _prepare(session_factory, tmp_path, rendered.execution_id)


async def test_without_passing_reports_there_is_no_candidate(session_factory: Factory, tmp_path: Path) -> None:
    source = make_source(tmp_path / "masters" / "episode.mp4")
    await _seed_master(session_factory, tmp_path, source, "a")
    plan = await _plan(session_factory, tmp_path, source, version=1)
    rendered = await render_service(session_factory).render(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan.plan_id, source=source, command_id="r-1"
    )
    await FormatValidationService(session_factory).validate(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, execution_id=rendered.execution_id, source=source
    )

    with pytest.raises(PromotionBindingStaleError, match="both pass"):
        await _prepare(session_factory, tmp_path, rendered.execution_id)


async def test_a_report_appended_after_the_preview_supersedes_the_evidence(
    session_factory: Factory, tmp_path: Path
) -> None:
    source = make_source(tmp_path / "masters" / "episode.mp4")
    await _seed_master(session_factory, tmp_path, source, "a")
    plan = await _plan(session_factory, tmp_path, source, version=1)
    rendered = await _reviewed_render(session_factory, tmp_path, source, plan.plan_id, "r-1")
    prepared = await _prepare(session_factory, tmp_path, rendered.execution_id)
    authorization = await _preview(session_factory, prepared, "late")

    await _append_failing_technical(session_factory, plan.plan_id, rendered.artifact_digest)
    with pytest.raises(PromotionBindingStaleError, match="both pass"):
        await _promote(session_factory, prepared, authorization)


async def test_a_promotion_waits_for_a_concurrent_report_writer_and_sees_its_report(
    concurrent_session_factory: Factory, tmp_path: Path
) -> None:
    factory = concurrent_session_factory
    async with factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL transaction advisory locks")
    source = make_source(tmp_path / "masters" / "episode.mp4")
    await _seed_master(factory, tmp_path, source, "a")
    plan = await _plan(factory, tmp_path, source, version=1)
    rendered = await _reviewed_render(factory, tmp_path, source, plan.plan_id, "r-1")
    prepared = await _prepare(factory, tmp_path, rendered.execution_id)
    authorization = await _preview(factory, prepared, "race")

    # A report writer holds the plan's report lock; the promotion must wait for it, then refuse.
    async with factory() as holder, holder.begin():
        await FormatRepository(holder).lock_plan_reports(user_id=USER, project_name=PROJECT, plan_id=plan.plan_id)
        promotion = asyncio.create_task(_promote(factory, prepared, authorization))
        await wait_for_advisory_waiter(factory)
        await _append_failing_technical_in(holder, plan.plan_id, rendered.artifact_digest)
    with pytest.raises(PromotionBindingStaleError, match="both pass"):
        await promotion


async def test_two_projections_racing_for_a_new_format_slot_promote_exactly_one(
    concurrent_session_factory: Factory, tmp_path: Path
) -> None:
    factory = concurrent_session_factory
    source = make_source(tmp_path / "masters" / "episode.mp4")
    await _seed_master(factory, tmp_path, source, "a")
    grants = await granted(factory, "sponsor")
    prepared = []
    for plan_id in ("plan-1", "plan-2"):
        plan = await _plan(factory, tmp_path, source, version=1, plan_id=plan_id)
        rendered = await _reviewed_render(factory, tmp_path, source, plan.plan_id, f"r-{plan_id}", grants)
        prepared.append(await _prepare(factory, tmp_path, rendered.execution_id))
    assert {item.slot_key for item in prepared} == {format_slot_key(SOURCE_KEY, "square@1")}
    assert {item.expected_target_version for item in prepared} == {0}
    authorizations = [await _preview(factory, item, f"genesis-{index}") for index, item in enumerate(prepared)]

    if (await _dialect(factory)) == "postgresql":
        outcomes = await asyncio.gather(
            *(_promote(factory, item, auth) for item, auth in zip(prepared, authorizations, strict=True)),
            return_exceptions=True,
        )
    else:
        # SQLite has one writer; the two promotions run one after the other.
        outcomes = []
        for item, auth in zip(prepared, authorizations, strict=True):
            try:
                outcomes.append(await _promote(factory, item, auth))
            except PromotionBindingStaleError as error:
                outcomes.append(error)
    receipts = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
    refusals = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
    assert len(receipts) == 1
    assert len(refusals) == 1
    assert isinstance(refusals[0], PromotionBindingStaleError)
    async with factory() as session:
        head = await MasterAuthorityRepository(session).get_current(
            user_id=USER, project_name=PROJECT, artifact_key=prepared[0].slot_key
        )
    assert head is not None
    assert (head.master_version, head.content_digest) == (1, receipts[0].result_digest)


async def _dialect(factory: Factory) -> str:
    async with factory() as probe:
        return probe.get_bind().dialect.name
