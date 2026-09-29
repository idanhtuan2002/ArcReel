"""The M8 exploration repository on a real database (plan Task A2.2)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.advanced_creative import (
    M8CandidateRevisionModel,
    M8CommandReceiptModel,
    M8PromotionAuthorizationModel,
    M8PromotionPreviewModel,
)
from lib.db.repositories.advanced_creative import ExplorationRepository
from r2.advanced_creative.digests import digest_payload
from r2.advanced_creative.errors import CandidateConflictError, CommandConflictError, ExplorationNotFoundError
from r2.contracts.advanced_creative import (
    CandidateHead,
    CanvasCandidate,
    CanvasNode,
    ExplorationKind,
    ExplorationRevision,
    LineageBinding,
)

type Factory = async_sessionmaker[AsyncSession]

USER = "default"
PROJECT = "demo"
CANDIDATE = "0199c1d8-0000-7000-8000-000000000001"
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


def _revision(revision: int, *, label: str = "v", candidate_id: str = CANDIDATE, project: str = PROJECT):
    payload = CanvasCandidate(
        kind=ExplorationKind.CANVAS,
        graph_schema_version="1",
        nodes=(CanvasNode(node_id="n1", node_type="shot", body={"label": label}),),
        edges=(),
        groups=(),
        storyboard_order=("n1",),
        viewport_bookmarks=(),
    )
    lineage = LineageBinding(
        project_name=project,
        content_basis_digest=DIGEST,
        approved_master_id=None,
        approved_master_digest=None,
        creative_profile_id="profile",
        creative_profile_version="1",
        policy_digest=DIGEST,
    )
    return ExplorationRevision(
        candidate_id=candidate_id,
        revision=revision,
        kind=ExplorationKind.CANVAS,
        parent_revision=None if revision == 1 else revision - 1,
        payload=payload,
        payload_digest=digest_payload(payload, lineage),
        lineage=lineage,
        created_by="actor-1",
        created_at=NOW,
    )


async def _append(factory: Factory, candidate: ExplorationRevision, expected: int | None, command: str, **scope):
    async with factory() as session:
        head = await ExplorationRepository(session).append_revision(
            user_id=scope.get("user_id", USER),
            project_name=scope.get("project_name", PROJECT),
            candidate=candidate,
            expected_head_version=expected,
            command_id=command,
        )
        await session.commit()
        return head


async def _count(factory: Factory, model) -> int:
    async with factory() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def _skip_unless_postgres(factory: Factory) -> None:
    async with factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("concurrent appends need PostgreSQL row locks")


async def test_genesis_append_and_exact_replay(session_factory: Factory) -> None:
    first = await _append(session_factory, _revision(1), None, "cmd-1")
    second = await _append(session_factory, _revision(2), 1, "cmd-2")
    replayed = await _append(session_factory, _revision(2), 1, "cmd-2")

    assert first == CandidateHead(candidate_id=CANDIDATE, current_revision=1, head_version=1)
    assert second == replayed == CandidateHead(candidate_id=CANDIDATE, current_revision=2, head_version=2)
    assert await _count(session_factory, M8CandidateRevisionModel) == 2
    assert await _count(session_factory, M8CommandReceiptModel) == 2


async def test_a_replay_returns_the_original_head_after_later_appends(session_factory: Factory) -> None:
    await _append(session_factory, _revision(1), None, "cmd-1")
    await _append(session_factory, _revision(2), 1, "cmd-2")

    replayed = await _append(session_factory, _revision(1), None, "cmd-1")

    assert replayed == CandidateHead(candidate_id=CANDIDATE, current_revision=1, head_version=1)


async def test_a_reused_command_id_with_another_request_conflicts(session_factory: Factory) -> None:
    await _append(session_factory, _revision(1), None, "cmd-1")

    with pytest.raises(CommandConflictError):
        await _append(session_factory, _revision(1, label="other"), None, "cmd-1")


@pytest.mark.parametrize(("revision", "expected"), [(3, 1), (2, 7)])
async def test_a_wrong_parent_or_stale_head_version_conflicts(
    session_factory: Factory, revision: int, expected: int
) -> None:
    await _append(session_factory, _revision(1), None, "cmd-1")

    with pytest.raises(CandidateConflictError):
        await _append(session_factory, _revision(revision), expected, "cmd-x")


async def test_a_payload_digest_that_does_not_match_conflicts(session_factory: Factory) -> None:
    forged = _revision(1).model_copy(update={"payload_digest": "sha256:" + "b" * 64})

    with pytest.raises(CandidateConflictError):
        await _append(session_factory, forged, None, "cmd-1")


async def test_history_is_immutable_and_the_same_payload_can_be_an_explicit_later_revision(
    session_factory: Factory,
) -> None:
    original = _revision(1)
    await _append(session_factory, original, None, "cmd-1")
    await _append(session_factory, _revision(2, label="changed"), 1, "cmd-2")
    await _append(session_factory, _revision(3), 2, "cmd-3")  # same payload as revision 1

    async with session_factory() as session:
        repository = ExplorationRepository(session)
        stored = await repository.get_exact(user_id=USER, project_name=PROJECT, candidate_id=CANDIDATE, revision=1)
        third = await repository.get_exact(user_id=USER, project_name=PROJECT, candidate_id=CANDIDATE, revision=3)

    assert stored == original
    assert stored is not None
    assert digest_payload(stored.payload, stored.lineage) == original.payload_digest
    assert third is not None
    assert third.payload_digest == original.payload_digest


async def test_a_foreign_scope_is_indistinguishable_from_an_unknown_candidate(session_factory: Factory) -> None:
    await _append(session_factory, _revision(1), None, "cmd-1")

    async with session_factory() as session:
        repository = ExplorationRepository(session)
        foreign = await repository.get_exact(user_id=USER, project_name="other", candidate_id=CANDIDATE, revision=1)
        unknown = await repository.get_exact(user_id=USER, project_name=PROJECT, candidate_id="missing", revision=1)
    assert foreign is None
    assert unknown is None

    with pytest.raises(ExplorationNotFoundError):
        await _append(session_factory, _revision(2, project="other"), 1, "cmd-2", project_name="other")
    with pytest.raises(ExplorationNotFoundError):
        await _append(session_factory, _revision(2, candidate_id="missing"), 1, "cmd-3")


async def test_history_pages_in_revision_order(session_factory: Factory) -> None:
    await _append(session_factory, _revision(1), None, "cmd-1")
    for revision in range(2, 6):
        await _append(session_factory, _revision(revision, label=str(revision)), revision - 1, f"cmd-{revision}")

    async with session_factory() as session:
        repository = ExplorationRepository(session)
        page = await repository.history(
            user_id=USER, project_name=PROJECT, candidate_id=CANDIDATE, after_revision=1, limit=2
        )
        rest = await repository.history(
            user_id=USER, project_name=PROJECT, candidate_id=CANDIDATE, after_revision=3, limit=100
        )
        with pytest.raises(ValueError, match="limit"):
            await repository.history(
                user_id=USER, project_name=PROJECT, candidate_id=CANDIDATE, after_revision=None, limit=0
            )

    assert [item.revision for item in page] == [2, 3]
    assert [item.revision for item in rest] == [4, 5]


async def test_an_uncommitted_append_leaves_nothing(session_factory: Factory) -> None:
    async with session_factory() as session:
        await ExplorationRepository(session).append_revision(
            user_id=USER, project_name=PROJECT, candidate=_revision(1), expected_head_version=None, command_id="cmd-1"
        )
        await session.rollback()

    assert await _count(session_factory, M8CandidateRevisionModel) == 0
    assert await _count(session_factory, M8CommandReceiptModel) == 0


async def test_concurrent_genesis_has_one_winner(session_factory: Factory) -> None:
    await _skip_unless_postgres(session_factory)

    results = await asyncio.gather(
        _append(session_factory, _revision(1), None, "cmd-a"),
        _append(session_factory, _revision(1, label="b"), None, "cmd-b"),
        return_exceptions=True,
    )

    assert sum(isinstance(result, CandidateHead) for result in results) == 1
    assert sum(isinstance(result, CandidateConflictError) for result in results) == 1


async def test_concurrent_appends_on_one_head_have_one_winner(session_factory: Factory) -> None:
    await _skip_unless_postgres(session_factory)
    await _append(session_factory, _revision(1), None, "cmd-1")

    results = await asyncio.gather(
        _append(session_factory, _revision(2, label="a"), 1, "cmd-a"),
        _append(session_factory, _revision(2, label="b"), 1, "cmd-b"),
        return_exceptions=True,
    )

    assert sum(isinstance(result, CandidateHead) for result in results) == 1
    assert sum(isinstance(result, CandidateConflictError) for result in results) == 1
    assert await _count(session_factory, M8CandidateRevisionModel) == 2


async def test_concurrent_replays_of_one_command_write_once(session_factory: Factory) -> None:
    await _skip_unless_postgres(session_factory)
    await _append(session_factory, _revision(1), None, "cmd-1")

    results = await asyncio.gather(
        _append(session_factory, _revision(2), 1, "cmd-2"),
        _append(session_factory, _revision(2), 1, "cmd-2"),
        return_exceptions=True,
    )

    assert all(isinstance(result, CandidateHead) for result in results), results
    assert await _count(session_factory, M8CandidateRevisionModel) == 2


async def test_the_database_refuses_an_authorization_bound_to_a_preview_of_another_scope(
    session_factory: Factory,
) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("SQLite test databases do not enforce foreign keys")
    await _append(session_factory, _revision(1), None, "cmd-1")
    async with session_factory() as session:
        session.add(
            M8PromotionPreviewModel(
                user_id=USER,
                project_name=PROJECT,
                preview_id="preview-1",
                preview_command_id="preview-cmd-1",
                candidate_id=CANDIDATE,
                candidate_revision=1,
                candidate_payload_digest=DIGEST,
                target_kind="PRODUCTION_BINDING",
                target_ref="binding-1",
                expected_target_version=0,
                expected_master_id=None,
                expected_master_digest=None,
                impact_json={},
                impact_digest=DIGEST,
                preview_digest=DIGEST,
                authorization_scope=USER,
                issued_at=NOW,
                expires_at=NOW,
                ttl_seconds=60,
            )
        )
        await session.commit()

    def authorization(project_name: str) -> M8PromotionAuthorizationModel:
        return M8PromotionAuthorizationModel(
            user_id=USER,
            project_name=project_name,
            command_id="auth-1",
            preview_id="preview-1",
            preview_digest=DIGEST,
            actor_id=USER,
            actor_scope=USER,
            decision="APPROVE",
            authorized_at=NOW,
            authorization_digest=DIGEST,
        )

    async with session_factory() as session:
        session.add(authorization("other"))
        with pytest.raises(IntegrityError):
            await session.commit()
    async with session_factory() as session:
        session.add(authorization(PROJECT))
        await session.commit()
    assert await _count(session_factory, M8PromotionAuthorizationModel) == 1
