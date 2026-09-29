"""Portfolio admission filters in TaskRepository.claim_next (ADR-0094): pause and per-project ceiling."""

from __future__ import annotations

from lib.db.repositories.task_repo import TaskRepository


async def _enqueue(repo: TaskRepository, project: str, resource: str, **kwargs) -> str:
    task = await repo.enqueue(
        project_name=project,
        task_type="storyboard",
        media_type="image",
        resource_id=resource,
        payload={},
        script_file="ep1.json",
        **kwargs,
    )
    return task["task_id"]


class TestProjectAdmission:
    async def test_a_paused_project_is_skipped_until_it_is_resumed(self, db_session):
        repo = TaskRepository(db_session)
        paused_task = await _enqueue(repo, "paused-project", "E1S01")
        other_task = await _enqueue(repo, "other-project", "E1S01")

        first = await repo.claim_next("image", paused_projects=frozenset({"paused-project"}))
        second = await repo.claim_next("image", paused_projects=frozenset({"paused-project"}))
        resumed = await repo.claim_next("image")

        assert first is not None
        assert first["task_id"] == other_task
        assert second is None
        assert resumed is not None
        assert resumed["task_id"] == paused_task

    async def test_a_project_at_its_ceiling_does_not_block_a_later_project(self, db_session):
        repo = TaskRepository(db_session)
        busy_1 = await _enqueue(repo, "busy", "E1S01")
        busy_2 = await _enqueue(repo, "busy", "E1S02")
        later = await _enqueue(repo, "later", "E1S01")

        first = await repo.claim_next("image", project_running_ceiling=1)
        second = await repo.claim_next("image", project_running_ceiling=1)
        third = await repo.claim_next("image", project_running_ceiling=1)

        assert [first["task_id"], second["task_id"]] == [busy_1, later]
        assert third is None
        assert (await repo.get(busy_2))["status"] == "queued"

    async def test_the_ceiling_counts_persisted_running_rows_after_a_restart(self, db_session):
        repo = TaskRepository(db_session)
        await _enqueue(repo, "busy", "E1S01")
        waiting = await _enqueue(repo, "busy", "E1S02")
        await repo.claim_next("image")

        restarted = TaskRepository(db_session)
        blocked = await restarted.claim_next("image", project_running_ceiling=1)
        admitted = await restarted.claim_next("image", project_running_ceiling=2)

        assert blocked is None
        assert admitted is not None
        assert admitted["task_id"] == waiting

    async def test_dependencies_are_still_honoured_under_admission(self, db_session):
        repo = TaskRepository(db_session)
        parent = await _enqueue(repo, "demo", "E1S01")
        child = await repo.enqueue(
            project_name="demo",
            task_type="video",
            media_type="video",
            resource_id="E1S01",
            payload={},
            script_file="ep1.json",
            dependency_task_id=parent,
        )

        assert await repo.claim_next("video", project_running_ceiling=5, paused_projects=frozenset()) is None
        assert child["status"] == "queued"


class TestAdmissionSettings:
    async def test_pause_and_ceiling_round_trip_through_the_settings_store(self, db_session):
        from lib.project_admission import load_project_admission, set_project_ceiling, set_project_paused

        await set_project_paused(db_session, "a", paused=True)
        await set_project_paused(db_session, "b", paused=True)
        await set_project_paused(db_session, "a", paused=False)
        await set_project_ceiling(db_session, 3)

        admission = await load_project_admission(db_session)

        assert admission.paused == frozenset({"b"})
        assert admission.ceiling == 3


class TestConcurrentAdmission:
    async def test_a_claim_of_another_task_waits_for_an_uncommitted_claim_of_the_same_project(self, session_factory):
        """Claimer A has set its task running but not committed yet; claimer B skips A's task (as a
        full provider pool would) and must not see room under the ceiling for a second one."""
        import asyncio

        import pytest

        async with session_factory() as session:
            if session.bind.dialect.name != "postgresql":
                pytest.skip("concurrent read-committed claims need PostgreSQL")
            repo = TaskRepository(session)
            first = await _enqueue(repo, "busy", "E1S01")
            await _enqueue(repo, "busy", "E1S02")
            await session.commit()

        release_a = asyncio.Event()
        a_updated = asyncio.Event()

        async def claim_a():
            async with session_factory() as session_a:
                real_commit = session_a.commit

                async def held_commit():
                    a_updated.set()
                    await release_a.wait()
                    await real_commit()

                session_a.commit = held_commit
                return await TaskRepository(session_a).claim_next("image", project_running_ceiling=1)

        async def claim_b():
            async with session_factory() as session_b:
                return await TaskRepository(session_b).claim_next(
                    "image", project_running_ceiling=1, exclude_task_ids=frozenset({first})
                )

        a = asyncio.create_task(claim_a())
        await asyncio.wait_for(a_updated.wait(), timeout=10)
        b = asyncio.create_task(claim_b())
        await asyncio.sleep(0.5)
        release_a.set()
        claimed_a = await asyncio.wait_for(a, timeout=10)
        claimed_b = await asyncio.wait_for(b, timeout=10)

        assert claimed_a is not None
        assert claimed_b is None
