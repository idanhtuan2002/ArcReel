"""Media stage over a scripted workflow planner, real write-ahead attempts and real run delegation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.db.repositories.production_runs import ProductionRunRepository
from lib.project_manager import ProjectManager
from lib.workflow_plan import WorkflowNarrationDelivery, WorkflowPlan
from lib.workflow_state import WorkflowActionType, WorkflowNextAction, WorkflowProject, WorkflowStatus, WorkflowTarget
from r2.contracts.automation import RunStage, RunStatus
from server.production_run.controller import ProductionController
from server.production_run.media_adapter import MediaAdapter
from server.tool_runtime import ToolOutcome, ToolProblem
from tests.integration.server.production_run.test_render_master_adapter import RunInput
from tests.integration.server.services.test_automation_grants import delegated_host as delegated_host
from tests.integration.server.services.test_automation_grants import interactive_env as interactive_env

A = WorkflowActionType


def _plan(
    action: WorkflowActionType,
    ids: list[str] | None = None,
    *,
    sheets: dict[str, list[str]] | None = None,
    args: dict | None = None,
    artifacts: dict | None = None,
) -> WorkflowPlan:
    status = WorkflowStatus.model_construct(
        project_revision="r",
        source_revision=None,
        project=WorkflowProject(content_mode="narration", generation_mode="storyboard", grid_storyboard=False),
        target=WorkflowTarget(episode=1, script="scripts/episode_1.json", script_filename="episode_1.json", source="s"),
        state="VIDEO",
        blockers=[],
        gates={},
        artifacts={
            "videos": {"state": "current"},
            "asset_sheets": {kind: {"missing_ids": names} for kind, names in (sheets or {}).items()},
            **(artifacts or {}),
        },
        next_action=WorkflowNextAction(type=action, reason="test"),
    )
    return WorkflowPlan.model_construct(
        status=status,
        narration_delivery=WorkflowNarrationDelivery(selected="use_tts"),
        steps=[],
        blockers=[],
        problems=[],
        next_action=WorkflowNextAction(type=action, requested_ids=ids or [], args=args or {}, reason="test"),
    )


class Planner:
    def __init__(self) -> None:
        self.plans = [_plan(A.GENERATE_STORYBOARDS)]
        self.requests = []

    async def get_plan(self, project_name, request, **kwargs):
        self.requests.append(request)
        return self.plans[0] if len(self.plans) == 1 else self.plans.pop(0)


class Tools:
    def __init__(self) -> None:
        self.calls: list[tuple[WorkflowActionType, dict]] = []
        self.problem: ToolProblem | None = None

    def handler(self, action: WorkflowActionType):
        async def call(ctx, args):
            self.calls.append((action, args))
            assert ctx.caller.source == "mcp"
            return ToolOutcome(problem=self.problem) if self.problem else ToolOutcome(value={"batch": "b"})

        return call


@pytest.fixture
async def media_host(delegated_host, tmp_path: Path):
    issuer, sessions, _request, _grant, run, *_ = delegated_host
    projects = ProjectManager(tmp_path / "projects")
    script = tmp_path / "projects" / run.project_name / "scripts" / "episode_1.json"
    script.parent.mkdir(parents=True)
    script.write_text(json.dumps({"episode": 1, "segments": []}), encoding="utf-8")
    async with sessions() as session, session.begin():
        moved = run.model_copy(update={"stage": RunStage.MEDIA, "version": run.version + 1})
        await ProductionRunRepository(session).transition(expected=run, updated=moved, fencing_epoch=run.fencing_epoch)
    planner, tools = Planner(), Tools()
    adapter = MediaAdapter(
        sessions,
        authority=issuer.authority(),
        projects=projects,
        resolver=None,
        planner=planner,
        queue=None,
        tools={
            action: tools.handler(action)
            for action in (
                A.GENERATE_ASSET_SHEETS,
                A.GENERATE_STORYBOARDS,
                A.GENERATE_TTS,
                A.REGENERATE_TTS,
                A.GENERATE_VIDEOS,
            )
        },
    )
    adapter.calls_per_target, adapter.seconds_per_target = 1, 10  # the fixture policy has tiny caps
    controller = ProductionController(
        sessions, adapters={RunStage.MEDIA: adapter}, witness=RunInput(run.input_digest), poll_seconds=0
    )
    return sessions, controller, run, planner, tools, script


async def _tick(sessions, controller, run):
    async with sessions() as session, session.begin():
        claimed = await ProductionRunRepository(session).claim_due(owner_id="controller", lease_seconds=120)
    assert claimed is not None
    return await controller.tick(run_id=run.run_id, owner_id="controller")


async def test_an_owner_action_is_retried_at_most_twice_then_blocks(media_host):
    sessions, controller, run, planner, tools, _ = media_host

    first = await _tick(sessions, controller, run)
    second = await _tick(sessions, controller, run)
    blocked = await _tick(sessions, controller, run)

    assert (first.status, second.status) == (RunStatus.WAITING_TASK, RunStatus.WAITING_TASK)
    assert (blocked.status, blocked.reason) == (RunStatus.BLOCKED_CONFIGURATION, "MEDIA_RETRY_LIMIT")
    assert tools.calls == [(A.GENERATE_STORYBOARDS, {"script": "episode_1.json"})] * 2
    assert {request.narration_delivery for request in planner.requests} == {"use_tts"}


async def test_active_tasks_wait_and_export_passes_with_media_evidence(media_host):
    sessions, controller, run, planner, tools, _ = media_host
    planner.plans = [_plan(A.WAIT_FOR_TASK), _plan(A.WAIT_FOR_TASK), _plan(A.EXPORT)]

    waiting = await _tick(sessions, controller, run)
    passed = await _tick(sessions, controller, run)

    assert waiting.status is RunStatus.WAITING_TASK
    assert (passed.stage, passed.status) == (RunStage.RENDER, RunStatus.RUNNING)
    assert tools.calls == []
    async with sessions() as session:
        outcome = await ProductionRunRepository(session).stage_outcome(run=passed, stage=RunStage.MEDIA)
    assert outcome is not None
    assert outcome.receipts[0].receipt_ref.startswith("episode:1:media@")


@pytest.mark.parametrize(
    ("action", "reason"),
    [
        (A.GENERATE_SCRIPT, "EXTERNAL_INPUT_CHANGED"),
        (A.REPAIR_VIDEO_UNITS, "WORKFLOW_REPAIR_VIDEO_UNITS"),
        (A.CONFIRM_REQUEST_DURATION, "WORKFLOW_CONFIRM_REQUEST_DURATION"),
        (A.CONFIGURE_PROVIDER, "WORKFLOW_CONFIGURE_PROVIDER"),
    ],
)
async def test_actions_that_need_a_human_or_upstream_change_never_run(media_host, action, reason):
    sessions, controller, run, planner, tools, _ = media_host
    planner.plans = [_plan(action)]

    blocked = await _tick(sessions, controller, run)

    assert blocked.reason == reason
    assert tools.calls == []


async def test_a_changed_script_blocks_the_media_stage(media_host):
    sessions, controller, run, planner, _tools, script = media_host
    planner.plans = [_plan(A.WAIT_FOR_TASK)]
    await _tick(sessions, controller, run)
    script.write_text(json.dumps({"episode": 1, "segments": [{"segment_id": "E1S09"}]}), encoding="utf-8")

    blocked = await _tick(sessions, controller, run)

    assert (blocked.status, blocked.reason) == (RunStatus.BLOCKED_INPUT_CHANGED, "EXTERNAL_INPUT_CHANGED")


async def test_requests_follow_the_agent_tool_contracts(media_host):
    sessions, controller, run, planner, tools, _ = media_host
    planner.plans = [
        _plan(A.GENERATE_ASSET_SHEETS, ["Lan", "Làng", "Mai"], sheets={"character": ["Mai", "Lan"], "scene": ["Làng"]})
    ]
    await _tick(sessions, controller, run)
    planner.plans = [_plan(A.GENERATE_VIDEOS)]
    await _tick(sessions, controller, run)
    planner.plans = [_plan(A.GENERATE_VIDEOS, ["E1S02"])]
    await _tick(sessions, controller, run)

    assert tools.calls == [
        (A.GENERATE_ASSET_SHEETS, {"type": "character", "names": ["Lan", "Mai"]}),
        (A.GENERATE_ASSET_SHEETS, {"type": "scene", "names": ["Làng"]}),
        (
            A.GENERATE_VIDEOS,
            {"script": "episode_1.json", "target": {"scope": "episode", "episode": 1}, "narration_delivery": "use_tts"},
        ),
        (
            A.GENERATE_VIDEOS,
            {
                "script": "episode_1.json",
                "target": {"scope": "selected", "ids": ["E1S02"]},
                "narration_delivery": "use_tts",
                "force": True,
            },
        ),
    ]


async def test_a_refused_tool_call_blocks_with_its_code(media_host):
    sessions, controller, run, _planner, tools, _ = media_host
    tools.problem = ToolProblem("worker_offline", "no worker")

    blocked = await _tick(sessions, controller, run)

    assert blocked.reason == "MEDIA_WORKER_OFFLINE"


def test_an_asset_name_no_sheet_type_lists_blocks_the_media_step():
    from server.production_run.media_adapter import MediaAdapter
    from server.production_run.owner_support import OwnerBlocked

    plan = _plan(A.GENERATE_ASSET_SHEETS, ["Lan", "Ghost"], sheets={"character": ["Lan"]})

    with pytest.raises(OwnerBlocked, match="MEDIA_ASSET_TYPE_UNKNOWN"):
        MediaAdapter._requests(plan, "episode_1.json")


async def test_a_proposed_duration_tier_is_confirmed_and_sent_with_the_videos(media_host):
    sessions, controller, run, planner, tools, _ = media_host
    unit = {
        "unit_id": "E1S01",
        "request_duration_seconds": 8,
        "problems": [{"code": "reference_duration_confirmation_required", "action": "confirm_request_duration"}],
    }
    confirm = _plan(A.CONFIRM_REQUEST_DURATION, ["E1S01"], args={"admission": {"units": [unit]}})
    planner.plans = [confirm, confirm, _plan(A.GENERATE_VIDEOS, ["E1S01"])]

    await _tick(sessions, controller, run)

    assert [r.confirmed_request_durations for r in planner.requests][-2:] == [{}, {"E1S01": 8}]
    assert tools.calls[-1] == (
        A.GENERATE_VIDEOS,
        {
            "script": "episode_1.json",
            "target": {"scope": "selected", "ids": ["E1S01"]},
            "narration_delivery": "use_tts",
            "force": True,
            "confirmed_request_durations": {"E1S01": 8},
        },
    )


def _episode_media(*, missing_video: bool = False) -> dict:
    done = {"current_ids": ["E1S01"], "missing_ids": [], "stale_ids": []}
    return {
        "script": {"state": "current"},
        "storyboards": done,
        "videos": {**done, "missing_ids": ["E1S02"]} if missing_video else done,
        "audio": done,
    }


async def test_a_complete_target_episode_passes_while_more_episodes_await_planning(media_host):
    sessions, controller, run, planner, tools, _ = media_host
    planner.plans = [_plan(A.PLAN_EPISODES, artifacts=_episode_media())]

    passed = await _tick(sessions, controller, run)

    assert (passed.stage, passed.status) == (RunStage.RENDER, RunStatus.RUNNING)
    assert tools.calls == []


async def test_planning_more_episodes_before_the_target_is_complete_is_an_input_change(media_host):
    sessions, controller, run, planner, _, _ = media_host
    planner.plans = [_plan(A.PLAN_EPISODES, artifacts=_episode_media(missing_video=True))]

    blocked = await _tick(sessions, controller, run)

    assert (blocked.status, blocked.reason) == (RunStatus.BLOCKED_INPUT_CHANGED, "EXTERNAL_INPUT_CHANGED")
