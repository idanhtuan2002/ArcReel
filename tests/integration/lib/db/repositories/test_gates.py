"""Integration coverage for the P1 Gate A/D/C-receipt repositories."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.gates import (
    FinalCutReceiptRepository,
    GateSequenceConflictError,
    GreenlightRepository,
    PublishApprovalRepository,
)
from r2.contracts.gates import FinalCutReceipt, GateAuthorization, GreenlightDecision, PublishApprovalDecision

type Factory = async_sessionmaker[AsyncSession]

USER = "u1"
PROJECT = "demo"
NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def _authorization() -> GateAuthorization:
    return GateAuthorization(authenticated_principal="operator-1", authority_role="HUMAN_OPERATOR", authorized_at=NOW)


def _greenlight(*, decision_id: str, sequence: int = 1) -> GreenlightDecision:
    return GreenlightDecision(
        decision_id=decision_id,
        user_id=USER,
        project_name=PROJECT,
        source_digest="sha256:" + "a" * 64,
        action="GREENLIGHT",
        authorization=_authorization(),
        sequence=sequence,
        created_at=NOW,
    )


def _publish_approval(*, decision_id: str, sequence: int = 1) -> PublishApprovalDecision:
    return PublishApprovalDecision(
        decision_id=decision_id,
        user_id=USER,
        project_name=PROJECT,
        deliverable_digest="sha256:" + "b" * 64,
        platform="youtube",
        visibility="unlisted",
        action="APPROVE_PUBLISH",
        authorization=_authorization(),
        sequence=sequence,
        created_at=NOW,
    )


def _final_cut_receipt(*, artifact_key: str = "videos:1:SH01", sequence: int = 1) -> FinalCutReceipt:
    return FinalCutReceipt(
        user_id=USER,
        project_name=PROJECT,
        artifact_key=artifact_key,
        selected_candidate_id="CAND-1",
        content_fingerprint="sha256:" + "c" * 64,
        approval_record="APR-SH01",
        selected_by="operator-1",
        selected_at=NOW,
        sequence=sequence,
    )


# --- GreenlightRepository ---------------------------------------------------


async def test_greenlight_repository_round_trips_and_orders_by_sequence(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = GreenlightRepository(session)
        await repo.append(_greenlight(decision_id="d-1"))
        await session.commit()

    async with session_factory() as session:
        history = await GreenlightRepository(session).list_for_project(user_id=USER, project_name=PROJECT)
    assert len(history) == 1
    assert history[0].decision_id == "d-1"
    assert history[0].sequence == 1
    assert history[0].authorization == _authorization()


async def test_greenlight_repository_assigns_increasing_sequence(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = GreenlightRepository(session)
        await repo.append(_greenlight(decision_id="d-1"))
        await session.commit()
    async with session_factory() as session:
        repo = GreenlightRepository(session)
        await repo.append(_greenlight(decision_id="d-2"))
        await session.commit()

    async with session_factory() as session:
        history = await GreenlightRepository(session).list_for_project(user_id=USER, project_name=PROJECT)
    assert [d.decision_id for d in history] == ["d-1", "d-2"]
    assert [d.sequence for d in history] == [1, 2]


async def test_greenlight_repository_rejects_a_stale_sequence_computation(
    session_factory: Factory,
) -> None:
    # Simulates the real race append() is built to survive (two computations
    # of "next sequence" landing on the same value) deterministically, rather
    # than relying on timing to force a genuine concurrent race -- a real
    # asyncio.gather-based race against Postgres was tried and found flaky:
    # sub-millisecond local queries frequently completed non-overlapping, so
    # the two transactions' read-then-write windows never actually collided.
    # The exception-handling path under test (IntegrityError ->
    # GateSequenceConflictError) is identical either way.
    async with session_factory() as session:
        repo = GreenlightRepository(session)
        await repo.append(_greenlight(decision_id="d-1"))
        await session.commit()

    async def _stale(*, user_id: str, project_name: str) -> int:
        return 1  # the sequence already taken by "d-1" above

    async with session_factory() as session:
        repo = GreenlightRepository(session)
        repo._next_sequence = _stale
        with pytest.raises(GateSequenceConflictError):
            await repo.append(_greenlight(decision_id="d-2"))

    async with session_factory() as session:
        history = await GreenlightRepository(session).list_for_project(user_id=USER, project_name=PROJECT)
    assert len(history) == 1


async def test_greenlight_repository_is_scoped_per_project(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = GreenlightRepository(session)
        await repo.append(_greenlight(decision_id="d-1"))
        await session.commit()

    async with session_factory() as session:
        other_project_history = await GreenlightRepository(session).list_for_project(
            user_id=USER, project_name="other-project"
        )
    assert other_project_history == []


# --- PublishApprovalRepository ----------------------------------------------


async def test_publish_approval_repository_round_trips(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = PublishApprovalRepository(session)
        await repo.append(_publish_approval(decision_id="d-1"))
        await session.commit()

    async with session_factory() as session:
        history = await PublishApprovalRepository(session).list_for_project(user_id=USER, project_name=PROJECT)
    assert len(history) == 1
    assert history[0].platform == "youtube"
    assert history[0].visibility == "unlisted"


# --- FinalCutReceiptRepository -----------------------------------------------


async def test_final_cut_receipt_repository_round_trips(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = FinalCutReceiptRepository(session)
        await repo.append(_final_cut_receipt())
        await session.commit()

    async with session_factory() as session:
        history = await FinalCutReceiptRepository(session).list_for_artifact(
            user_id=USER, project_name=PROJECT, artifact_key="videos:1:SH01"
        )
    assert len(history) == 1
    assert history[0].selected_candidate_id == "CAND-1"
    assert history[0].sequence == 1


async def test_final_cut_receipt_repository_assigns_increasing_sequence_per_artifact(
    session_factory: Factory,
) -> None:
    async with session_factory() as session:
        repo = FinalCutReceiptRepository(session)
        await repo.append(_final_cut_receipt())
        await session.commit()
    async with session_factory() as session:
        repo = FinalCutReceiptRepository(session)
        await repo.append(_final_cut_receipt())  # a second, re-approval receipt for the same artifact
        await session.commit()

    async with session_factory() as session:
        history = await FinalCutReceiptRepository(session).list_for_artifact(
            user_id=USER, project_name=PROJECT, artifact_key="videos:1:SH01"
        )
    assert [r.sequence for r in history] == [1, 2]


async def test_final_cut_receipt_repository_is_scoped_per_artifact(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = FinalCutReceiptRepository(session)
        await repo.append(_final_cut_receipt(artifact_key="videos:1:SH01"))
        await session.commit()

    async with session_factory() as session:
        other_artifact_history = await FinalCutReceiptRepository(session).list_for_artifact(
            user_id=USER, project_name=PROJECT, artifact_key="videos:1:SH02"
        )
    assert other_artifact_history == []
