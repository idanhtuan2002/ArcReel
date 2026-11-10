"""Text stages over the real workflow status owner, queue command receipts and the schema inventory executor."""

from __future__ import annotations

import json

import sqlalchemy as sa

from lib.db.models.production_run import ProductionUsageModel
from lib.db.models.task import Task
from lib.db.repositories.production_runs import ProductionRunRepository
from lib.db.repositories.task_repo import TaskRepository
from lib.text_backends.base import TextGenerationResult
from r2.contracts.automation import RunSnapshot, RunStage, RunStatus
from server import tool_runtime
from server.production_run.assets_adapter import AssetsAdapter
from server.production_run.controller import ProductionController
from server.production_run.text_adapter import EpisodePlanAdapter
from tests.integration.server.production_run.test_story_adapter import OWNER, Host
from tests.integration.server.production_run.test_story_adapter import interactive_env as interactive_env
from tests.integration.server.production_run.test_story_adapter import story_host as story_host
from tests.integration.server.production_run.test_story_adapter import story_policy as story_policy
from tests.integration.server.production_run.test_story_adapter import story_start as story_start
from tests.integration.server.story_authoring.test_driver import MODEL

EXTRACTED = {
    "characters": [{"name": "Lan", "description": "Cô gái gầy, tóc dài, áo bà ba nâu.", "voice_style": "nhỏ nhẹ"}],
    "scenes": [{"name": "Làng ven sông", "description": "Đường đất, hàng tre."}],
    "props": [],
}


class Resolver:
    def __init__(self, route: tuple[str, str]) -> None:
        self.route = route

    async def text_backend_for_task(self, task_type, project_name):
        return self.route


class RunInput:
    def __init__(self, run: RunSnapshot) -> None:
        self.run = run

    async def digest(self, *, user_id, project_name):
        return self.run.input_digest


class Generator:
    calls = 0

    async def generate(self, request, project_name=None, *, user_id="default", execution_id=None):
        Generator.calls += 1
        return TextGenerationResult(text=json.dumps(EXTRACTED), provider="fake", model="fake")


async def _at(host: Host, stage: RunStage) -> RunSnapshot:
    async with host.sessions() as session, session.begin():
        repository = ProductionRunRepository(session)
        run = await repository.claim_due(owner_id=OWNER, lease_seconds=120)
        assert run is not None
        moved = run.model_copy(update={"stage": stage, "status": RunStatus.RUNNING, "version": run.version + 1})
        return await repository.transition(expected=run, updated=moved, fencing_epoch=run.fencing_epoch)


def _controller(host: Host) -> ProductionController:
    writer = next(r for r in host.run.policy.routes if r.role == "script")
    shared = {"authority": host.authority, "projects": host.projects, "resolver": Resolver((writer.provider_id, MODEL))}
    return ProductionController(
        host.sessions,
        adapters={
            RunStage.ASSET_ANALYSIS: AssetsAdapter(host.sessions, **shared),
            RunStage.EPISODE_PLAN: EpisodePlanAdapter(host.sessions, **shared),
        },
        witness=RunInput(host.run),
        poll_seconds=0,
    )


async def _tick(host: Host, controller: ProductionController) -> RunSnapshot:
    async with host.sessions() as session, session.begin():
        claimed = await ProductionRunRepository(session).claim_due(owner_id=OWNER, lease_seconds=120)
    assert claimed is not None
    return await controller.tick(run_id=host.run.run_id, owner_id=OWNER)


async def _tasks(host: Host, task_type: str) -> list[Task]:
    async with host.sessions() as session:
        return list((await session.execute(sa.select(Task).where(Task.task_type == task_type))).scalars())


async def _execute(host: Host, task: Task, monkeypatch) -> None:
    async def create(task_type, project_name=None, **kwargs):
        return Generator()

    monkeypatch.setattr(tool_runtime.TextGenerator, "create", create)
    async with host.sessions() as session:
        row = await TaskRepository(session).get(task.task_id)
    assert row is not None
    result = await tool_runtime.execute_queued_text_task(row)
    async with host.sessions() as session, session.begin():
        await session.execute(
            sa.update(Task)
            .where(Task.task_id == task.task_id)
            .values(
                status="succeeded",
                result_json=json.dumps(result),
                started_at=Task.queued_at,
                finished_at=Task.queued_at,
            )
        )


async def test_inventory_stage_runs_the_schema_executor_once_and_pins_the_completed_revision(
    story_host: Host, monkeypatch
):
    host = story_host
    source = host.projects.get_project_path("project") / "source" / "can-nha.txt"
    source.write_text("Lan về làng ven sông, mang theo chiếc vòng bạc của mẹ.", encoding="utf-8")
    await _at(host, RunStage.ASSET_ANALYSIS)
    controller = _controller(host)

    waiting = await _tick(host, controller)
    again = await _tick(host, controller)

    assert (waiting.status, again.status) == (RunStatus.WAITING_TASK, RunStatus.WAITING_TASK)
    [task] = await _tasks(host, "text_asset_inventory")
    await _execute(host, task, monkeypatch)
    passed = await _tick(host, controller)

    assert (passed.stage, passed.status) == (RunStage.EPISODE_PLAN, RunStatus.RUNNING)
    project = host.projects.load_project("project")
    assert project["characters"]["Lan"]["description"].startswith("Cô gái")
    async with host.sessions() as session:
        receipt = await ProductionRunRepository(session).stage_receipt(run=passed, stage=RunStage.ASSET_ANALYSIS)
        usage = (
            await session.execute(
                sa.select(ProductionUsageModel).where(ProductionUsageModel.owner == "asset-inventory")
            )
        ).scalar_one()
    assert receipt is not None
    assert json.loads(usage.usage_json)["tasks"] == 1
    assert Generator.calls == 1

    planning = await _tick(host, controller)
    assert planning.status is RunStatus.WAITING_TASK
    [plan_task] = await _tasks(host, "text_episode_plan")
    assert plan_task.resource_id == "episode-planning"


async def test_another_actors_active_task_on_the_resource_blocks_instead_of_adopting_it(story_host: Host):
    host = story_host
    source = host.projects.get_project_path("project") / "source" / "can-nha.txt"
    source.write_text("Lan về làng.", encoding="utf-8")
    await _at(host, RunStage.ASSET_ANALYSIS)
    async with host.sessions() as session:
        await TaskRepository(session).enqueue(
            project_name="project",
            task_type="text_asset_inventory",
            media_type="text",
            resource_id="asset-inventory",
            payload={"scope": {"kind": "all", "files": []}, "expected_source_revision": "sha256:" + "0" * 64},
            user_id="default",
        )

    blocked = await _tick(host, _controller(host))

    assert (blocked.status, blocked.reason) == (RunStatus.BLOCKED_INPUT_CHANGED, "EXTERNAL_INPUT_CHANGED")
    assert len(await _tasks(host, "text_asset_inventory")) == 1


async def test_a_changed_script_route_blocks_before_any_task(story_host: Host):
    host = story_host
    await _at(host, RunStage.ASSET_ANALYSIS)
    controller = _controller(host)
    adapter = controller._adapters[RunStage.ASSET_ANALYSIS]
    adapter._resolver = Resolver(("custom-999", "other"))

    blocked = await _tick(host, controller)

    assert (blocked.status, blocked.reason) == (RunStatus.BLOCKED_CONFIGURATION, "MODEL_CONFIG_CHANGED")
    assert await _tasks(host, "text_asset_inventory") == []
