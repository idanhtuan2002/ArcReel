from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from lib.draft_quarantine import generated_meta
from lib.workflow_state import (
    WorkflowActionType,
    WorkflowBlocker,
    WorkflowNextAction,
    WorkflowProject,
    WorkflowStatus,
    WorkflowTarget,
)
from r2.automation.identity import derive_step_identity, policy_digest
from r2.contracts.automation import DispatchIntent, RunScope, RunSnapshot, RunStage
from server.production_run import text_adapter
from server.production_run.owner_support import OwnerBlocked
from server.production_run.text_adapter import EpisodePlanAdapter, ScriptAdapter, ScriptPlanAdapter, revision_receipt
from tests.unit.server.production_run.test_controller import _policy

REVISION = "sha256:" + "5" * 64
A = WorkflowActionType


def _status(action: WorkflowActionType, *, episode: int | None = 1, **changes: Any) -> WorkflowStatus:
    values: dict[str, Any] = {
        "project_revision": "sha256:" + "0" * 64,
        "source_revision": REVISION,
        "project": WorkflowProject(content_mode="narration", generation_mode="storyboard", grid_storyboard=False),
        "target": (
            WorkflowTarget(episode=episode, script="scripts/e.json", script_filename="e.json", source="s")
            if episode
            else None
        ),
        "state": "FINAL_SCRIPT",
        "blockers": [],
        "gates": {},
        "artifacts": {"script_plan": {"revision": "sha256:" + "7" * 64}},
        "next_action": WorkflowNextAction(type=action, reason="test"),
    }
    values.update(changes)
    return WorkflowStatus.model_construct(**values)


class Projects:
    projects_root = "/projects"

    def __init__(self) -> None:
        self.episodes: list[dict[str, Any]] = []

    def load_project(self, name: str) -> dict[str, Any]:
        return {"content_mode": "narration", "episodes": list(self.episodes)}

    def get_project_path(self, name: str):
        from pathlib import Path

        return Path("/projects") / name

    def load_script(self, name: str, filename: str) -> dict[str, Any]:
        return {"segments": []}


class Statuses:
    def __init__(self, by_episode: dict[int | None, list[WorkflowStatus]]) -> None:
        self.by_episode = by_episode

    def __call__(self, project_name: str, episode: int | None) -> WorkflowStatus:
        queue = self.by_episode[episode]
        return queue.pop(0) if len(queue) > 1 else queue[0]


class Tasks:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self.submitted: list[tuple[str, str, dict]] = []

    async def find(self, sessions, intent, sub_key):
        return self.tasks.get(sub_key)

    async def submit(
        self,
        sessions,
        authority,
        intent,
        *,
        sub_key,
        task_type,
        resource_id,
        payload,
        subject_digest,
        media_type="text",
    ):
        self.submitted.append((sub_key, task_type, payload))
        self.tasks[sub_key] = {"status": "queued"}
        return sub_key


def _run(*targets: str) -> RunSnapshot:
    return RunSnapshot.model_validate(
        {
            "user_id": "u1",
            "project_name": "film",
            "run_id": "run-1",
            "policy": _policy(max_target_episodes=4),
            "input_digest": "sha256:" + "c" * 64,
            "status": "RUNNING",
            "targets": targets,
            "created_at": datetime(2026, 11, 1, tzinfo=UTC),
        }
    )


def _intent(stage: RunStage) -> DispatchIntent:
    run = _run("episode:1")
    return DispatchIntent(
        scope=RunScope(user_id="u1", project_name="film", run_id="run-1"),
        identity=derive_step_identity(
            run_id="run-1",
            stage=stage,
            unit_key=stage.value.lower(),
            generation=1,
            input_digest=run.input_digest,
            policy_digest=policy_digest(run.policy),
            repair_index=0,
        ),
        owner="text",
        input_refs=(revision_receipt("asset-inventory", "asset-inventory", REVISION),),
        estimated_cost_minor_units=0,
        estimated_model_calls=1,
        estimated_tasks=1,
        estimated_runtime_seconds=1,
    )


@pytest.fixture
def tasks(monkeypatch) -> Tasks:
    fake = Tasks()
    monkeypatch.setattr(text_adapter, "find_task", fake.find)
    monkeypatch.setattr(text_adapter, "submit_task", fake.submit)
    return fake


class Sessions:
    """``async with sessions() as session, session.begin():`` without a database."""

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def begin(self):
        return self


def _adapter(cls, statuses: Statuses, monkeypatch, *targets: str, projects: Projects | None = None):
    async def current_run(sessions, intent):
        return _run(*(targets or ("episode:1",)))

    monkeypatch.setattr(text_adapter, "current_run", current_run)
    return cls(None, authority=None, projects=projects or Projects(), resolver=None, status=statuses)


async def test_script_stage_passes_only_when_every_target_has_moved_past_it(tasks, monkeypatch):
    statuses = Statuses({1: [_status(A.GENERATE_ASSET_SHEETS)], 2: [_status(A.GENERATE_SCRIPT, episode=2)]})
    adapter = _adapter(ScriptAdapter, statuses, monkeypatch, "episode:1", "episode:2")
    monkeypatch.setattr(text_adapter, "script_revision", lambda path: "sha256:" + "9" * 64)
    intent = _intent(RunStage.SCRIPT)

    waiting = await adapter.inspect(intent=intent, receipt=intent.input_refs[0])

    assert waiting.kind == "WAIT"
    assert [sub for sub, *_ in tasks.submitted] == ["script:2:sha256:" + "7" * 64]
    statuses.by_episode[2] = [_status(A.GENERATE_ASSET_SHEETS, episode=2)]
    passed = await adapter.inspect(intent=intent, receipt=intent.input_refs[0])
    assert passed.kind == "PASS"
    assert [r.receipt_ref.partition("@")[0] for r in passed.receipts] == ["episode:1:script", "episode:2:script"]


async def test_succeeded_task_whose_output_the_status_still_lacks_never_passes(tasks, monkeypatch):
    adapter = _adapter(ScriptAdapter, Statuses({1: [_status(A.GENERATE_SCRIPT)]}), monkeypatch)
    intent = _intent(RunStage.SCRIPT)
    tasks.tasks["script:1:sha256:" + "7" * 64] = {"status": "succeeded"}

    with pytest.raises(OwnerBlocked, match="OWNER_OUTPUT_MISSING"):
        await adapter.inspect(intent=intent, receipt=intent.input_refs[0])


async def test_a_failed_owner_task_is_resubmitted_until_the_attempts_are_spent(tasks, monkeypatch):
    adapter = _adapter(ScriptAdapter, Statuses({1: [_status(A.GENERATE_SCRIPT)]}), monkeypatch)
    intent = _intent(RunStage.SCRIPT)
    first = "script:1:sha256:" + "7" * 64
    tasks.tasks[first] = {"status": "failed"}

    waiting = await adapter.inspect(intent=intent, receipt=intent.input_refs[0])

    assert waiting.kind == "WAIT"
    assert [sub for sub, *_ in tasks.submitted] == [f"{first}#attempt-2"]
    tasks.tasks[f"{first}#attempt-2"] = {"status": "failed"}
    tasks.tasks[f"{first}#attempt-3"] = {"status": "failed"}
    with pytest.raises(OwnerBlocked, match="OWNER_TASK_FAILED"):
        await adapter.inspect(intent=intent, receipt=intent.input_refs[0])
    assert [sub for sub, *_ in tasks.submitted] == [f"{first}#attempt-2"]


@pytest.mark.parametrize(
    ("cls", "stage", "action"),
    [
        (ScriptAdapter, RunStage.SCRIPT, A.PREPARE_SCRIPT_PLAN),
        (EpisodePlanAdapter, RunStage.EPISODE_PLAN, A.RESET_EPISODE_PLANNING),
        (ScriptPlanAdapter, RunStage.SCRIPT_PLAN, A.ANALYZE_ASSETS),
    ],
)
async def test_a_status_that_moved_backwards_is_an_external_change(tasks, monkeypatch, cls, stage, action):
    adapter = _adapter(cls, Statuses({1: [_status(action)]}), monkeypatch)

    with pytest.raises(OwnerBlocked, match="EXTERNAL_INPUT_CHANGED"):
        await adapter.inspect(intent=_intent(stage), receipt=_intent(stage).input_refs[0])
    assert tasks.submitted == []


async def test_a_moved_source_revision_is_an_external_change(tasks, monkeypatch):
    moved = _status(A.GENERATE_SCRIPT, source_revision="sha256:" + "6" * 64)
    adapter = _adapter(ScriptAdapter, Statuses({1: [moved]}), monkeypatch)

    with pytest.raises(OwnerBlocked, match="EXTERNAL_INPUT_CHANGED"):
        await adapter.inspect(intent=_intent(RunStage.SCRIPT), receipt=_intent(RunStage.SCRIPT).input_refs[0])


async def test_an_active_task_waits_and_a_project_blocker_names_its_code(tasks, monkeypatch):
    waiting = _adapter(ScriptAdapter, Statuses({1: [_status(A.WAIT_FOR_TASK)]}), monkeypatch)
    intent = _intent(RunStage.SCRIPT)
    assert (await waiting.inspect(intent=intent, receipt=intent.input_refs[0])).kind == "WAIT"

    blocked = _status(A.NONE, blockers=[WorkflowBlocker(code="script_plan_quarantined", path="p", reason="r")])
    adapter = _adapter(ScriptAdapter, Statuses({1: [blocked]}), monkeypatch)
    with pytest.raises(OwnerBlocked, match="WORKFLOW_SCRIPT_PLAN_QUARANTINED"):
        await adapter.inspect(intent=intent, receipt=intent.input_refs[0])


async def test_planner_windows_are_keyed_by_the_planned_ledger(tasks, monkeypatch):
    projects = Projects()
    statuses = Statuses({1: [_status(A.PLAN_EPISODES)]})
    adapter = _adapter(EpisodePlanAdapter, statuses, monkeypatch, projects=projects)
    intent = _intent(RunStage.EPISODE_PLAN)

    assert (await adapter.inspect(intent=intent, receipt=intent.input_refs[0])).kind == "WAIT"
    tasks.tasks["plan:0"]["status"] = "succeeded"
    projects.episodes.append({"episode": 1, "title": "Một"})
    assert (await adapter.inspect(intent=intent, receipt=intent.input_refs[0])).kind == "WAIT"
    assert [sub for sub, *_ in tasks.submitted] == ["plan:0", "plan:1"]

    statuses.by_episode[1] = [_status(A.PREPARE_SCRIPT_PLAN)]
    passed = await adapter.inspect(intent=intent, receipt=intent.input_refs[0])
    assert passed.kind == "PASS"
    assert passed.receipts[0].receipt_ref == "episode:1:plan"


async def test_script_plan_confirmation_runs_once_then_the_stage_passes(tasks, monkeypatch):
    statuses = Statuses({1: [_status(A.CONFIRM_SCRIPT_PLAN), _status(A.GENERATE_SCRIPT)]})
    confirmed: list[int] = []
    authorized: list[str] = []

    async def confirm(project_name, episode):
        confirmed.append(episode)

    async def current_subject(sessions, intent, *, subject_digest):
        return subject_digest

    class Authority:
        async def require_locked(self, session, *, subject):
            authorized.append(subject)

    monkeypatch.setattr(text_adapter, "current_subject", current_subject)
    monkeypatch.setattr(text_adapter, "script_plan_path", lambda path, project, episode: path)
    monkeypatch.setattr(text_adapter, "content_fingerprint", lambda path: "sha256:" + "7" * 64)
    _adapter(ScriptPlanAdapter, statuses, monkeypatch)
    adapter = ScriptPlanAdapter(
        Sessions(), authority=Authority(), projects=Projects(), resolver=None, status=statuses, confirm=confirm
    )
    intent = _intent(RunStage.SCRIPT_PLAN)

    passed = await adapter.inspect(intent=intent, receipt=intent.input_refs[0])

    assert (passed.kind, confirmed, tasks.submitted) == ("PASS", [1], [])
    assert authorized == [intent.input_refs[0].digest]
    assert passed.receipts[0].receipt_ref == "episode:1:script-plan@sha256:" + "7" * 64


async def test_a_stale_rebuild_is_not_regenerated_automatically(tasks, monkeypatch):
    stale = _status(A.PREPARE_SCRIPT_PLAN)
    stale.next_action.args["expected_stale_script_plan_revision"] = "sha256:" + "8" * 64
    adapter = _adapter(ScriptPlanAdapter, Statuses({1: [stale]}), monkeypatch)

    with pytest.raises(OwnerBlocked, match="SCRIPT_PLAN_REBUILD_REQUIRED"):
        await adapter.inspect(intent=_intent(RunStage.SCRIPT_PLAN), receipt=_intent(RunStage.SCRIPT_PLAN).input_refs[0])


def _quarantined(tmp_path, monkeypatch):
    draft = tmp_path / "script_plan_segments.invalid.json"
    content = {"segments": [{"text": "generated"}]}
    draft.write_text(json.dumps({"meta": generated_meta(content), "content": content}), encoding="utf-8")
    monkeypatch.setattr(text_adapter, "script_plan_quarantine_path", lambda path, project, episode: draft)
    blocked = _status(A.NONE, blockers=[WorkflowBlocker(code="script_plan_quarantined", path="p", reason="r")])
    return draft, Statuses({1: [blocked, _status(A.PREPARE_SCRIPT_PLAN)]})


async def test_a_script_plan_this_run_had_quarantined_is_set_aside_and_generated_again(tasks, monkeypatch, tmp_path):
    draft, statuses = _quarantined(tmp_path, monkeypatch)
    adapter = _adapter(ScriptPlanAdapter, statuses, monkeypatch)
    intent = _intent(RunStage.SCRIPT_PLAN)
    tasks.tasks["script-plan:1"] = {"status": "failed"}

    waiting = await adapter.inspect(intent=intent, receipt=intent.input_refs[0])

    assert waiting.kind == "WAIT"
    assert [sub for sub, *_ in tasks.submitted] == ["script-plan:1#attempt-2"]
    assert not draft.exists()
    assert (tmp_path / "script_plan_segments.invalid.json.rejected-1").exists()


async def test_a_draft_a_human_edited_after_generation_stays_for_the_human(tasks, monkeypatch, tmp_path):
    draft, statuses = _quarantined(tmp_path, monkeypatch)
    edited = json.loads(draft.read_text(encoding="utf-8"))
    edited["content"] = {"segments": [{"text": "the Human's rewrite"}]}
    draft.write_text(json.dumps(edited), encoding="utf-8")
    adapter = _adapter(ScriptPlanAdapter, statuses, monkeypatch)
    intent = _intent(RunStage.SCRIPT_PLAN)
    tasks.tasks["script-plan:1"] = {"status": "failed"}

    with pytest.raises(OwnerBlocked, match="WORKFLOW_SCRIPT_PLAN_QUARANTINED"):
        await adapter.inspect(intent=intent, receipt=intent.input_refs[0])
    assert draft.exists()
    assert tasks.submitted == []


async def test_a_quarantined_draft_no_failed_task_of_the_run_left_stays_for_the_human(tasks, monkeypatch, tmp_path):
    draft, statuses = _quarantined(tmp_path, monkeypatch)
    adapter = _adapter(ScriptPlanAdapter, statuses, monkeypatch)
    intent = _intent(RunStage.SCRIPT_PLAN)

    with pytest.raises(OwnerBlocked, match="WORKFLOW_SCRIPT_PLAN_QUARANTINED"):
        await adapter.inspect(intent=intent, receipt=intent.input_refs[0])
    assert draft.exists()
    assert tasks.submitted == []
