"""Media stage over a scripted workflow planner, real write-ahead attempts and real run delegation."""

from __future__ import annotations

import asyncio
import json
import os
import random
from pathlib import Path

import pytest
from PIL import Image

from lib.db.repositories.production_runs import ProductionRunRepository
from lib.project_manager import ProjectManager
from lib.workflow_plan import WorkflowNarrationDelivery, WorkflowPlan
from lib.workflow_state import WorkflowActionType, WorkflowNextAction, WorkflowProject, WorkflowStatus, WorkflowTarget
from r2.automation.assessment import AssessmentFinding, ModelAssessment
from r2.contracts.automation import ModelRoute, RunStage, RunStatus
from server.production_run.controller import ProductionController
from server.production_run.image_judge import Choice
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


def _storyboard(path: Path, *, blank: bool) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if blank:
        Image.new("RGB", (576, 1024), (0, 0, 0)).save(path)
    else:
        rng = random.Random(3)
        image = Image.new("RGB", (576, 1024))
        image.putdata([(rng.randrange(256),) * 3 for _ in range(576 * 1024)])
        image.save(path)
    return path.name


def _script_with_storyboards(script: Path, *, blank: set[str], clips: set[str] = frozenset()) -> None:
    root = script.parent.parent
    segments = []
    for unit in ("E1S01", "E1S02"):
        _storyboard(root / "storyboards" / f"scene_{unit}.png", blank=unit in blank)
        assets = {"storyboard_image": f"storyboards/scene_{unit}.png"}
        if unit in clips:
            clip = root / "videos" / f"scene_{unit}.mp4"
            clip.parent.mkdir(parents=True, exist_ok=True)
            clip.write_bytes(b"clip")
            assets["video_clip"] = f"videos/scene_{unit}.mp4"
        segments.append({"segment_id": unit, "novel_text": unit, "generated_assets": assets})
    script.write_text(json.dumps({"episode": 1, "content_mode": "narration", "segments": segments}), encoding="utf-8")


def _storyboards_made() -> dict:
    return {"storyboards": {"current_ids": ["E1S01", "E1S02"], "missing_ids": [], "stale_ids": []}}


async def test_a_blank_storyboard_is_made_again_before_the_next_action(media_host):
    sessions, controller, run, planner, tools, script = media_host
    _script_with_storyboards(script, blank={"E1S02"})
    planner.plans = [_plan(A.GENERATE_TTS, artifacts=_storyboards_made())]

    waiting = await _tick(sessions, controller, run)

    assert waiting.status is RunStatus.WAITING_TASK
    assert tools.calls == [(A.GENERATE_STORYBOARDS, {"script": "episode_1.json", "segment_ids": ["E1S02"]})]


async def test_a_storyboard_that_keeps_failing_its_check_blocks_after_two_regenerations(media_host):
    sessions, controller, run, planner, tools, script = media_host
    _script_with_storyboards(script, blank={"E1S02"})
    planner.plans = [_plan(A.GENERATE_TTS, artifacts=_storyboards_made())]

    await _tick(sessions, controller, run)
    await _tick(sessions, controller, run)
    blocked = await _tick(sessions, controller, run)

    assert (blocked.status, blocked.reason) == (RunStatus.BLOCKED_CONFIGURATION, "MEDIA_IMAGE_CHECK_FAILED")
    assert [action for action, _ in tools.calls] == [A.GENERATE_STORYBOARDS] * 2


async def test_a_storyboard_made_again_also_remakes_its_older_clip_then_planning_continues(media_host):
    sessions, controller, run, planner, tools, script = media_host
    _script_with_storyboards(script, blank={"E1S02"}, clips={"E1S01", "E1S02"})
    planner.plans = [_plan(A.GENERATE_TTS, artifacts=_storyboards_made())]
    await _tick(sessions, controller, run)
    # The regenerated storyboard is newer than the clip made from the blank one.
    clip = script.parent.parent / "videos" / "scene_E1S02.mp4"
    _storyboard(script.parent.parent / "storyboards" / "scene_E1S02.png", blank=False)
    os.utime(clip, ns=(1, 1))

    await _tick(sessions, controller, run)
    os.utime(clip, None)
    await _tick(sessions, controller, run)

    assert tools.calls[1:] == [
        (
            A.GENERATE_VIDEOS,
            {
                "script": "episode_1.json",
                "target": {"scope": "selected", "ids": ["E1S02"]},
                "narration_delivery": "use_tts",
                "force": True,
            },
        ),
        (A.GENERATE_TTS, {"script": "episode_1.json"}),
    ]


def _review(identity: str, *, accepted: bool, segments: list[str]) -> ModelAssessment:
    score = 5 if accepted else 2
    return ModelAssessment.model_validate(
        {
            "reviewer_route_digest": "sha256:" + "1" * 64,
            "model_identity": identity,
            "prompt_digest": "sha256:" + "1" * 64,
            "subject_digest": "sha256:" + "1" * 64,
            "evidence_digest": "sha256:" + "1" * 64,
            "outcome": "COMPLETED",
            "language": "vi",
            "scores": {"story": 5, "visual": score, "audio": 5, "continuity": 5, "pacing": 5},
            "findings": [
                AssessmentFinding(
                    code="FRAME_NOT_ILLUSTRATING_NARRATION",
                    severity="CRITICAL",
                    unit_key=f"episode:1:segment:{unit}",
                    repair_stage=RunStage.MEDIA,
                    detail="2 frames",
                )
                for unit in segments
            ]
            + [AssessmentFinding(code="PACING", severity="MAJOR", unit_key="episode:1", repair_stage=RunStage.MEDIA)],
        }
    )


async def _second_generation(sessions, run, script, *, accepted: tuple[bool, bool]):
    """The run back at MEDIA as generation 2, with the reviews generation 1's final drew."""
    async with sessions() as session, session.begin():
        repository = ProductionRunRepository(session)
        current = await repository.claim_due(owner_id="controller", lease_seconds=120)
        assert current is not None
        await repository.transition(
            expected=current,
            updated=current.model_copy(update={"generation": 2, "version": current.version + 1}),
            fencing_epoch=current.fencing_epoch,
        )
    folder = script.parent.parent / "production" / "automation" / run.run_id / "g1" / "episode_1" / "quality"
    folder.mkdir(parents=True)
    reviews = (("reviewer_a", ["E1S02"]), ("reviewer_b", ["E1S02", "E1S01"]))
    for (role, segments), ok in zip(reviews, accepted, strict=True):
        review = _review(f"model-{role}", accepted=ok, segments=[] if ok else segments)
        (folder / f"subject.{role}.json").write_text(review.model_dump_json(), encoding="utf-8")


async def test_an_automatic_rework_makes_the_named_segments_again_then_their_clips(media_host):
    sessions, controller, run, planner, tools, script = media_host
    _script_with_storyboards(script, blank=set(), clips={"E1S01", "E1S02"})
    await _second_generation(sessions, run, script, accepted=(False, False))
    planner.plans = [_plan(A.EXPORT, artifacts=_storyboards_made())]

    first = await _tick(sessions, controller, run)
    # The storyboards were made again: newer than the clips made from the rejected ones.
    for unit in ("E1S01", "E1S02"):
        os.utime(script.parent.parent / "videos" / f"scene_{unit}.mp4", ns=(1, 1))
    second = await _tick(sessions, controller, run)

    assert (first.status, second.status) == (RunStatus.WAITING_TASK, RunStatus.WAITING_TASK)
    assert tools.calls == [
        (A.GENERATE_STORYBOARDS, {"script": "episode_1.json", "segment_ids": ["E1S01", "E1S02"]}),
        (
            A.GENERATE_VIDEOS,
            {
                "script": "episode_1.json",
                "target": {"scope": "selected", "ids": ["E1S01", "E1S02"]},
                "narration_delivery": "use_tts",
                "force": True,
            },
        ),
    ]


async def test_a_human_rework_after_accepting_reviews_regenerates_nothing_on_its_own(media_host):
    sessions, controller, run, planner, tools, script = media_host
    _script_with_storyboards(script, blank=set(), clips={"E1S01", "E1S02"})
    await _second_generation(sessions, run, script, accepted=(True, True))
    planner.plans = [_plan(A.EXPORT, artifacts=_storyboards_made())]

    passed = await _tick(sessions, controller, run)

    assert (passed.stage, passed.status) == (RunStage.RENDER, RunStatus.RUNNING)
    assert tools.calls == []


class Judge:
    """A ranking judge that prefers each segment's listed candidate index."""

    def __init__(self, prefer: dict[str, int]) -> None:
        self.prefer, self.calls = prefer, []

    async def choose(self, route, line, pictures):
        self.calls.append((route.role, line, len(pictures)))
        index = self.prefer[line]
        return Choice(index=index, rounds=[{"between": [0, 1], "answers": ["A", "B"], "later_wins": bool(index)}])


def _two_versions(script: Path) -> None:
    root = script.parent.parent
    versions: dict[str, dict] = {}
    for unit in ("E1S01", "E1S02"):
        files = []
        for version in (1, 2):
            name = f"versions/storyboards/{unit}_v{version}.png"
            _storyboard(root / name, blank=False)
            files.append({"version": version, "file": name, "prompt": "p", "created_at": "2026-11-08T00:00:00Z"})
        versions[unit] = {"current_version": 2, "versions": files}
    (root / "versions" / "versions.json").write_text(json.dumps({"storyboards": versions}), encoding="utf-8")


async def test_extra_storyboard_versions_are_made_judged_and_the_winner_restored(media_host, monkeypatch):
    sessions, controller, run, planner, tools, script = media_host
    _script_with_storyboards(script, blank=set())
    adapter = controller._adapters[RunStage.MEDIA]
    judge, restored = Judge({"E1S01": 0, "E1S02": 1}), []

    async def restore(project, resource_type, unit, version):
        restored.append((resource_type, unit, version))

    adapter._judge_client, adapter._restore = judge, restore
    judge_route = ModelRoute.model_validate(
        {
            "role": "reviewer_a",
            "provider_id": "custom-1",
            "model_id": "judge",
            "model_identity": "ollama/judge@sha256:" + "2" * 64,
            "config_digest": "sha256:" + "2" * 64,
            "local": True,
            "paid": False,
            "currency": "USD",
            "max_cost_per_call": None,
        }
    )
    real_run = adapter._run

    async def selecting_run(intent):
        snapshot = await real_run(intent)
        policy = snapshot.policy.model_copy(
            update={
                "image_candidates": 2,
                "image_judge_identity": judge_route.model_identity,
                "image_judge_prompt_digest": "sha256:" + "3" * 64,
                "routes": (judge_route,),
            }
        )
        return snapshot.model_copy(update={"policy": policy})

    monkeypatch.setattr(adapter, "_run", selecting_run)
    planned = json.loads(script.read_text(encoding="utf-8"))
    for item in planned["segments"]:
        item["novel_text"] = item["segment_id"]
    script.write_text(json.dumps(planned), encoding="utf-8")
    planner.plans = [_plan(A.GENERATE_TTS, artifacts=_storyboards_made())]

    extra = await _tick(sessions, controller, run)
    _two_versions(script)
    started = await _tick(sessions, controller, run)
    await asyncio.sleep(0.05)
    chosen = await _tick(sessions, controller, run)
    continued = await _tick(sessions, controller, run)

    assert [s.status for s in (extra, started, chosen, continued)] == [RunStatus.WAITING_TASK] * 4
    assert tools.calls == [
        (A.GENERATE_STORYBOARDS, {"script": "episode_1.json", "segment_ids": ["E1S01", "E1S02"]}),
        (A.GENERATE_TTS, {"script": "episode_1.json"}),
    ]
    assert judge.calls == [("reviewer_a", "E1S01", 2), ("reviewer_a", "E1S02", 2)]
    assert restored == [("storyboards", "E1S01", 1)]
    evidence = json.loads(
        (
            script.parent.parent
            / "production"
            / "automation"
            / run.run_id
            / "g1"
            / "episode_1"
            / "image_selection.json"
        ).read_text(encoding="utf-8")
    )
    assert evidence["segments"]["E1S01"] | {"rounds": None} == {
        "candidates": [1, 2],
        "chosen_version": 1,
        "restored": True,
        "rounds": None,
    }
    assert evidence["segments"]["E1S02"]["restored"] is False
