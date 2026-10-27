"""Scoped publication storage on real PostgreSQL; fixtures confer no Human authority."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.governance_grant import ShowrunnerGrantEventModel, ShowrunnerGrantHeadModel
from lib.db.models.quality import (
    ProfilePublicationAuthorizationModel,
    QualityCommandModel,
    QualityOutboxModel,
    QualityProfileHeadModel,
    QualityProfileRevisionModel,
)
from lib.db.repositories.quality import QualityProfileRepository
from r2.quality.errors import (
    CommandReplayConflictError,
    M10Error,
    ProfileStaleError,
    SchemaChangeRequiredError,
    StaleHeadError,
)
from r2.quality.profiles import build_published_profile
from tests.unit.r2.contracts.test_quality import NOW
from tests.unit.r2.quality.test_quality_profiles import POLICY_ID, publication_lease, publication_request

MIGRATION_PATH = Path(__file__).resolve().parents[5] / "alembic/versions/65f53650f3a8_quality_profile_publication.py"

type Factory = async_sessionmaker[AsyncSession]


def request_for(revision: int = 1, command_id: str = "publish", **changes: Any):
    request = publication_request(
        user_id="default", revision=revision, parent_revision=None if revision == 1 else revision - 1, **changes
    )
    return request.model_copy(update={"command": request.command.model_copy(update={"command_id": command_id})})


def lease_for(request):
    return publication_lease(request).model_copy(update={"authorization_id": "issued-" + request.command.command_id})


@pytest.fixture
async def quality_factory(session_factory: Factory) -> Factory:
    async with session_factory() as session:
        if session.get_bind().dialect.name != "postgresql":
            pytest.skip("authoritative publication requires real PostgreSQL")
        async with session.begin():
            path = MIGRATION_PATH
            spec = importlib.util.spec_from_file_location("m10_publication_migration_fixture", path)
            assert spec is not None
            assert spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            connection = await session.connection()
            await connection.run_sync(module.install_immutability)
            session.add(
                ShowrunnerGrantHeadModel(
                    user_id="default",
                    project_name="project",
                    principal="actor",
                    current_sequence=None,
                    current_event_digest=None,
                )
            )
            await session.flush()
            session.add(
                ShowrunnerGrantEventModel(
                    user_id="default",
                    project_name="project",
                    principal="actor",
                    sequence=1,
                    raw_event=b"database-fixture-not-authority",
                    event_digest="sha256:" + "a" * 64,
                    event_type="ISSUE",
                    issued_at="2026-10-26T00:00:00Z",
                    signer_key_id="fixture",
                    imported_at=NOW,
                )
            )
    return session_factory


async def record(factory: Factory, request):
    lease = lease_for(request)
    async with factory() as session, session.begin():
        await QualityProfileRepository(session).record_authorization(request, lease, grant_sequence=1)
    return lease


async def append(factory: Factory, request):
    lease = await record(factory, request)
    profile = build_published_profile(request, lease, NOW, policy_id=POLICY_ID, policy_version="1")
    async with factory() as session, session.begin():
        repository = QualityProfileRepository(session)
        await repository.lock_command(request.command)
        await repository.lock_profile(request)
        await repository.stage_publication(request, lease, profile, NOW)
    return profile


async def test_sqlite_refuses_authoritative_storage_and_replay(file_session_factory: Factory) -> None:
    request = request_for()
    async with file_session_factory() as session:
        with pytest.raises(SchemaChangeRequiredError):
            await QualityProfileRepository(session).replay(request)
        async with session.begin():
            with pytest.raises(SchemaChangeRequiredError):
                await QualityProfileRepository(session).lock_command(request.command)


async def test_genesis_head_advance_scoped_read_and_historical_exact_replay(quality_factory: Factory) -> None:
    first_request = request_for()
    first = await append(quality_factory, first_request)
    second = await append(quality_factory, request_for(2, "publish-2"))
    async with quality_factory() as session:
        repository = QualityProfileRepository(session)
        assert await repository.replay(first_request) == first
        assert (
            await repository.get_revision(
                user_id="default", project_name="project", profile_id=first.profile_id, revision=2
            )
            == second
        )
        assert (
            await repository.get_revision(
                user_id="default", project_name="other", profile_id=first.profile_id, revision=1
            )
            is None
        )
        assert (await session.execute(sa.select(QualityProfileHeadModel.current_revision))).scalar_one() == 2
        for model in [QualityProfileRevisionModel, QualityCommandModel, QualityOutboxModel]:
            assert (await session.execute(sa.select(sa.func.count()).select_from(model))).scalar_one() == 2


async def test_same_full_command_key_with_changed_semantics_conflicts(quality_factory: Factory) -> None:
    await append(quality_factory, request_for())
    async with quality_factory() as session:
        with pytest.raises(CommandReplayConflictError):
            await QualityProfileRepository(session).replay(request_for(cohort_id="changed"))


@pytest.mark.parametrize("changes", [{"cohort_id": "changed"}, {"product_surface": "changed"}])
async def test_profile_lineage_cannot_change_genesis_cohort_or_surface(
    quality_factory: Factory, changes: dict[str, str]
) -> None:
    await append(quality_factory, request_for())
    async with quality_factory() as session, session.begin():
        with pytest.raises(ProfileStaleError):
            await QualityProfileRepository(session).lock_profile(request_for(2, "other", **changes))


async def test_non_genesis_request_cannot_create_genesis(quality_factory: Factory) -> None:
    async with quality_factory() as session, session.begin():
        with pytest.raises(StaleHeadError):
            await QualityProfileRepository(session).lock_profile(request_for(2))


async def test_rollback_leaves_no_partial_publication_outputs(quality_factory: Factory) -> None:
    request = request_for()
    lease = await record(quality_factory, request)
    profile = build_published_profile(request, lease, NOW, policy_id=POLICY_ID, policy_version="1")

    async def cut_before_commit() -> None:
        async with quality_factory() as session, session.begin():
            repo = QualityProfileRepository(session)
            await repo.lock_command(request.command)
            await repo.stage_publication(request, lease, profile, NOW)
            raise RuntimeError("driver-boundary-cut")

    with pytest.raises(RuntimeError, match="driver-boundary-cut"):
        await cut_before_commit()
    async with quality_factory() as session:
        for model in [QualityProfileHeadModel, QualityProfileRevisionModel, QualityCommandModel, QualityOutboxModel]:
            assert (await session.execute(sa.select(sa.func.count()).select_from(model))).scalar_one() == 0
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(ProfilePublicationAuthorizationModel))
        ).scalar_one() == 1


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("m10_quality_profile_revisions", "policy_digest"),
        ("m10_quality_commands", "result_digest"),
        ("m10_profile_publication_authorizations", "subject_digest"),
    ],
)
async def test_full_stored_bodies_and_duplicated_columns_are_revalidated(
    quality_factory: Factory, table: str, column: str
) -> None:
    request = request_for()
    await append(quality_factory, request)
    async with quality_factory() as session, session.begin():
        await session.execute(sa.text(f'ALTER TABLE "{table}" DISABLE TRIGGER USER'))
        await session.execute(sa.text(f'UPDATE "{table}" SET "{column}"=:digest'), {"digest": "sha256:" + "b" * 64})
        await session.execute(sa.text(f'ALTER TABLE "{table}" ENABLE TRIGGER USER'))
    async with quality_factory() as session:
        with pytest.raises(M10Error):
            await QualityProfileRepository(session).replay(request)


async def test_outbox_contains_only_bounded_publication_metadata(quality_factory: Factory) -> None:
    request = request_for()
    profile = await append(quality_factory, request)
    async with quality_factory() as session:
        event = (await session.execute(sa.select(QualityOutboxModel))).scalar_one()
        assert event.event_json == {
            "event_type": "PROFILE_PUBLISHED",
            "user_id": "default",
            "project_name": "project",
            "actor_id": "actor",
            "operation": "PUBLISH_PROFILE",
            "command_id": "publish",
            "profile_id": profile.profile_id,
            "revision": 1,
            "profile_digest": profile.profile_digest,
            "previous_revision": None,
            "cohort_id": profile.cohort_id,
            "product_surface": profile.product_surface,
            "supersession_effect": "HISTORICAL_ONLY",
            "admitted_at": "2026-10-26T00:00:00Z",
        }


async def test_unissued_lease_cannot_stage_publication(quality_factory: Factory) -> None:
    request = request_for()
    lease = lease_for(request)
    profile = build_published_profile(request, lease, NOW, policy_id=POLICY_ID, policy_version="1")
    async with quality_factory() as session, session.begin():
        with pytest.raises(M10Error):
            await QualityProfileRepository(session).stage_publication(request, lease, profile, NOW)
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(QualityProfileRevisionModel))
        ).scalar_one() == 0


async def test_oversized_request_is_rejected_before_any_sql(quality_factory: Factory) -> None:
    from r2.quality.errors import OperationalEnvelopeExceededError
    from tests.unit.r2.quality.test_quality_profiles import sized_request

    request = sized_request(1_048_577)
    async with quality_factory() as session:
        engine = session.get_bind()

        def forbidden_sql(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("oversized publication crossed SQL driver boundary")

        sa.event.listen(engine, "before_cursor_execute", forbidden_sql)
        try:
            with pytest.raises(OperationalEnvelopeExceededError):
                await QualityProfileRepository(session).replay(request)
        finally:
            sa.event.remove(engine, "before_cursor_execute", forbidden_sql)


async def test_forged_lease_shape_has_sanitized_error_before_storage(quality_factory: Factory) -> None:
    from r2.quality.errors import ProfilePublicationUnauthorizedError

    request = request_for()
    forged = lease_for(request).model_copy(update={"action": "UNTRUSTED-LEASE-CANARY"})
    async with quality_factory() as session, session.begin():
        with pytest.raises(ProfilePublicationUnauthorizedError) as caught:
            await QualityProfileRepository(session).record_authorization(request, forged, grant_sequence=1)
        assert "UNTRUSTED-LEASE-CANARY" not in str(caught.value)
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(ProfilePublicationAuthorizationModel))
        ).scalar_one() == 0


async def test_direct_profile_read_resolves_action_receipt_beyond_recomputed_digest_columns(
    quality_factory: Factory,
) -> None:
    from r2.quality.digests import compute_digest
    from r2.quality.errors import RequiredEvidenceMissingError

    original = await append(quality_factory, request_for())
    body = original.model_dump(mode="json")
    body["publication_evidence_digest"] = "sha256:" + "b" * 64
    body["profile_digest"] = compute_digest("m10.quality-profile.v1", body)
    async with quality_factory() as session, session.begin():
        await session.execute(sa.text("ALTER TABLE m10_quality_profile_revisions DISABLE TRIGGER USER"))
        await session.execute(
            sa.update(QualityProfileRevisionModel).values(body_json=body, profile_digest=body["profile_digest"])
        )
        await session.execute(sa.text("ALTER TABLE m10_quality_profile_revisions ENABLE TRIGGER USER"))
    async with quality_factory() as session:
        with pytest.raises(RequiredEvidenceMissingError):
            await QualityProfileRepository(session).get_revision(
                user_id="default", project_name="project", profile_id=original.profile_id, revision=1
            )
