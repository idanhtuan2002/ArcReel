"""Human publication composes real host custody and atomic PostgreSQL persistence."""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.quality import (
    ProfilePublicationAuthorizationModel,
    QualityCommandModel,
    QualityOutboxModel,
    QualityProfileHeadModel,
    QualityProfileRevisionModel,
)
from r2.quality.errors import CommandReplayConflictError, RequiredEvidenceMissingError
from server import auth
from server.services.governance_attestation import serve_governance_attestor
from server.services.quality_profile_custodian import InteractiveProfilePublicationCustodian
from server.services.quality_profiles import ProfilePublicationService
from tests.integration.server.services.test_quality_profile_custodian import SECRET, prepare_qualified_custody
from tests.unit.r2.quality.test_quality_profiles import publication_request

type Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def publication_host(session_factory: Factory, tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", SECRET)
    prepared = await prepare_qualified_custody(session_factory, tmp_path)
    return session_factory, prepared


async def publisher(sessions: Factory, root, runtime, request, *, token: str | None = None):
    custodian = await InteractiveProfilePublicationCustodian.for_request(
        request,
        sessions,
        interactive_token=token or auth.create_token("actor"),
        read_directory=root / "read",
        socket_directory=runtime,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    return ProfilePublicationService(sessions, custodian=custodian)


def next_request():
    request = publication_request(user_id="default", revision=2, parent_revision=1)
    return request.model_copy(update={"command": request.command.model_copy(update={"command_id": "second"})})


async def test_actual_human_publication_and_receipt_first_replay_after_archive_disappears(publication_host) -> None:
    sessions, (root, runtime, *_rest) = publication_host
    request = publication_request(user_id="default")
    async with serve_governance_attestor(
        root, runtime, session_factory=sessions, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        service = await publisher(sessions, root, runtime, request)
        first = await service.publish(request)
        second_request = next_request()
        second = await (await publisher(sessions, root, runtime, second_request)).publish(second_request)
        assert second.revision == 2
    replay_service = await publisher(sessions, root, runtime, request)
    assert await replay_service.publish(request) == first
    changed = publication_request(user_id="default", cohort_id="other")
    with pytest.raises(CommandReplayConflictError):
        await (await publisher(sessions, root, runtime, changed)).publish(changed)
    async with sessions() as session:
        assert (await session.execute(sa.select(QualityProfileHeadModel.current_revision))).scalar_one() == 2
        for model in [
            QualityProfileRevisionModel,
            QualityCommandModel,
            QualityOutboxModel,
            ProfilePublicationAuthorizationModel,
        ]:
            assert (await session.execute(sa.select(sa.func.count()).select_from(model))).scalar_one() == 2


@pytest.mark.parametrize("cut", ["revision", "head", "receipt", "event", "before_commit", "after_commit"])
async def test_driver_crash_cuts_leave_zero_partial_state_or_exact_committed_replay(
    publication_host, cut: str, caplog: pytest.LogCaptureFixture
) -> None:
    sessions, (root, runtime, *_rest) = publication_host
    request = publication_request(user_id="default")
    token = auth.create_token("actor")
    marker = "M10-DRIVER-CUT-TOKEN-CANARY:" + token
    engine = sessions.kw["bind"].sync_engine
    statements = {
        "revision": "INSERT INTO m10_quality_profile_revisions",
        "head": "UPDATE m10_quality_profile_heads",
        "receipt": "INSERT INTO m10_quality_commands",
        "event": "INSERT INTO m10_quality_outbox",
    }

    def driver_cut(connection, cursor, statement: str, parameters, context, executemany):
        if cut in statements and statement.startswith(statements[cut]):
            raise RuntimeError(marker)

    def mark_publication(session, flush_context, instances):
        if any(isinstance(row, QualityCommandModel) for row in session.new):
            session.info["m10_publication_fixture_cut"] = True

    def commit_cut(session):
        if session.info.get("m10_publication_fixture_cut"):
            raise RuntimeError(marker)

    session_type = sessions.class_.sync_session_class
    sa.event.listen(engine, "before_cursor_execute", driver_cut)
    sa.event.listen(session_type, "before_flush", mark_publication)
    event = "after_commit" if cut == "after_commit" else "before_commit"
    if cut in {"before_commit", "after_commit"}:
        sa.event.listen(session_type, event, commit_cut)
    try:
        async with serve_governance_attestor(
            root, runtime, session_factory=sessions, expected_uid=os.getuid(), expected_gid=os.getgid()
        ):
            service = await publisher(sessions, root, runtime, request, token=token)
            with pytest.raises(RequiredEvidenceMissingError) as caught:
                await service.publish(request)
            assert marker not in str(caught.value)
            assert token not in caplog.text
    finally:
        sa.event.remove(engine, "before_cursor_execute", driver_cut)
        sa.event.remove(session_type, "before_flush", mark_publication)
        if cut in {"before_commit", "after_commit"}:
            sa.event.remove(session_type, event, commit_cut)
    async with sessions() as session:
        for model in [QualityProfileHeadModel, QualityProfileRevisionModel, QualityCommandModel, QualityOutboxModel]:
            assert (await session.execute(sa.select(sa.func.count()).select_from(model))).scalar_one() == int(
                cut == "after_commit"
            )
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(ProfilePublicationAuthorizationModel))
        ).scalar_one() == 1
    if cut == "after_commit":
        replay = await (await publisher(sessions, root, runtime, request)).publish(request)
        assert replay.revision == 1


async def wait_for_blockers(sessions: Factory, blocker_pid: int, *, minimum: int = 1) -> list[int]:
    import asyncio
    import json

    try:
        async with asyncio.timeout(20):
            while True:
                async with sessions() as probe:
                    pids = list(
                        (
                            await probe.execute(
                                sa.text(
                                    "SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
                                    "AND :blocker = ANY(pg_blocking_pids(pid)) ORDER BY pid"
                                ),
                                {"blocker": blocker_pid},
                            )
                        ).scalars()
                    )
                if len(pids) >= minimum:
                    print("M10_POSTGRES_BLOCKERS=" + json.dumps({"blocker_pid": blocker_pid, "waiter_pids": pids}))
                    return pids

    except TimeoutError:
        async with sessions() as probe:
            activity = (
                (
                    await probe.execute(
                        sa.text(
                            "SELECT pid,wait_event_type,wait_event,pg_blocking_pids(pid) AS blockers,left(query,240) AS query "
                            "FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()"
                        )
                    )
                )
                .mappings()
                .all()
            )
            print("M10_POSTGRES_WAIT_DIAGNOSTIC=" + json.dumps([dict(row) for row in activity]))
        raise AssertionError("expected PostgreSQL blockers were not observed") from None


async def seed_empty_head(sessions: Factory, request) -> None:
    draft = request.subject.profile_draft
    async with sessions() as session, session.begin():
        session.add(
            QualityProfileHeadModel(
                user_id=draft.user_id,
                project_name=draft.project_name,
                profile_id=draft.profile_id,
                current_revision=None,
                current_digest=None,
            )
        )


@pytest.mark.parametrize("order", ["publication_first", "revocation_first"])
async def test_revocation_and_publication_have_both_real_lock_orders(publication_host, order: str) -> None:
    import asyncio

    from lib.db.repositories.quality import QualityProfileRepository
    from r2.governance.grant_transition import GrantScopeV1
    from r2.quality.errors import ProfilePublicationUnauthorizedError
    from tests.integration.r2.governance.test_grant_importer import _event, _signed

    sessions, (root, runtime, importer, key, event) = publication_host
    request = publication_request(user_id="default")
    if order == "publication_first":
        await seed_empty_head(sessions, request)
    body = _event("REVOKE", 2, event.event_digest, "2026-10-27T00:00:00Z", project_name="project")
    body.update(user_id="default", principal="actor", signer_key_id="grant-key-a")
    raw = _signed(body, key)
    tasks = []
    async with serve_governance_attestor(
        root, runtime, session_factory=sessions, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        async with sessions() as holder, holder.begin():
            if order == "publication_first":
                await holder.execute(sa.select(QualityProfileHeadModel).with_for_update())
            else:
                await QualityProfileRepository(holder).lock_command(request.command)
            holder_pid = await holder.scalar(sa.text("SELECT pg_backend_pid()"))
            assert holder_pid is not None
            service = await publisher(sessions, root, runtime, request)
            publication = asyncio.create_task(service.publish(request))
            tasks.append(publication)
            try:
                publication_pid = (await wait_for_blockers(sessions, holder_pid))[0]
                revocation = asyncio.create_task(
                    importer.import_event(raw, scope=GrantScopeV1("default", "project", "actor"))
                )
                tasks.append(revocation)
                if order == "publication_first":
                    assert await wait_for_blockers(sessions, publication_pid)
                else:
                    assert (await revocation).body.event_type == "REVOKE"
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
        results = await asyncio.gather(*tasks, return_exceptions=True)
    if order == "publication_first":
        assert not isinstance(results[0], BaseException)
        assert results[0].revision == 1
    else:
        assert isinstance(results[0], ProfilePublicationUnauthorizedError)
    assert not isinstance(results[1], BaseException)
    async with sessions() as probe:
        assert (await probe.execute(sa.select(sa.func.count()).select_from(QualityCommandModel))).scalar_one() == int(
            order == "publication_first"
        )


async def test_forced_hash_collision_serializes_without_merging_full_command_keys(publication_host) -> None:
    import asyncio
    import re

    from lib.db.repositories.quality import QualityProfileRepository
    from tests.unit.r2.contracts.test_quality import OTHER_UUID

    sessions, (root, runtime, *_rest) = publication_host
    first = publication_request(user_id="default")
    second = publication_request(user_id="default", profile_id=OTHER_UUID)
    second = second.model_copy(update={"command": second.command.model_copy(update={"command_id": "distinct-command"})})
    async with sessions() as setup, setup.begin():
        schema = await setup.scalar(sa.text("SELECT current_schema()"))
        assert schema is not None
        assert re.fullmatch(r"test_[0-9a-f]{12}", schema)
        await setup.execute(
            sa.text(
                "CREATE FUNCTION hashtextextended(text,bigint) RETURNS bigint LANGUAGE sql IMMUTABLE AS $$ SELECT 42::bigint $$"
            )
        )
    engine = sessions.kw["bind"].sync_engine

    def scoped_hash_dependency(session, transaction, connection):
        if connection.engine is engine:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", pg_catalog')

    session_type = sessions.class_.sync_session_class
    sa.event.listen(session_type, "after_begin", scoped_hash_dependency)
    tasks = []
    try:
        async with serve_governance_attestor(
            root, runtime, session_factory=sessions, expected_uid=os.getuid(), expected_gid=os.getgid()
        ):
            async with sessions() as holder, holder.begin():
                assert await holder.scalar(sa.text("SELECT hashtextextended('first',0)")) == 42
                assert await holder.scalar(sa.text("SELECT hashtextextended('second',0)")) == 42
                await QualityProfileRepository(holder).lock_command(first.command)
                pid = await holder.scalar(sa.text("SELECT pg_backend_pid()"))
                assert pid is not None
                for index, request in enumerate([first, second]):
                    service = await publisher(sessions, root, runtime, request)
                    tasks.append(asyncio.create_task(service.publish(request)))
                    if index == 0:
                        assert await wait_for_blockers(sessions, pid)
                try:
                    assert len(await wait_for_blockers(sessions, pid, minimum=2)) >= 2
                except BaseException:
                    for task in tasks:
                        if task.done() and not task.cancelled():
                            error = task.exception()
                            while error is not None:
                                frames = []
                                trace = error.__traceback__
                                while trace is not None:
                                    frames.append((trace.tb_frame.f_code.co_name, trace.tb_lineno))
                                    trace = trace.tb_next
                                print("M10_COLLISION_TASK_DIAGNOSTIC", type(error).__name__, frames)
                                error = error.__context__
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise
            results = await asyncio.gather(*tasks)
        assert results[0].profile_id != results[1].profile_id
        async with sessions() as probe:
            commands = set((await probe.execute(sa.select(QualityCommandModel.command_id))).scalars())
            assert commands == {"publish", "distinct-command"}
            assert (await probe.execute(sa.select(sa.func.count()).select_from(QualityOutboxModel))).scalar_one() == 2
    finally:
        sa.event.remove(session_type, "after_begin", scoped_hash_dependency)


@pytest.mark.parametrize("race", ["same_command", "genesis_cas"])
async def test_overlapping_publications_replay_or_compare_and_set_once(publication_host, race: str) -> None:
    import asyncio

    from lib.db.repositories.quality import QualityProfileRepository
    from r2.quality.errors import StaleHeadError

    sessions, (root, runtime, *_rest) = publication_host
    first = publication_request(user_id="default")
    second = (
        first
        if race == "same_command"
        else first.model_copy(update={"command": first.command.model_copy(update={"command_id": "competing-genesis"})})
    )
    if race == "genesis_cas":
        await seed_empty_head(sessions, first)
    tasks = []
    async with serve_governance_attestor(
        root, runtime, session_factory=sessions, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        async with sessions() as holder, holder.begin():
            if race == "same_command":
                await QualityProfileRepository(holder).lock_command(first.command)
            else:
                await holder.execute(sa.select(QualityProfileHeadModel).with_for_update())
            pid = await holder.scalar(sa.text("SELECT pg_backend_pid()"))
            assert pid is not None
            first_service = await publisher(sessions, root, runtime, first)
            tasks.append(asyncio.create_task(first_service.publish(first)))
            try:
                first_pid = (await wait_for_blockers(sessions, pid))[0]
                second_service = await publisher(sessions, root, runtime, second)
                tasks.append(asyncio.create_task(second_service.publish(second)))
                if race == "same_command":
                    assert len(await wait_for_blockers(sessions, pid, minimum=2)) >= 2
                else:
                    assert await wait_for_blockers(sessions, first_pid)
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert not isinstance(results[0], BaseException)
    assert results[0].revision == 1
    if race == "same_command":
        assert results[0] == results[1]
    else:
        assert isinstance(results[1], StaleHeadError)
    async with sessions() as probe:
        for model in [QualityProfileRevisionModel, QualityCommandModel, QualityOutboxModel]:
            assert (await probe.execute(sa.select(sa.func.count()).select_from(model))).scalar_one() == 1
        assert (await probe.execute(sa.select(QualityProfileHeadModel.current_revision))).scalar_one() == 1


async def test_lease_expiring_behind_held_profile_lock_uses_final_database_time(publication_host) -> None:
    import asyncio

    from r2.quality.errors import ProfilePublicationUnauthorizedError

    sessions, (root, runtime, *_rest) = publication_host
    request = publication_request(user_id="default")
    await seed_empty_head(sessions, request)
    publication = None
    async with serve_governance_attestor(
        root, runtime, session_factory=sessions, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        async with sessions() as holder, holder.begin():
            await holder.execute(sa.select(QualityProfileHeadModel).with_for_update())
            pid = await holder.scalar(sa.text("SELECT pg_backend_pid()"))
            assert pid is not None
            service = await publisher(sessions, root, runtime, request)
            publication = asyncio.create_task(service.publish(request))
            try:
                assert await wait_for_blockers(sessions, pid)
                async with sessions() as observer, asyncio.timeout(40):
                    deadline = (
                        await observer.execute(sa.select(ProfilePublicationAuthorizationModel.admit_not_after))
                    ).scalar_one()
                    while True:
                        current = await observer.scalar(sa.select(sa.func.clock_timestamp()))
                        assert current is not None
                        if current >= deadline:
                            print("M10_EXPIRED_BEHIND_LOCK", current.isoformat(), deadline.isoformat())
                            break
                        expired = asyncio.Event()
                        timer = asyncio.get_running_loop().call_later((deadline - current).total_seconds(), expired.set)
                        try:
                            await expired.wait()
                        finally:
                            timer.cancel()
            except BaseException:
                publication.cancel()
                await asyncio.gather(publication, return_exceptions=True)
                raise
        with pytest.raises(ProfilePublicationUnauthorizedError):
            await publication
    async with sessions() as observer:
        for model in [QualityProfileRevisionModel, QualityCommandModel, QualityOutboxModel]:
            assert (await observer.execute(sa.select(sa.func.count()).select_from(model))).scalar_one() == 0


async def test_session_token_is_absent_from_all_durable_json_and_master_locks(publication_host) -> None:
    import json

    sessions, (root, runtime, *_rest) = publication_host
    request = publication_request(user_id="default")
    token = auth.create_token("actor")
    engine = sessions.kw["bind"].sync_engine
    queries = []

    def observe_driver(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement.lower())

    sa.event.listen(engine, "before_cursor_execute", observe_driver)
    try:
        async with serve_governance_attestor(
            root, runtime, session_factory=sessions, expected_uid=os.getuid(), expected_gid=os.getgid()
        ):
            profile = await (await publisher(sessions, root, runtime, request, token=token)).publish(request)
        assert profile.revision == 1
    finally:
        sa.event.remove(engine, "before_cursor_execute", observe_driver)
    assert not any("for update" in query and ("master" in query or "disposition" in query) for query in queries)
    async with sessions() as session:
        for column in [
            ProfilePublicationAuthorizationModel.request_json,
            ProfilePublicationAuthorizationModel.lease_json,
            QualityProfileRevisionModel.body_json,
            QualityCommandModel.receipt_json,
            QualityOutboxModel.event_json,
        ]:
            bodies = (await session.execute(sa.select(column))).scalars().all()
            assert len(bodies) == 1
            assert token not in json.dumps(bodies)
