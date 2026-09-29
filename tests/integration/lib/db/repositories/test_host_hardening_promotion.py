"""Integration coverage for M7-B's atomic master promotion repositories:
immutable candidates, one CASed master head per artifact, promotion-receipt
idempotency/conflict, backup-set retention, and real PostgreSQL concurrent CAS."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.host_hardening import MasterAuthorityModel
from lib.db.repositories.host_hardening import (
    ActiveAttemptReferenceCheckImpl,
    BackupSetRepository,
    CandidateIdentityConflictError,
    CandidateObjectRepository,
    MasterAuthorityRepository,
    MasterHeadConflictError,
    MasterHeadReferenceCheckImpl,
    PromotionReceiptConflictError,
    PromotionReceiptRepository,
)
from r2.contracts.host_hardening import MasterHeadSnapshot, PromotionReceipt, VerifiedCandidateObject
from r2.host_hardening.promotion import AtomicPromotionService, PromotionExpectedVersionConflictError
from r2.host_hardening.retention import CandidateRetentionPolicy

type Factory = async_sessionmaker[AsyncSession]

USER = "u1"
PROJECT = "demo"
ARTIFACT_KEY = "videos/E1S01"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


async def _skip_unless_postgres(session_factory: Factory) -> None:
    async with session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("concurrency races need real row-level locking (PostgreSQL only)")


def _candidate(candidate_id: str, **overrides: object) -> VerifiedCandidateObject:
    defaults: dict[str, object] = {
        "candidate_id": candidate_id,
        "project_name": PROJECT,
        "artifact_key": ARTIFACT_KEY,
        "object_ref": f"/data/{PROJECT}/videos/{candidate_id}.mp4",
        "byte_size": 1024,
        "content_digest": "sha256:" + candidate_id,
        "media_probe_digest": "sha256:probe-" + candidate_id,
    }
    defaults.update(overrides)
    return VerifiedCandidateObject(**defaults)


# --- CandidateObjectRepository --------------------------------------------------------


async def test_candidate_object_repository_round_trips(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = CandidateObjectRepository(session)
        await repo.insert(user_id=USER, project_name=PROJECT, candidate=_candidate("cand-1"), created_at=NOW)
        await session.commit()

    async with session_factory() as session:
        fetched = await CandidateObjectRepository(session).get_exact(
            user_id=USER, project_name=PROJECT, candidate_id="cand-1"
        )
    assert fetched == _candidate("cand-1")


async def test_candidate_object_repository_rejects_a_duplicate_id_with_different_bytes(
    session_factory: Factory,
) -> None:
    async with session_factory() as session:
        repo = CandidateObjectRepository(session)
        await repo.insert(user_id=USER, project_name=PROJECT, candidate=_candidate("cand-1"), created_at=NOW)
        await session.commit()

    async with session_factory() as session:
        repo = CandidateObjectRepository(session)
        with pytest.raises(CandidateIdentityConflictError):
            await repo.insert(
                user_id=USER,
                project_name=PROJECT,
                candidate=_candidate("cand-1", content_digest="sha256:different"),
                created_at=NOW,
            )


# --- MasterAuthorityRepository ---------------------------------------------------------


async def test_master_authority_lock_creates_the_pointer_at_version_zero(session_factory: Factory) -> None:
    async with session_factory() as session:
        current = await MasterAuthorityRepository(session).get_current_version(
            user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY
        )
        await session.commit()
    assert current == 0


async def test_master_authority_promotes_then_reflects_the_current_head(session_factory: Factory) -> None:
    async with session_factory() as session:
        candidates = CandidateObjectRepository(session)
        await candidates.insert(user_id=USER, project_name=PROJECT, candidate=_candidate("cand-1"), created_at=NOW)
        authorities = MasterAuthorityRepository(session)
        current = await authorities.get_current_version(user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY)
        assert current == 0
        snapshot = MasterHeadSnapshot(
            artifact_key=ARTIFACT_KEY,
            master_version=1,
            candidate_id="cand-1",
            object_ref=_candidate("cand-1").object_ref,
            content_digest="sha256:cand-1",
            approval_record="approval-1",
        )
        await authorities.insert_head_version(
            user_id=USER, project_name=PROJECT, master_head_version_id="mhv-1", snapshot=snapshot, promoted_at=NOW
        )
        await authorities.advance_head(
            user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY, expected_current_version=0, new_version=1
        )
        await session.commit()

    async with session_factory() as session:
        current_head = await MasterAuthorityRepository(session).get_current(
            user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY
        )
    assert current_head == MasterHeadSnapshot(
        artifact_key=ARTIFACT_KEY,
        master_version=1,
        candidate_id="cand-1",
        object_ref=_candidate("cand-1").object_ref,
        content_digest="sha256:cand-1",
        approval_record="approval-1",
    )


async def test_advance_head_rejects_a_stale_expected_version(session_factory: Factory) -> None:
    async with session_factory() as session:
        authorities = MasterAuthorityRepository(session)
        await authorities.get_current_version(user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY)
        await session.commit()

    async with session_factory() as session:
        authorities = MasterAuthorityRepository(session)
        with pytest.raises(MasterHeadConflictError):
            await authorities.advance_head(
                user_id=USER,
                project_name=PROJECT,
                artifact_key=ARTIFACT_KEY,
                expected_current_version=5,
                new_version=6,
            )


async def test_insert_head_version_rejects_a_concurrent_same_version(session_factory: Factory) -> None:
    async with session_factory() as session:
        candidates = CandidateObjectRepository(session)
        await candidates.insert(user_id=USER, project_name=PROJECT, candidate=_candidate("cand-1"), created_at=NOW)
        await candidates.insert(user_id=USER, project_name=PROJECT, candidate=_candidate("cand-2"), created_at=NOW)
        authorities = MasterAuthorityRepository(session)
        await authorities.insert_head_version(
            user_id=USER,
            project_name=PROJECT,
            master_head_version_id="mhv-1",
            snapshot=MasterHeadSnapshot(
                artifact_key=ARTIFACT_KEY,
                master_version=1,
                candidate_id="cand-1",
                object_ref=_candidate("cand-1").object_ref,
                content_digest="sha256:cand-1",
                approval_record="approval-1",
            ),
            promoted_at=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        authorities = MasterAuthorityRepository(session)
        with pytest.raises(MasterHeadConflictError):
            await authorities.insert_head_version(
                user_id=USER,
                project_name=PROJECT,
                master_head_version_id="mhv-2",
                snapshot=MasterHeadSnapshot(
                    artifact_key=ARTIFACT_KEY,
                    master_version=1,
                    candidate_id="cand-2",
                    object_ref=_candidate("cand-2").object_ref,
                    content_digest="sha256:cand-2",
                    approval_record="approval-2",
                ),
                promoted_at=NOW,
            )


# --- PromotionReceiptRepository ---------------------------------------------------------


def _receipt(**overrides: object) -> PromotionReceipt:
    defaults: dict[str, object] = {
        "artifact_key": ARTIFACT_KEY,
        "command_id": "cmd-1",
        "command_digest": "sha256:cmd-1",
        "candidate_id": "cand-1",
        "master_version": 1,
        "approval_record": "approval-1",
        "created_at": NOW,
    }
    defaults.update(overrides)
    return PromotionReceipt(**defaults)


async def test_promotion_receipt_round_trips(session_factory: Factory) -> None:
    async with session_factory() as session:
        await CandidateObjectRepository(session).insert(
            user_id=USER, project_name=PROJECT, candidate=_candidate("cand-1"), created_at=NOW
        )
        await PromotionReceiptRepository(session).add(user_id=USER, project_name=PROJECT, receipt=_receipt())
        await session.commit()

    async with session_factory() as session:
        fetched = await PromotionReceiptRepository(session).get_exact(
            user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY, command_id="cmd-1"
        )
    assert fetched == _receipt()


async def test_promotion_receipt_rejects_a_conflicting_replay(session_factory: Factory) -> None:
    async with session_factory() as session:
        await CandidateObjectRepository(session).insert(
            user_id=USER, project_name=PROJECT, candidate=_candidate("cand-1"), created_at=NOW
        )
        await PromotionReceiptRepository(session).add(user_id=USER, project_name=PROJECT, receipt=_receipt())
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(PromotionReceiptConflictError):
            await PromotionReceiptRepository(session).add(
                user_id=USER, project_name=PROJECT, receipt=_receipt(command_digest="sha256:different")
            )


async def test_promotion_receipt_retains_its_candidate(session_factory: Factory) -> None:
    async with session_factory() as session:
        await CandidateObjectRepository(session).insert(
            user_id=USER, project_name=PROJECT, candidate=_candidate("cand-1"), created_at=NOW
        )
        await PromotionReceiptRepository(session).add(user_id=USER, project_name=PROJECT, receipt=_receipt())
        await session.commit()

    async with session_factory() as session:
        retained = await PromotionReceiptRepository(session).has_retained_receipt_for_candidate(
            user_id=USER, project_name=PROJECT, candidate_id="cand-1"
        )
        not_retained = await PromotionReceiptRepository(session).has_retained_receipt_for_candidate(
            user_id=USER, project_name=PROJECT, candidate_id="cand-2"
        )
    assert retained is True
    assert not_retained is False


# --- BackupSetRepository ----------------------------------------------------------------


async def test_incomplete_backup_set_blocks_its_referenced_candidate(session_factory: Factory) -> None:
    async with session_factory() as session:
        await CandidateObjectRepository(session).insert(
            user_id=USER, project_name=PROJECT, candidate=_candidate("cand-1"), created_at=NOW
        )
        backups = BackupSetRepository(session)
        await backups.insert(user_id=USER, project_name=PROJECT, backup_set_id="bset-1", state="PREPARING", now=NOW)
        await backups.add_media_ref(backup_set_id="bset-1", candidate_id="cand-1")
        await session.commit()

    async with session_factory() as session:
        blocked = await BackupSetRepository(session).has_incomplete_backup_referencing(
            user_id=USER, project_name=PROJECT, candidate_id="cand-1"
        )
    assert blocked is True


async def test_verified_backup_set_does_not_block_its_referenced_candidate(session_factory: Factory) -> None:
    async with session_factory() as session:
        await CandidateObjectRepository(session).insert(
            user_id=USER, project_name=PROJECT, candidate=_candidate("cand-1"), created_at=NOW
        )
        backups = BackupSetRepository(session)
        await backups.insert(user_id=USER, project_name=PROJECT, backup_set_id="bset-1", state="VERIFIED", now=NOW)
        await backups.add_media_ref(backup_set_id="bset-1", candidate_id="cand-1")
        await session.commit()

    async with session_factory() as session:
        blocked = await BackupSetRepository(session).has_incomplete_backup_referencing(
            user_id=USER, project_name=PROJECT, candidate_id="cand-1"
        )
    assert blocked is False


# --- MasterHeadReferenceCheckImpl --------------------------------------------------------


async def test_master_head_reference_check_reflects_the_current_promoted_candidate(
    session_factory: Factory,
) -> None:
    async with session_factory() as session:
        candidates = CandidateObjectRepository(session)
        await candidates.insert(user_id=USER, project_name=PROJECT, candidate=_candidate("cand-1"), created_at=NOW)
        await candidates.insert(user_id=USER, project_name=PROJECT, candidate=_candidate("cand-2"), created_at=NOW)
        authorities = MasterAuthorityRepository(session)
        await authorities.get_current_version(user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY)
        await authorities.insert_head_version(
            user_id=USER,
            project_name=PROJECT,
            master_head_version_id="mhv-1",
            snapshot=MasterHeadSnapshot(
                artifact_key=ARTIFACT_KEY,
                master_version=1,
                candidate_id="cand-1",
                object_ref=_candidate("cand-1").object_ref,
                content_digest="sha256:cand-1",
                approval_record="approval-1",
            ),
            promoted_at=NOW,
        )
        await authorities.advance_head(
            user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY, expected_current_version=0, new_version=1
        )
        await session.commit()

    async with session_factory() as session:
        check = MasterHeadReferenceCheckImpl(session)
        assert await check.references_candidate(user_id=USER, project_name=PROJECT, candidate_id="cand-1") is True
        assert await check.references_candidate(user_id=USER, project_name=PROJECT, candidate_id="cand-2") is False


# --- CandidateRetentionPolicy wired against the real repositories ----------------------


async def test_retention_policy_over_real_repositories_blocks_a_promoted_candidate(
    session_factory: Factory,
) -> None:
    async with session_factory() as session:
        candidates = CandidateObjectRepository(session)
        await candidates.insert(user_id=USER, project_name=PROJECT, candidate=_candidate("cand-1"), created_at=NOW)
        authorities = MasterAuthorityRepository(session)
        await authorities.get_current_version(user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY)
        await authorities.insert_head_version(
            user_id=USER,
            project_name=PROJECT,
            master_head_version_id="mhv-1",
            snapshot=MasterHeadSnapshot(
                artifact_key=ARTIFACT_KEY,
                master_version=1,
                candidate_id="cand-1",
                object_ref=_candidate("cand-1").object_ref,
                content_digest="sha256:cand-1",
                approval_record="approval-1",
            ),
            promoted_at=NOW,
        )
        await authorities.advance_head(
            user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY, expected_current_version=0, new_version=1
        )
        receipts = PromotionReceiptRepository(session)
        await receipts.add(user_id=USER, project_name=PROJECT, receipt=_receipt())
        await session.commit()

    async with session_factory() as session:
        policy = CandidateRetentionPolicy(
            master_head=MasterHeadReferenceCheckImpl(session),
            active_attempt=ActiveAttemptReferenceCheckImpl(),
            retained_receipt=PromotionReceiptRepository(session),
            incomplete_backup=BackupSetRepository(session),
        )
        # The master-head check alone already blocks this candidate; the fail-closed
        # active-attempt placeholder (see ActiveAttemptReferenceCheckImpl) would too.
        assert await policy.can_delete(user_id=USER, project_name=PROJECT, candidate_id="cand-1") is False


# --- real PostgreSQL concurrent CAS ------------------------------------------------------


async def test_concurrent_promotion_has_exactly_one_winner(session_factory: Factory) -> None:
    await _skip_unless_postgres(session_factory)
    async with session_factory() as setup_session:
        candidates = CandidateObjectRepository(setup_session)
        await candidates.insert(user_id=USER, project_name=PROJECT, candidate=_candidate("cand-1"), created_at=NOW)
        await candidates.insert(user_id=USER, project_name=PROJECT, candidate=_candidate("cand-2"), created_at=NOW)
        # Pre-create and commit the master-authority pointer row: otherwise both
        # tasks below race to INSERT it themselves, and the loser blocks on that
        # uncommitted row inside get_current_version() before ever reaching the
        # barrier -- deadlocking against the winner, which is itself waiting at
        # the barrier for the loser. Real concurrent promotions in production
        # race after the pointer already exists (this is a promotion of an
        # existing artifact), so this matches the intended scenario.
        await MasterAuthorityRepository(setup_session).get_current_version(
            user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY
        )
        await setup_session.commit()

    barrier = asyncio.Barrier(2)

    async def _try_promote(candidate_id: str, master_head_version_id: str) -> bool:
        async with session_factory() as session:
            authorities = MasterAuthorityRepository(session)
            current = await authorities.get_current_version(
                user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY
            )
            await barrier.wait()
            try:
                await authorities.insert_head_version(
                    user_id=USER,
                    project_name=PROJECT,
                    master_head_version_id=master_head_version_id,
                    snapshot=MasterHeadSnapshot(
                        artifact_key=ARTIFACT_KEY,
                        master_version=current + 1,
                        candidate_id=candidate_id,
                        object_ref=_candidate(candidate_id).object_ref,
                        content_digest="sha256:" + candidate_id,
                        approval_record="approval-" + candidate_id,
                    ),
                    promoted_at=NOW,
                )
                await authorities.advance_head(
                    user_id=USER,
                    project_name=PROJECT,
                    artifact_key=ARTIFACT_KEY,
                    expected_current_version=current,
                    new_version=current + 1,
                )
                await session.commit()
                return True
            except MasterHeadConflictError:
                await session.rollback()
                return False

    results = await asyncio.wait_for(
        asyncio.gather(_try_promote("cand-1", "mhv-a"), _try_promote("cand-2", "mhv-b")), timeout=10.0
    )
    assert sorted(results) == [False, True]

    async with session_factory() as session:
        head = await MasterAuthorityRepository(session).get_current(
            user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY
        )
    assert head is not None
    assert head.master_version == 1
    assert head.candidate_id in ("cand-1", "cand-2")


def _promotion_service(session: AsyncSession) -> AtomicPromotionService:
    return AtomicPromotionService(
        candidates=CandidateObjectRepository(session),
        authorities=MasterAuthorityRepository(session),
        receipts=PromotionReceiptRepository(session),
        clock=lambda: NOW,
        commit=session.commit,
    )


async def _wait_for_a_lock_waiter(session_factory: Factory) -> None:
    async with session_factory() as probe:
        for _ in range(200):
            waiting = (
                await probe.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                    )
                )
            ).scalar_one()
            if waiting:
                return
            await probe.rollback()
            await asyncio.sleep(0.02)
    pytest.fail("the second promotion never waited on the authority row lock")


async def test_a_promotion_waits_on_a_held_authority_row_before_appending_history(
    session_factory: Factory,
) -> None:
    """A row-lock holder (``serialized_artifacts``, an M8 slot lock) then promoting the same slot
    must not deadlock against an unserialized promotion started in between."""
    await _skip_unless_postgres(session_factory)
    async with session_factory() as setup_session:
        candidates = CandidateObjectRepository(setup_session)
        await candidates.insert(user_id=USER, project_name=PROJECT, candidate=_candidate("cand-1"), created_at=NOW)
        await candidates.insert(user_id=USER, project_name=PROJECT, candidate=_candidate("cand-2"), created_at=NOW)
        await MasterAuthorityRepository(setup_session).get_current_version(
            user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY
        )
        await setup_session.commit()

    async with session_factory() as holder:
        await holder.execute(
            update(MasterAuthorityModel)
            .where(
                MasterAuthorityModel.user_id == USER,
                MasterAuthorityModel.project_name == PROJECT,
                MasterAuthorityModel.artifact_key == ARTIFACT_KEY,
            )
            .values(current_version=MasterAuthorityModel.current_version)
        )

        async def _unserialized() -> MasterHeadSnapshot:
            async with session_factory() as session:
                return await _promotion_service(session).promote(
                    user_id=USER,
                    project_name=PROJECT,
                    artifact_key=ARTIFACT_KEY,
                    candidate_id="cand-2",
                    expected_master_version=0,
                    approval_record="approval-cand-2",
                    command_id="cmd-unserialized",
                )

        contender = asyncio.create_task(_unserialized())
        await _wait_for_a_lock_waiter(session_factory)
        winner = await asyncio.wait_for(
            _promotion_service(holder).promote(
                user_id=USER,
                project_name=PROJECT,
                artifact_key=ARTIFACT_KEY,
                candidate_id="cand-1",
                expected_master_version=0,
                approval_record="approval-cand-1",
                command_id="cmd-holder",
            ),
            timeout=10.0,
        )

    with pytest.raises((MasterHeadConflictError, PromotionExpectedVersionConflictError)):
        await asyncio.wait_for(contender, timeout=10.0)
    async with session_factory() as session:
        head = await MasterAuthorityRepository(session).get_current(
            user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY
        )
    assert winner.candidate_id == "cand-1"
    assert head == winner
