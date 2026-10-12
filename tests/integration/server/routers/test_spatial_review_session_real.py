"""A review session pins two current PNG streams behind a signed scoped grant."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import AsyncClient
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.content_digest import canonical_json_bytes
from lib.db.models.spatial_pair import (
    SpatialPairCommandModel,
    SpatialPairDecisionModel,
    SpatialPairHeadModel,
    SpatialPairV2CustodyModel,
)
from lib.db.models.spatial_review import (
    SpatialReviewAcknowledgmentModel,
    SpatialReviewDeliveryModel,
    SpatialReviewSessionModel,
)
from lib.db.repositories.spatial_pair import SpatialPairIntegrityError
from lib.db.repositories.spatial_pair_v2 import SpatialPairVersionedRepository
from lib.db.repositories.spatial_review import SpatialReviewIntegrityError, SpatialReviewRepository
from lib.db.repositories.spatial_source import _receipt_digest
from r2.contracts.production_binding_authority import BindingCreateCommandV1
from r2.contracts.spatial_pair import PairDecisionCommandV2, PairDecisionResultV2, PairDecisionV2
from r2.governance.grant_transition import GrantScopeV1
from r2.host_hardening.master_authority import MasterAuthorityUnit
from r2.m3.host_integration import GoldenAHostIntegration
from r2.production_intelligence.take_director import TakeDirectorAdapter
from r2.spatial_pair.digests import (
    pair_authorization_digest,
    pair_command_digest_v2,
    pair_decision_digest_v2,
    pair_result_digest_v2,
    scoped_pair_id,
)
from r2.spatial_pair.review_digests import review_evidence_digest, review_snapshot_digest
from r2.target_registry.service import TakeTargetRegistrationService
from server.auth import CurrentUserInfo
from server.services.governance_grants import (
    CheckpointedShowrunnerGrantReader,
    CurrentShowrunnerGrantReader,
    GovernanceGrantImporter,
    ShowrunnerGrantUnavailableError,
)
from server.services.location_binding import LocationBindingCreationService
from server.services.spatial_pair_current_v2 import CurrentApprovedSpatialPairReaderV2, SpatialPairV2UnavailableError
from server.services.spatial_pair_decision import PairAuthorizationDeniedError
from server.services.spatial_pair_decision_v2 import SpatialPairDecisionServiceV2
from server.services.spatial_review_session import SpatialReviewSessionService
from server.services.spatial_source import FrameDerivationService, FrameSourceConflictError
from tests.integration.r2.adaptation import test_screenplay_admission as admission_helpers
from tests.integration.r2.governance.test_grant_recovery_snapshot import _checkpoint
from tests.integration.r2.target_registry import test_take_registration as target_helpers
from tests.integration.server.routers.test_gates_export import PROJECT, USER, _approve_shot
from tests.integration.server.routers.test_spatial_frame_reader import _start_blocked_master_writer

PAIR_V2_VECTOR = json.loads(
    (Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_pair_v2_decision_vector.json").read_text()
)


async def _run_blocked_v2_command(
    *,
    service: SpatialPairDecisionServiceV2,
    command: PairDecisionCommandV2,
    interactive: CurrentUserInfo,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    first_fails: bool,
) -> PairDecisionResultV2:
    original_claim = SpatialPairVersionedRepository.claim_pair_head
    original_receipt = SpatialPairVersionedRepository.get_command_receipt_v2
    first_claimed = asyncio.Event()
    release_first = asyncio.Event()
    first_pid: list[int] = []
    second_pid: list[int] = []
    second: asyncio.Task[PairDecisionResultV2] | None = None

    async def capture_second_receipt(self, **kwargs):
        if asyncio.current_task() is second and not second_pid:
            pid = await self.session.scalar(select(func.pg_backend_pid()))
            assert isinstance(pid, int)
            second_pid.append(pid)
        return await original_receipt(self, **kwargs)

    async def pause_pair_claim(self, *, user_id: str, project_name: str, pair_id: str):
        pid = await self.session.scalar(select(func.pg_backend_pid()))
        assert isinstance(pid, int)
        if not first_claimed.is_set():
            locked = await original_claim(self, user_id=user_id, project_name=project_name, pair_id=pair_id)
            first_pid.append(pid)
            first_claimed.set()
            await release_first.wait()
            if first_fails:
                raise RuntimeError("forced first V2 writer rollback")
            return locked
        return await original_claim(self, user_id=user_id, project_name=project_name, pair_id=pair_id)

    monkeypatch.setattr(SpatialPairVersionedRepository, "claim_pair_head", pause_pair_claim)
    monkeypatch.setattr(SpatialPairVersionedRepository, "get_command_receipt_v2", capture_second_receipt)
    first = asyncio.create_task(service.decide(command, authenticated_user=interactive))
    try:
        await asyncio.wait_for(first_claimed.wait(), timeout=10)
        second = asyncio.create_task(service.decide(command, authenticated_user=interactive))
        blocked = False
        for _ in range(500):
            async with session_factory() as observer:
                blockers = await observer.scalar(select(func.pg_blocking_pids(second_pid[0]))) if second_pid else []
            if first_pid and first_pid[0] in blockers:
                blocked = True
                break
            if second.done():
                raise AssertionError("second V2 decision did not wait for the first transaction")
            await asyncio.sleep(0.01)
        assert blocked
    finally:
        release_first.set()
        monkeypatch.setattr(SpatialPairVersionedRepository, "claim_pair_head", original_claim)
        monkeypatch.setattr(SpatialPairVersionedRepository, "get_command_receipt_v2", original_receipt)
        await asyncio.wait_for(
            asyncio.gather(first, *([second] if second is not None else []), return_exceptions=True), 15
        )
    assert second is not None
    if first_fails:
        with pytest.raises(RuntimeError, match="forced first V2 writer rollback"):
            first.result()
    else:
        assert first.result() == second.result()
    return second.result()


@pytest.mark.asyncio
@pytest.mark.parametrize("race_order", ["pair_first", "writer_first"])
async def test_review_session_requires_current_grant_and_pins_verified_png_bytes(
    gate_export_client: AsyncClient,
    project_dir: Path,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    race_order: str,
) -> None:
    if race_order == "writer_first" and session_factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("forced Gate C writer-first schedule requires PostgreSQL row locks")
    monkeypatch.setattr(admission_helpers, "USER", USER.id)
    monkeypatch.setattr(admission_helpers, "PROJECT", PROJECT)
    admission, *_ = await target_helpers._admit(session_factory)
    original_direct = TakeDirectorAdapter.direct

    async def direct_with_location(self, ref):
        result = await original_direct(self, ref)
        return replace(
            result,
            scenes=tuple(scene.model_copy(update={"location_ref": "location:room-1"}) for scene in result.scenes),
        )

    monkeypatch.setattr(TakeDirectorAdapter, "direct", direct_with_location)
    registered = await TakeTargetRegistrationService(session_factory).register(
        target_helpers._command(admission, user_id=USER.id, project_name=PROJECT)
    )
    receipts = []
    for shot, tag in (("SH01", b"review-parent-a"), ("SH02", b"review-parent-b")):
        await _approve_shot(gate_export_client, project_dir, shot, tag)
        key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for(shot)
        receipts.append(
            await FrameDerivationService(session_factory=session_factory, project_dir=project_dir).derive(
                user_id=USER.id,
                project_name=PROJECT,
                parent_artifact_key=key,
                expected_master_version=1,
                decoded_frame_index=0,
                command_id=f"review-frame-{shot}",
            )
        )
    receipts.sort(key=lambda receipt: receipt.frame_candidate_id)
    await LocationBindingCreationService(session_factory=session_factory, project_dir=project_dir).create(
        BindingCreateCommandV1.model_validate(
            {
                "user_id": USER.id,
                "project_name": PROJECT,
                "principal": USER.sub,
                "command_id": "review-binding-1",
                "expected_target_ref": registered.shot_targets[0].model_dump(mode="json"),
                "ordered_frame_receipts": [
                    {"receipt_id": receipt.frame_candidate_id, "receipt_digest": _receipt_digest(receipt)}
                    for receipt in receipts
                ],
            }
        )
    )

    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    reader = CurrentShowrunnerGrantReader(key_id="test-review-key", public_key=public)
    service = SpatialReviewSessionService(session_factory=session_factory, project_dir=project_dir, grants=reader)
    arguments = {
        "user_id": USER.id,
        "project_name": PROJECT,
        "principal": USER.sub,
        "target_id": registered.shot_targets[0].target_id,
    }
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await service.create(**arguments)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(SpatialReviewSessionModel)) == 0

    scope = GrantScopeV1(USER.id, PROJECT, USER.sub)
    issued_at = (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "schema": "governance.showrunner_grant_event.v1",
        "event_type": "ISSUE",
        "user_id": USER.id,
        "project_name": PROJECT,
        "principal": USER.sub,
        "role": "HUMAN_SHOWRUNNER",
        "sequence": 1,
        "previous_event_digest": None,
        "issued_at": issued_at,
        "not_before": issued_at,
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "signer_key_id": "test-review-key",
    }
    signature = base64.urlsafe_b64encode(private.sign(canonical_json_bytes(body, allow_nan=False))).decode().rstrip("=")
    raw = canonical_json_bytes({"body": body, "signature": signature}, allow_nan=False)
    issue = await GovernanceGrantImporter(session_factory, key_id="test-review-key", public_key=public).import_event(
        raw, scope=scope
    )
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await service.create(**(arguments | {"principal": "other-reviewer"}))
    snapshot = await service.create(**arguments)
    second_snapshot = await service.create(**arguments)
    assert snapshot.session_id != second_snapshot.session_id
    assert [frame.role for frame in snapshot.frames] == ["MASTER", "REVERSE"]
    assert [frame.receipt_id for frame in snapshot.frames] == [receipt.frame_candidate_id for receipt in receipts]
    fetch_scope = {
        "user_id": USER.id,
        "project_name": PROJECT,
        "principal": USER.sub,
        "session_id": snapshot.session_id,
    }
    with pytest.raises(SpatialReviewIntegrityError):
        await service.fetch_frame(**(fetch_scope | {"principal": "other-reviewer"}), role="MASTER")
    deliveries = []
    for frame in snapshot.frames:
        frame_path = project_dir / "spatial" / "frames" / f"{frame.receipt_id}.png"
        assert frame.png_digest == "sha256:" + hashlib.sha256(frame_path.read_bytes()).hexdigest()
        served, delivery = await service.fetch_frame(**fetch_scope, role=frame.role)
        assert served == frame_path.read_bytes()
        assert delivery.role == frame.role
        assert delivery.png_digest == frame.png_digest
        deliveries.append(delivery)
    with pytest.raises(SpatialReviewIntegrityError):
        await service.acknowledge_frame(
            **fetch_scope,
            attempt_id=deliveries[0].attempt_id,
            role="REVERSE",
            png_digest=snapshot.frames[0].png_digest,
            decoded=True,
        )
    with pytest.raises(SpatialReviewIntegrityError):
        await service.acknowledge_frame(
            **fetch_scope,
            attempt_id=deliveries[0].attempt_id,
            role="MASTER",
            png_digest=snapshot.frames[0].png_digest,
            decoded=False,
        )
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await service.acknowledge_frame(
            **(fetch_scope | {"principal": "other-reviewer"}),
            attempt_id=deliveries[0].attempt_id,
            role="MASTER",
            png_digest=snapshot.frames[0].png_digest,
            decoded=True,
        )
    for frame, delivery in zip(snapshot.frames, deliveries, strict=True):
        acknowledgment = await service.acknowledge_frame(
            **fetch_scope,
            attempt_id=delivery.attempt_id,
            role=frame.role,
            png_digest=frame.png_digest,
            decoded=True,
        )
        assert acknowledgment.delivery_attempt_id == delivery.attempt_id
        assert acknowledgment.principal == USER.sub
    async with session_factory() as session, session.begin():
        evidence, digest = await SpatialReviewRepository(session).read_complete(**fetch_scope)
        assert evidence.snapshot == snapshot
        assert digest.startswith("sha256:")
        command = PairDecisionCommandV2.model_validate(
            PAIR_V2_VECTOR["body"]["command"]
            | {
                "user_id": USER.id,
                "project_name": PROJECT,
                "principal": USER.sub,
                "expected_scene_ref": snapshot.scene_ref.model_dump(mode="json"),
                "expected_target_ref": snapshot.target_ref.model_dump(mode="json"),
                "binding_id": snapshot.binding_id,
                "expected_binding_version": snapshot.binding_version,
                "expected_envelope_digest": snapshot.envelope_digest,
                "expected_core_digest": snapshot.core_digest,
                "views": [
                    {"role": frame.role, "receipt_id": frame.receipt_id, "receipt_digest": frame.receipt_digest}
                    for frame in snapshot.frames
                ],
                "review_session_id": snapshot.session_id,
                "review_evidence_digest": review_evidence_digest(evidence.model_dump(mode="json")),
            }
        )
        command_digest = pair_command_digest_v2(command.model_dump(mode="json"))
        now = datetime.now(UTC)
        authorization = {
            "user_id": USER.id,
            "project_name": PROJECT,
            "authenticated_principal": USER.sub,
            "authority_role": "HUMAN_SHOWRUNNER",
            "command_digest": command_digest,
            "authorization_ref": issue.event_digest,
            "authenticated_at": now.isoformat(),
        }
        decision = PairDecisionV2.model_validate(
            {
                "decision_schema": "r2.m8.spatial.pair.decision.v2",
                "command": command.model_dump(mode="json"),
                "command_digest": command_digest,
                "pair_id": scoped_pair_id(user_id=USER.id, project_name=PROJECT, binding_id=snapshot.binding_id),
                "pair_version": 1,
                "reviewer_id": USER.sub,
                "authorization": authorization,
                "authorization_digest": pair_authorization_digest(authorization),
                "review_evidence": evidence.model_dump(mode="json"),
                "decided_at": now.isoformat(),
            }
        )
        decision_digest = pair_decision_digest_v2(decision.model_dump(mode="json"))
        pair_repo = SpatialPairVersionedRepository(session)
        locked = await pair_repo.claim_pair_head(user_id=USER.id, project_name=PROJECT, pair_id=decision.pair_id)
        await session.execute(
            insert(SpatialPairCommandModel).values(
                user_id=USER.id,
                project_name=PROJECT,
                principal=USER.sub,
                command_id=command.command_id,
                command_digest=command_digest,
                result_json={"invalid": True},
                result_digest="sha256:" + "0" * 64,
                created_at=now,
            )
        )

        async def append_with_colliding_receipt() -> None:
            async with session.begin_nested():
                await pair_repo.append_reviewed_decision(locked=locked, decision=decision)

        with pytest.raises(IntegrityError):
            await append_with_colliding_receipt()
        still_open = await session.get(
            SpatialReviewSessionModel,
            (USER.id, PROJECT, snapshot.session_id),
            populate_existing=True,
        )
        assert still_open is not None
        assert still_open.consumed_command_digest is None
        assert await session.scalar(select(func.count()).select_from(SpatialPairDecisionModel)) == 0
        await session.execute(
            delete(SpatialPairCommandModel).where(
                SpatialPairCommandModel.user_id == USER.id,
                SpatialPairCommandModel.project_name == PROJECT,
                SpatialPairCommandModel.principal == USER.sub,
                SpatialPairCommandModel.command_id == command.command_id,
            )
        )
        result = await pair_repo.append_reviewed_decision(locked=locked, decision=decision)
        assert result.decision_digest == decision_digest
        receipt_row = await session.get(SpatialPairCommandModel, (USER.id, PROJECT, USER.sub, command.command_id))
        assert receipt_row is not None
        assert receipt_row.result_json == result.model_dump(mode="json")
        assert receipt_row.result_digest == pair_result_digest_v2(result.model_dump(mode="json"))
        hint = await pair_repo.get_command_receipt_v2(
            user_id=USER.id,
            project_name=PROJECT,
            principal=USER.sub,
            command_id=command.command_id,
            expected_command_digest=command_digest,
        )
        assert hint is not None
        assert hint.result == result
        replay = await pair_repo.verify_historical_receipt(hint=hint, command=command)
        assert replay.decision_digest == decision_digest
        receipt_row.result_digest = "sha256:" + "0" * 64
        await session.flush()
        with pytest.raises(SpatialPairIntegrityError):
            await pair_repo.get_command_receipt_v2(
                user_id=USER.id,
                project_name=PROJECT,
                principal=USER.sub,
                command_id=command.command_id,
                expected_command_digest=command_digest,
            )
        receipt_row.result_digest = pair_result_digest_v2(result.model_dump(mode="json"))
        await session.flush()
        session_row = await session.get(SpatialReviewSessionModel, (USER.id, PROJECT, snapshot.session_id))
        assert session_row is not None
        assert session_row.consumed_command_digest == command_digest
        reused = PairDecisionV2.model_validate(decision.model_dump(mode="json") | {"pair_version": 2})
        reused_head = await pair_repo.claim_pair_head(user_id=USER.id, project_name=PROJECT, pair_id=decision.pair_id)
        with pytest.raises(SpatialReviewIntegrityError):
            await pair_repo.append_reviewed_decision(locked=reused_head, decision=reused)
        assert await session.scalar(select(func.count()).select_from(SpatialPairDecisionModel)) == 1
        verified_pair = await SpatialPairVersionedRepository(session).get_current_verified(
            user_id=USER.id,
            project_name=PROJECT,
            binding_id=command.binding_id,
            expected_binding_version=command.expected_binding_version,
            expected_envelope_digest=command.expected_envelope_digest,
            expected_core_digest=command.expected_core_digest,
            expected_target_ref=command.expected_target_ref,
            expected_scene_ref=command.expected_scene_ref,
        )
        assert verified_pair is not None
        assert verified_pair.decision_digest == decision_digest
        if session.get_bind().dialect.name == "postgresql":

            async def link_foreign_session() -> None:
                async with session.begin_nested():
                    session.add(
                        SpatialReviewSessionModel(
                            user_id=USER.id,
                            project_name="foreign-project",
                            session_id="b" * 32,
                            principal=USER.sub,
                            snapshot_body_json=snapshot.model_dump(mode="json"),
                            snapshot_digest=review_snapshot_digest(snapshot.model_dump(mode="json")),
                            created_at=snapshot.created_at,
                            expires_at=snapshot.expires_at,
                            consumed_command_digest=None,
                        )
                    )
                    await session.flush()
                    custody = await session.get(
                        SpatialPairV2CustodyModel, (USER.id, PROJECT, decision.pair_id, 1), with_for_update=True
                    )
                    assert custody is not None
                    custody.review_session_id = "b" * 32
                    await session.flush()

            with pytest.raises(IntegrityError):
                await link_foreign_session()
    current_v2 = CurrentApprovedSpatialPairReaderV2(
        session_factory=session_factory, project_dir=project_dir, grants=reader
    )
    approved = await current_v2.read_current(
        user_id=USER.id, project_name=PROJECT, target_id=snapshot.target_ref.target_id
    )
    assert approved.body == decision
    assert approved.decision_digest == decision_digest

    async def load_stale_checkpoint() -> bytes:
        return _checkpoint([], signer=private)

    checkpointed = CheckpointedShowrunnerGrantReader(
        grant_key_id="test-review-key",
        grant_public_key=public,
        deployment_id="deploy-a",
        checkpoint_key_id="checkpoint-test-key",
        checkpoint_public_key=public,
        load_checkpoint=load_stale_checkpoint,
    )
    guarded_review = SpatialReviewSessionService(
        session_factory=session_factory, project_dir=project_dir, grants=checkpointed
    )
    guarded_current = CurrentApprovedSpatialPairReaderV2(
        session_factory=session_factory, project_dir=project_dir, grants=checkpointed
    )
    guarded_decision = SpatialPairDecisionServiceV2(
        session_factory=session_factory, project_dir=project_dir, grants=checkpointed
    )
    async with session_factory() as session:
        sessions_before = await session.scalar(select(func.count()).select_from(SpatialReviewSessionModel))
        deliveries_before = await session.scalar(select(func.count()).select_from(SpatialReviewDeliveryModel))
        acknowledgments_before = await session.scalar(
            select(func.count()).select_from(SpatialReviewAcknowledgmentModel)
        )
        decisions_before = await session.scalar(select(func.count()).select_from(SpatialPairDecisionModel))
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await guarded_review.create(**arguments)
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await guarded_review.fetch_frame(**fetch_scope, role="MASTER")
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await guarded_review.acknowledge_frame(
            **fetch_scope,
            attempt_id=deliveries[0].attempt_id,
            role="MASTER",
            png_digest=snapshot.frames[0].png_digest,
            decoded=True,
        )
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await guarded_current.read_current(
            user_id=USER.id, project_name=PROJECT, target_id=snapshot.target_ref.target_id
        )
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await guarded_decision.decide(
            command, authenticated_user=CurrentUserInfo(id=USER.id, sub=USER.sub, role="user")
        )
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(SpatialReviewSessionModel)) == sessions_before
        assert await session.scalar(select(func.count()).select_from(SpatialReviewDeliveryModel)) == deliveries_before
        assert (
            await session.scalar(select(func.count()).select_from(SpatialReviewAcknowledgmentModel))
            == acknowledgments_before
        )
        assert await session.scalar(select(func.count()).select_from(SpatialPairDecisionModel)) == decisions_before
    second_scope = fetch_scope | {"session_id": second_snapshot.session_id}
    if session_factory.kw["bind"].dialect.name == "postgresql":
        original_review_check = SpatialPairVersionedRepository.verify_review_consumption
        original_snapshot_hint = SpatialReviewRepository.read_snapshot_hint
        reader_holds_sources = asyncio.Event()
        release_reader = asyncio.Event()
        reader_pid: list[int] = []
        fetch_pid: list[int] = []
        reader_task = None
        fetch_task = None

        async def pause_before_review_check(self, verified):
            if asyncio.current_task() is reader_task:
                pid = await self.session.scalar(select(func.pg_backend_pid()))
                assert isinstance(pid, int)
                reader_pid.append(pid)
                reader_holds_sources.set()
                await release_reader.wait()
            return await original_review_check(self, verified)

        async def capture_fetch_snapshot_hint(self, **kwargs):
            if asyncio.current_task() is fetch_task:
                pid = await self.session.scalar(select(func.pg_backend_pid()))
                assert isinstance(pid, int)
                fetch_pid.append(pid)
            return await original_snapshot_hint(self, **kwargs)

        with monkeypatch.context() as read_patch:
            read_patch.setattr(SpatialPairVersionedRepository, "verify_review_consumption", pause_before_review_check)
            read_patch.setattr(SpatialReviewRepository, "read_snapshot_hint", capture_fetch_snapshot_hint)
            reader_task = asyncio.create_task(
                current_v2.read_current(user_id=USER.id, project_name=PROJECT, target_id=snapshot.target_ref.target_id)
            )
            blocked = False
            try:
                await asyncio.wait_for(reader_holds_sources.wait(), timeout=10)
                fetch_task = asyncio.create_task(service.fetch_frame(**second_scope, role="MASTER"))
                for _ in range(500):
                    async with session_factory() as observer:
                        blockers = (
                            await observer.scalar(select(func.pg_blocking_pids(fetch_pid[0]))) if fetch_pid else []
                        )
                    if reader_pid and reader_pid[0] in blockers:
                        blocked = True
                        break
                    if fetch_task.done():
                        break
                    await asyncio.sleep(0.01)
            finally:
                release_reader.set()
            assert (await asyncio.wait_for(reader_task, timeout=10)).decision_digest == decision_digest
            assert fetch_task is not None
            fetched_bytes, fetched_delivery = await asyncio.wait_for(fetch_task, timeout=10)
            assert fetched_bytes.startswith(b"\x89PNG\r\n\x1a\n")
            assert fetched_delivery.role == "MASTER"
            assert blocked, "frame fetch must wait on the current V2 reader's authority transaction"
    with pytest.raises(SpatialPairV2UnavailableError):
        await current_v2.read_current(
            user_id=USER.id, project_name="foreign-project", target_id=snapshot.target_ref.target_id
        )
    approved_frame_path = project_dir / "spatial" / "frames" / f"{snapshot.frames[0].receipt_id}.png"
    approved_png = approved_frame_path.read_bytes()
    approved_frame_path.write_bytes(approved_png + b"changed")
    try:
        with pytest.raises(FrameSourceConflictError):
            await current_v2.read_current(
                user_id=USER.id, project_name=PROJECT, target_id=snapshot.target_ref.target_id
            )
    finally:
        approved_frame_path.write_bytes(approved_png)
    for frame in second_snapshot.frames:
        _, delivered = await service.fetch_frame(**second_scope, role=frame.role)
        await service.acknowledge_frame(
            **second_scope,
            attempt_id=delivered.attempt_id,
            role=frame.role,
            png_digest=frame.png_digest,
            decoded=True,
        )
    async with session_factory() as session, session.begin():
        _, second_digest = await SpatialReviewRepository(session).read_complete(**second_scope)
    reject_command = PairDecisionCommandV2.model_validate(
        command.model_dump(mode="json")
        | {
            "command_id": "pair-review-reject-2",
            "review_session_id": second_snapshot.session_id,
            "review_evidence_digest": second_digest,
            "decision": "REJECT",
            "observations": {
                "view_coverage": None,
                "camera_center": None,
                "yaw_relation": None,
                "rejection_reason": "Reverse frame does not match the requested camera axis.",
            },
        }
    )
    pair_service = SpatialPairDecisionServiceV2(session_factory=session_factory, project_dir=project_dir, grants=reader)
    interactive = CurrentUserInfo(id=USER.id, sub=USER.sub, role="user")
    with pytest.raises(PairAuthorizationDeniedError):
        await pair_service.decide(reject_command, authenticated_user=CurrentUserInfo(id=USER.id, sub=USER.sub))
    if session_factory.kw["bind"].dialect.name == "postgresql":
        rejected = await _run_blocked_v2_command(
            service=pair_service,
            command=reject_command,
            interactive=interactive,
            session_factory=session_factory,
            monkeypatch=monkeypatch,
            first_fails=False,
        )
    else:
        rejected = await pair_service.decide(reject_command, authenticated_user=interactive)
    assert rejected.pair_version == 2
    assert rejected.decision == "REJECT"
    with pytest.raises(SpatialPairV2UnavailableError):
        await current_v2.read_current(user_id=USER.id, project_name=PROJECT, target_id=snapshot.target_ref.target_id)
    assert await pair_service.decide(reject_command, authenticated_user=interactive) == rejected
    async with session_factory() as session, session.begin():
        pair_head = await session.get(SpatialPairHeadModel, (USER.id, PROJECT, rejected.pair_id))
        assert pair_head is not None
        pair_head.current_decision_digest = "sha256:" + "0" * 64
    with pytest.raises(SpatialPairIntegrityError):
        await pair_service.decide(reject_command, authenticated_user=interactive)
    async with session_factory() as session, session.begin():
        pair_head = await session.get(SpatialPairHeadModel, (USER.id, PROJECT, rejected.pair_id))
        assert pair_head is not None
        pair_head.current_decision_digest = rejected.decision_digest
    third_snapshot = await service.create(**arguments)
    third_scope = fetch_scope | {"session_id": third_snapshot.session_id}
    for frame in third_snapshot.frames:
        _, delivered = await service.fetch_frame(**third_scope, role=frame.role)
        await service.acknowledge_frame(
            **third_scope,
            attempt_id=delivered.attempt_id,
            role=frame.role,
            png_digest=frame.png_digest,
            decoded=True,
        )
    async with session_factory() as session, session.begin():
        _, third_digest = await SpatialReviewRepository(session).read_complete(**third_scope)
    third_command = PairDecisionCommandV2.model_validate(
        reject_command.model_dump(mode="json")
        | {
            "command_id": "pair-review-reject-3",
            "review_session_id": third_snapshot.session_id,
            "review_evidence_digest": third_digest,
        }
    )
    if session_factory.kw["bind"].dialect.name == "postgresql":
        recovered = await _run_blocked_v2_command(
            service=pair_service,
            command=third_command,
            interactive=interactive,
            session_factory=session_factory,
            monkeypatch=monkeypatch,
            first_fails=True,
        )
    else:
        recovered = await pair_service.decide(third_command, authenticated_user=interactive)
    assert recovered.pair_version == 3
    assert await pair_service.decide(reject_command, authenticated_user=interactive) == rejected
    frame_path = project_dir / "spatial" / "frames" / f"{snapshot.frames[0].receipt_id}.png"
    original = frame_path.read_bytes()
    frame_path.write_bytes(original + b"changed")
    try:
        with pytest.raises(FrameSourceConflictError):
            await service.create(**arguments)
        with pytest.raises(FrameSourceConflictError):
            await service.fetch_frame(**fetch_scope, role="MASTER")
        with pytest.raises(FrameSourceConflictError):
            await pair_service.decide(reject_command, authenticated_user=interactive)
    finally:
        frame_path.write_bytes(original)
    async with session_factory() as session:
        row = await session.get(SpatialReviewSessionModel, (USER.id, PROJECT, snapshot.session_id))
        assert row is not None
        assert row.snapshot_digest == review_snapshot_digest(snapshot.model_dump(mode="json"))
        assert await session.scalar(select(func.count()).select_from(SpatialReviewSessionModel)) == 3
        assert await session.scalar(select(func.count()).select_from(SpatialReviewDeliveryModel)) == (
            7 if session.get_bind().dialect.name == "postgresql" else 6
        )
        assert await session.scalar(select(func.count()).select_from(SpatialReviewAcknowledgmentModel)) == 6

    revoke_body = {key: value for key, value in body.items() if key not in {"not_before", "expires_at"}} | {
        "event_type": "REVOKE",
        "sequence": 2,
        "previous_event_digest": issue.event_digest,
        "issued_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    revoke_signature = (
        base64.urlsafe_b64encode(private.sign(canonical_json_bytes(revoke_body, allow_nan=False))).decode().rstrip("=")
    )
    revoke_raw = canonical_json_bytes({"body": revoke_body, "signature": revoke_signature}, allow_nan=False)
    if session_factory.kw["bind"].dialect.name == "postgresql":
        original_grant_read = CurrentShowrunnerGrantReader.require_current_locked
        revoke_locked = asyncio.Event()
        release_revoke = asyncio.Event()
        revoke_pid: list[int] = []
        decision_pid: list[int] = []

        async def hold_revoke_head(session: AsyncSession) -> None:
            pid = await session.scalar(select(func.pg_backend_pid()))
            assert isinstance(pid, int)
            revoke_pid.append(pid)
            revoke_locked.set()
            await release_revoke.wait()

        async def capture_decision_grant_read(self, session: AsyncSession, *, scope: GrantScopeV1):
            pid = await session.scalar(select(func.pg_backend_pid()))
            assert isinstance(pid, int)
            decision_pid.append(pid)
            return await original_grant_read(self, session, scope=scope)

        importer = GovernanceGrantImporter(
            session_factory, key_id="test-review-key", public_key=public, on_head_locked=hold_revoke_head
        )
        revoke_task = asyncio.create_task(importer.import_event(revoke_raw, scope=scope))
        decision_task = None
        try:
            await asyncio.wait_for(revoke_locked.wait(), timeout=10)
            with monkeypatch.context() as grant_patch:
                grant_patch.setattr(CurrentShowrunnerGrantReader, "require_current_locked", capture_decision_grant_read)
                decision_task = asyncio.create_task(pair_service.decide(reject_command, authenticated_user=interactive))
                blocked = False
                for _ in range(500):
                    async with session_factory() as observer:
                        blockers = (
                            await observer.scalar(select(func.pg_blocking_pids(decision_pid[0])))
                            if decision_pid
                            else []
                        )
                    if revoke_pid and revoke_pid[0] in blockers:
                        blocked = True
                        break
                    if decision_task.done():
                        break
                    await asyncio.sleep(0.01)
                assert blocked, "V2 decision must wait for the signed-grant revoke transaction"
        finally:
            release_revoke.set()
            revoke = await asyncio.wait_for(revoke_task, timeout=10)
        assert decision_task is not None
        with pytest.raises(ShowrunnerGrantUnavailableError):
            await asyncio.wait_for(decision_task, timeout=10)
    else:
        revoke = await GovernanceGrantImporter(
            session_factory, key_id="test-review-key", public_key=public
        ).import_event(revoke_raw, scope=scope)
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await service.create(**arguments)
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await pair_service.decide(reject_command, authenticated_user=interactive)
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await service.fetch_frame(**fetch_scope, role="REVERSE")
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await service.acknowledge_frame(
            **fetch_scope,
            attempt_id=deliveries[0].attempt_id,
            role="MASTER",
            png_digest=snapshot.frames[0].png_digest,
            decoded=True,
        )
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(SpatialReviewSessionModel)) == 3
        assert await session.scalar(select(func.count()).select_from(SpatialReviewDeliveryModel)) == (
            7 if session.get_bind().dialect.name == "postgresql" else 6
        )
        assert await session.scalar(select(func.count()).select_from(SpatialReviewAcknowledgmentModel)) == 6

    if session_factory.kw["bind"].dialect.name == "postgresql":
        revoked_second = datetime.fromisoformat(revoke_body["issued_at"])
        await asyncio.sleep(max(0.0, ((revoked_second + timedelta(seconds=1)) - datetime.now(UTC)).total_seconds()))
        reissue_body = body | {
            "sequence": 3,
            "previous_event_digest": revoke.event_digest,
            "issued_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "not_before": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        reissue_signature = (
            base64.urlsafe_b64encode(private.sign(canonical_json_bytes(reissue_body, allow_nan=False)))
            .decode()
            .rstrip("=")
        )
        await GovernanceGrantImporter(session_factory, key_id="test-review-key", public_key=public).import_event(
            canonical_json_bytes({"body": reissue_body, "signature": reissue_signature}, allow_nan=False), scope=scope
        )
        if race_order == "writer_first":
            fourth_snapshot = await service.create(**arguments)
            fourth_scope = fetch_scope | {"session_id": fourth_snapshot.session_id}
            for frame in fourth_snapshot.frames:
                _, delivered = await service.fetch_frame(**fourth_scope, role=frame.role)
                await service.acknowledge_frame(
                    **fourth_scope,
                    attempt_id=delivered.attempt_id,
                    role=frame.role,
                    png_digest=frame.png_digest,
                    decoded=True,
                )
            async with session_factory() as session, session.begin():
                _, fourth_digest = await SpatialReviewRepository(session).read_complete(**fourth_scope)
            fourth_command = PairDecisionCommandV2.model_validate(
                third_command.model_dump(mode="json")
                | {
                    "command_id": "pair-review-writer-first-4",
                    "review_session_id": fourth_snapshot.session_id,
                    "review_evidence_digest": fourth_digest,
                }
            )
            original_promote = MasterAuthorityUnit.promote_staged
            original_receipt = SpatialPairVersionedRepository.get_command_receipt_v2
            writer_has_head = asyncio.Event()
            release_writer = asyncio.Event()
            writer_pid: list[int] = []
            writer_first_decision_pid: list[int] = []
            decision_task = None

            async def hold_promoted_master(self, **kwargs):
                result = await original_promote(self, **kwargs)
                pid = await self._authorities.session.scalar(select(func.pg_backend_pid()))
                assert isinstance(pid, int)
                writer_pid.append(pid)
                writer_has_head.set()
                await release_writer.wait()
                return result

            async def capture_writer_first_receipt(self, **kwargs):
                pid = await self.session.scalar(select(func.pg_backend_pid()))
                assert isinstance(pid, int)
                writer_first_decision_pid.append(pid)
                return await original_receipt(self, **kwargs)

            with monkeypatch.context() as writer_patch:
                writer_patch.setattr(MasterAuthorityUnit, "promote_staged", hold_promoted_master)
                writer_patch.setattr(
                    SpatialPairVersionedRepository, "get_command_receipt_v2", capture_writer_first_receipt
                )
                approval_task = asyncio.create_task(
                    _approve_shot(gate_export_client, project_dir, "SH01", b"review-writer-first-parent")
                )
                try:
                    await asyncio.wait_for(writer_has_head.wait(), timeout=10)
                    decision_task = asyncio.create_task(
                        pair_service.decide(fourth_command, authenticated_user=interactive)
                    )
                    blocked = False
                    for _ in range(500):
                        async with session_factory() as observer:
                            blockers = (
                                await observer.scalar(select(func.pg_blocking_pids(writer_first_decision_pid[0])))
                                if writer_first_decision_pid
                                else []
                            )
                        if writer_pid and writer_pid[0] in blockers:
                            blocked = True
                            break
                        if decision_task.done():
                            break
                        await asyncio.sleep(0.01)
                    assert blocked, "V2 decision must wait for Gate C's master-head transaction"
                finally:
                    release_writer.set()
                    if decision_task is None:
                        await asyncio.wait_for(asyncio.gather(approval_task, return_exceptions=True), timeout=10)
                    else:
                        await asyncio.wait_for(
                            asyncio.gather(approval_task, decision_task, return_exceptions=True), timeout=10
                        )
                approval_task.result()
                assert decision_task is not None
                with pytest.raises(FrameSourceConflictError):
                    await asyncio.wait_for(decision_task, timeout=10)
            async with session_factory() as session:
                assert await session.scalar(select(func.count()).select_from(SpatialPairDecisionModel)) == 3
                fourth_row = await session.get(
                    SpatialReviewSessionModel, (USER.id, PROJECT, fourth_snapshot.session_id)
                )
                assert fourth_row is not None
                assert fourth_row.consumed_command_digest is None

            return

        original_grant_read = CurrentShowrunnerGrantReader.require_current_locked
        decision_holds_sources = asyncio.Event()
        release_decision = asyncio.Event()

        async def pause_after_source_locks(self, session: AsyncSession, *, scope: GrantScopeV1):
            current = await original_grant_read(self, session, scope=scope)
            decision_holds_sources.set()
            await release_decision.wait()
            return current

        with monkeypatch.context() as source_patch:
            source_patch.setattr(CurrentShowrunnerGrantReader, "require_current_locked", pause_after_source_locks)
            replay_task = asyncio.create_task(pair_service.decide(reject_command, authenticated_user=interactive))
            approval_task = None
            try:
                await asyncio.wait_for(decision_holds_sources.wait(), timeout=10)
                approval_task = await _start_blocked_master_writer(
                    session_factory, _approve_shot(gate_export_client, project_dir, "SH01", b"review-next-parent")
                )
            finally:
                release_decision.set()
            assert await asyncio.wait_for(replay_task, timeout=10) == rejected
            assert approval_task is not None
            await asyncio.wait_for(approval_task, timeout=10)
        with pytest.raises(FrameSourceConflictError):
            await pair_service.decide(reject_command, authenticated_user=interactive)
