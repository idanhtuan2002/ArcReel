"""The autopilot decides a project's next run from durable state only (ADR-0124)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from tests.integration.lib.db.repositories.test_production_runs import policy

DIGEST = "sha256:" + "c" * 64


def _delegation(kind: str = "story", *, state: str = "ENABLED", project: str = "project"):
    from r2.automation.identity import policy_digest
    from r2.contracts.automation import AutomationMode
    from r2.contracts.autopilot import AutopilotDelegation, FilmAutopilot, StoryAutopilot

    return AutopilotDelegation(
        user_id="default",
        project_name=project,
        version=1,
        state=state,
        kind=kind,
        issuer_id="actor",
        command_id="enable-1",
        parent_sequence=1,
        parent_event_digest="sha256:" + "a" * 64,
        mode=AutomationMode.AUTO,
        policy_digest=policy_digest(policy()),
        story=StoryAutopilot(idea="Chuyến đò cuối.", book_chapters=12) if kind == "story" else None,
        film=FilmAutopilot(episodes_per_run=2) if kind == "film" else None,
        created_at=datetime(2026, 11, 10, tzinfo=UTC),
    )


class _Service:
    def __init__(self, *, story: bool = True) -> None:
        self.started: list = []
        self._story = story

    async def start_delegated(self, *, delegation, command):
        self.started.append(command)
        return command

    async def input_digest(self, *, user_id: str, project_name: str) -> str:
        return DIGEST

    async def has_story(self, project_name: str) -> bool:
        return self._story


def _planner(sessions, service, *, parts=None, episodes=(), unplanned=False, conflicts=(), link="story-a"):
    from server.production_run.autopilot import AutopilotPlanner

    async def book_parts(user_id, project_name):
        return parts

    async def sync_story(user_id, project_name):
        return list(conflicts)

    async def max_targets(delegation):
        return 4

    project = {"project_kind": "film", "story_project": link, "episodes": [{"episode": n} for n in episodes]}
    return AutopilotPlanner(
        sessions,
        service,
        load_project=lambda name: project,
        book_parts=book_parts,
        unplanned_source=lambda name: unplanned,
        sync_story=sync_story,
        max_targets=max_targets,
    )


async def _run(sessions, command_id: str, *, status: str, targets: tuple[str, ...] = ("episode:1",)):
    from lib.db.models.production_run import ProductionRunModel
    from lib.db.repositories.production_runs import ProductionRunRepository
    from r2.automation.identity import policy_digest
    from r2.contracts.automation import OwnerReceipt, RunCommand, RunSnapshot, TargetOutput

    async with sessions() as session, session.begin():
        run = await ProductionRunRepository(session).create(
            command=RunCommand(
                user_id="default",
                project_name="project",
                command_id=command_id,
                action="START",
                expected_version=0,
                expected_input_digest=DIGEST,
                policy_digest=policy_digest(policy()),
                story_source="project",
                targets=targets,
            ),
            policy=policy(),
        )
        receipt = OwnerReceipt(owner="o", receipt_ref="r", digest=DIGEST)
        outputs = tuple(
            TargetOutput(
                target=target,
                generation=1,
                input_digest=DIGEST,
                policy_digest=policy_digest(policy()),
                master_digest=DIGEST,
                quality_run=receipt,
                quality_decision="PASS",
                export=receipt,
                final_digest=DIGEST,
                archive_digest=DIGEST,
                archive_size=1,
                verified=True,
            )
            for target in targets
        )
        updated = RunSnapshot.model_validate(
            {
                **run.model_dump(mode="python"),
                "status": status,
                "completed_targets": outputs if status == "SUCCEEDED" else (),
            }
        )
        await session.execute(
            sa.update(ProductionRunModel)
            .where(ProductionRunModel.run_id == run.run_id)
            .values(status=status, snapshot_json=updated.model_dump_json())
        )
        return updated


async def test_story_part_one_then_continuations_then_finished(session_factory):
    from r2.contracts.autopilot import autopilot_command_id
    from server.production_run.autopilot import BookParts

    delegation = _delegation()
    service = _Service()
    state, command = await _planner(session_factory, service).state(delegation)
    assert state.state == "ready"
    assert command is not None
    assert (command.story_source, command.idea, command.book_chapters, command.end_stage) == (
        "idea",
        "Chuyến đò cuối.",
        12,
        "HANDOFF",
    )
    assert command.command_id == autopilot_command_id(delegation, 1)

    await _run(session_factory, autopilot_command_id(delegation, 1), status="SUCCEEDED")
    state, command = await _planner(session_factory, service, parts=BookParts(done=1, total=3)).state(delegation)
    assert command is not None
    assert (command.story_source, command.end_stage, command.book_chapters) == ("continue", "HANDOFF", None)
    assert command.command_id == autopilot_command_id(delegation, 2)

    state, command = await _planner(session_factory, service, parts=BookParts(done=3, total=3)).state(delegation)
    assert (state.state, command) == ("finished", None)
    # A succeeded part that left no book is not written again.
    state, command = await _planner(session_factory, service, parts=None).state(delegation)
    assert (state.state, command) == ("finished", None)


@pytest.mark.parametrize("status", ["FAILED_QUALITY", "CANCELLED", "BLOCKED_BUDGET"])
async def test_a_project_halts_on_its_own_unsucceeded_run_and_waits_on_an_active_one(session_factory, status):
    from r2.contracts.autopilot import autopilot_command_id

    delegation = _delegation()
    run = await _run(session_factory, autopilot_command_id(delegation, 1), status=status)
    state, command = await _planner(session_factory, _Service()).state(delegation)
    expected = "waiting" if status == "BLOCKED_BUDGET" else "halted"
    assert (state.state, state.run_id, command) == (expected, run.run_id, None)


async def test_another_delegations_failed_run_does_not_halt(session_factory):
    from r2.contracts.autopilot import autopilot_command_id

    await _run(session_factory, autopilot_command_id(_delegation(project="other"), 1), status="FAILED")
    await _run(session_factory, "manual-start", status="CANCELLED")
    state, _command = await _planner(session_factory, _Service()).state(_delegation())
    assert state.state == "ready"


async def test_disabled_delegation_is_off(session_factory):
    state, command = await _planner(session_factory, _Service()).state(_delegation(state="DISABLED"))
    assert (state.state, command) == ("off", None)


async def test_film_targets_unfilmed_planned_episodes_then_unplanned_source(session_factory):
    delegation = _delegation("film")
    await _run(session_factory, "manual-start", status="SUCCEEDED", targets=("episode:1",))
    service = _Service()
    _state, command = await _planner(session_factory, service, episodes=(1, 2, 3, 4)).state(delegation)
    assert command is not None
    assert (command.story_source, command.targets, command.idea) == ("project", ("episode:2", "episode:3"), None)

    _state, command = await _planner(session_factory, service, episodes=(1,), unplanned=True).state(delegation)
    assert command is not None
    assert command.targets == ("episode:2",)

    state, command = await _planner(session_factory, service, episodes=(1,), unplanned=False).state(delegation)
    assert (state.state, command) == ("finished", None)


async def test_film_without_a_story_waits_and_a_sync_conflict_halts(session_factory):
    delegation = _delegation("film")
    state, command = await _planner(session_factory, _Service(story=False)).state(delegation)
    assert (state.state, command) == ("finished", None)
    state, command = await _planner(session_factory, _Service(), conflicts=("part-2.txt",)).state(delegation)
    assert (state.state, state.reason, command) == ("halted", "STORY_SYNC_CONFLICT", None)


async def test_scheduler_starts_ready_projects_only(session_factory):
    from lib.db.repositories.autopilot import AutopilotRepository
    from server.production_run.autopilot import AutopilotScheduler

    enabled, disabled = _delegation(), _delegation(project="quiet", state="DISABLED")
    async with session_factory() as session, session.begin():
        repository = AutopilotRepository(session)
        await repository.append(enabled, previous=None)
        await repository.append(disabled, previous=None)
        assert await repository.enabled(limit=10) == [enabled]
    service = _Service()
    scheduler = AutopilotScheduler(session_factory, service, _planner(session_factory, service), page_size=1)
    assert await scheduler.scan_once() == 1
    assert [command.project_name for command in service.started] == ["project"]
