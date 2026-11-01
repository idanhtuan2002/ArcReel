"""Idea to a handed-off manuscript through the real controller, story owners and signed run delegation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.production_run import ProductionUsageModel
from lib.db.models.task import Task
from lib.db.repositories.gates import GreenlightRepository
from lib.db.repositories.production_runs import ProductionRunRepository
from lib.project_manager import ProjectManager
from r2.automation.authorization import automation_principal
from r2.automation.identity import policy_digest
from r2.contracts.automation import (
    AutomationOperation,
    GrantRequest,
    ModelRoute,
    RunCommand,
    RunPolicy,
    RunSnapshot,
    RunStage,
    RunStatus,
)
from r2.contracts.gates import GateAutomationAuthorizationV1
from server import auth
from server.production_run.controller import ProductionController
from server.production_run.inputs import ProjectInputWitness
from server.production_run.story_adapter import (
    BriefAdapter,
    HandoffAdapter,
    StoryAdapter,
    StoryCommitAdapter,
    story_limits,
)
from server.services.automation_grants import AutomationGrantCustodian, RunAutomationAuthority
from server.story_authoring.authority import GrantNarrativeShowrunnerAuthority
from server.story_authoring.executor import execute_story_run_task
from server.story_authoring.runtime import RunPhase, RunStateStore, set_phase
from server.story_authoring.service import StoryAuthoringService
from server.tool_runtime import (
    CallerContext,
    CreateProjectToolRequest,
    ProjectScope,
    Services,
    ToolRequest,
    UploadSourceRequest,
    create_project,
    upload_source,
)
from tests.integration.server.services.test_automation_grants import custodian
from tests.integration.server.services.test_automation_grants import interactive_env as interactive_env
from tests.integration.server.services.test_quality_profile_custodian import prepare_qualified_custody
from tests.integration.server.story_authoring.test_driver import MODEL, ScriptedModel
from tests.integration.server.story_authoring.test_executor import BASE_URL, _provider

OWNER = "controller"


class _Unused:
    pass


def _policy(provider_id: str, **overrides) -> RunPolicy:
    writer = ModelRoute(
        role="writer",
        provider_id=provider_id,
        model_id=MODEL,
        model_identity="writer-model",
        config_digest="sha256:" + "1" * 64,
        local=True,
        paid=False,
        currency="USD",
        max_cost_per_call=None,
    )
    fields = {"profile_id": "fiction_narration_vi_v1", "profile_digest": "sha256:" + "a" * 64, **overrides}
    return RunPolicy(
        profile_id=fields.pop("profile_id"),
        profile_digest=fields.pop("profile_digest"),
        routes=(
            writer,
            writer.model_copy(update={"role": "script"}),
            writer.model_copy(update={"role": "reviewer_a", "model_identity": "reviewer-a", "model_id": "rev-a"}),
            writer.model_copy(update={"role": "reviewer_b", "model_identity": "reviewer-b", "model_id": "rev-b"}),
        ),
        currency="USD",
        max_cost_minor_units=100,
        max_model_calls=1200,
        max_tasks=50,
        max_runtime_seconds=43200,
        route_digests=("sha256:" + "b" * 64,),
        **fields,
    )


@pytest.fixture
def story_policy():
    """Policy fields a test module replaces; called with the session factory after custody exists, before the run."""

    async def overrides(sessions) -> dict:
        del sessions
        return {}

    return overrides


@dataclass
class Host:
    sessions: async_sessionmaker[AsyncSession]
    projects: ProjectManager
    stories: StoryAuthoringService
    controller: ProductionController
    run: RunSnapshot
    uploads: list[str]
    issuer: AutomationGrantCustodian
    authority: RunAutomationAuthority


@pytest.fixture
async def story_host(concurrent_session_factory, tmp_path, interactive_env, story_policy):
    from server.services.governance_attestation import serve_governance_attestor

    sessions = concurrent_session_factory
    root, runtime, *_ = await prepare_qualified_custody(sessions, tmp_path)
    async with serve_governance_attestor(
        root, runtime, session_factory=sessions, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        projects = ProjectManager(tmp_path / "projects")
        created = await create_project(
            ToolRequest(
                CreateProjectToolRequest(
                    name="project", title="Truyện", content_mode="narration", generation_mode="storyboard"
                )
            ),
            CallerContext(user_id="default", source="embedded"),
            Services(projects=projects, workflow_planner=_Unused(), capabilities=_Unused()),
        )
        assert created.problem is None
        policy = _policy(await _provider(sessions), **await story_policy(sessions))
        witness = ProjectInputWitness(sessions, projects=projects)
        start_input = await witness.digest(user_id="default", project_name="project")
        async with sessions() as session, session.begin():
            run = await ProductionRunRepository(session).create(
                command=RunCommand(
                    user_id="default",
                    project_name="project",
                    command_id="start-1",
                    action="START",
                    expected_version=0,
                    expected_input_digest=start_input,
                    policy_digest=policy_digest(policy),
                    idea="Một người con về làng bán căn nhà của cha.",
                ),
                policy=policy,
            )
        issuer = custodian(sessions, root, runtime)
        await issuer.issue(
            interactive_token=auth.create_token("actor"),
            request=GrantRequest(
                user_id=run.user_id,
                project_name=run.project_name,
                run_id=run.run_id,
                issuer_id="actor",
                command_id="start-1",
                expected_run_version=run.version,
                input_digest=run.input_digest,
                policy_digest=policy_digest(run.policy),
                operations=frozenset(AutomationOperation),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
        )
        authority = issuer.authority()
        stories = StoryAuthoringService(
            session_factory=sessions,
            authority=GrantNarrativeShowrunnerAuthority(sessions, None),
            project_dir_for=projects.get_project_path,
        )
        uploads: list[str] = []

        def upload_for(intent):
            async def upload(filename, content, on_conflict):
                uploads.append(filename)
                outcome = await upload_source(
                    ToolRequest(UploadSourceRequest(filename=filename, content=content, on_conflict=on_conflict)),
                    ProjectScope(project_name="project", projects_root=projects.projects_root),
                    CallerContext(user_id="default", source="embedded"),
                    Services(projects=projects, workflow_planner=_Unused(), capabilities=_Unused()),
                )
                assert outcome.problem is None
                assert outcome.value is not None
                return outcome.value

            return upload

        shared = {"authority": authority, "stories": stories, "projects": projects}
        controller = ProductionController(
            sessions,
            adapters={
                RunStage.BRIEF: BriefAdapter(sessions, **shared),
                RunStage.STORY: StoryAdapter(sessions, **shared),
                RunStage.STORY_COMMIT: StoryCommitAdapter(sessions, **shared),
                RunStage.HANDOFF: HandoffAdapter(
                    sessions, authority=authority, projects=projects, upload_for=upload_for
                ),
            },
            witness=witness,
            poll_seconds=0,
        )
        yield Host(sessions, projects, stories, controller, run, uploads, issuer, authority)


async def _tick(host: Host) -> RunSnapshot:
    async with host.sessions() as session, session.begin():
        claimed = await ProductionRunRepository(session).claim_due(owner_id=OWNER, lease_seconds=120)
    assert claimed is not None
    assert claimed.run_id == host.run.run_id
    return await host.controller.tick(run_id=host.run.run_id, owner_id=OWNER)


async def _story_task(host: Host) -> str:
    async with host.sessions() as session:
        task = (await session.execute(sa.select(Task).where(Task.task_type == "story_authoring_run"))).scalar_one()
    return task.task_id


async def _execute_story(host: Host) -> str:
    async with host.sessions() as session:
        task = (await session.execute(sa.select(Task).where(Task.task_type == "story_authoring_run"))).scalar_one()
    import json

    payload = json.loads(task.payload_json)
    model = ScriptedModel()

    def client_for(base_url, api_key):
        from lib.text_backends.ollama import OllamaChatClient

        assert base_url == BASE_URL
        return OllamaChatClient(base_url=base_url, transport=httpx.MockTransport(model.handler))

    result = await execute_story_run_task(
        "project",
        task.resource_id,
        payload,
        user_id="default",
        task_id=task.task_id,
        session_factory=host.sessions,
        project_dir=host.projects.get_project_path("project"),
        client_for=client_for,
    )
    return result["phase"]


async def test_a_new_idea_reaches_a_committed_manuscript_handed_to_video(story_host: Host):
    host = story_host
    principal = automation_principal(host.run.run_id)

    briefed = await _tick(host)
    assert (briefed.stage, briefed.status) == (RunStage.STORY, RunStatus.RUNNING)
    async with host.sessions() as session:
        [decision] = await GreenlightRepository(session).list_for_project(user_id="default", project_name="project")
    assert isinstance(decision.authorization, GateAutomationAuthorizationV1)
    assert decision.authorization.authenticated_principal == principal

    waiting = await _tick(host)
    assert (waiting.stage, waiting.status) == (RunStage.STORY, RunStatus.WAITING_TASK)
    task_id = await _story_task(host)
    brief_limits = (await RunStateStore(host.sessions, task_id=task_id).load()).limits
    assert brief_limits.generate_calls_max == story_limits(host.run.policy, brief_limits).generate_calls_max <= 300
    assert await _execute_story(host) == "READY_FOR_APPROVAL"

    offered = await _tick(host)
    assert (offered.stage, offered.status) == (RunStage.STORY_COMMIT, RunStatus.RUNNING)
    async with host.sessions() as session:
        usage = (
            await session.execute(sa.select(ProductionUsageModel).where(ProductionUsageModel.owner == "story-run"))
        ).scalar_one()
    state = await RunStateStore(host.sessions, task_id=task_id).load()
    assert f'"model_calls":{state.usage.generate_calls + state.usage.count_calls}' in usage.usage_json

    committed = await _tick(host)
    assert (committed.stage, committed.status, committed.reason) == (RunStage.HANDOFF, RunStatus.RUNNING, None)
    state = await RunStateStore(host.sessions, task_id=task_id).load()
    assert state.phase is RunPhase.COMMITTED
    assert state.commit is not None
    assert state.commit.approval is not None
    assert state.commit.approval.actor_id == principal

    handed = await _tick(host)
    assert (handed.stage, handed.status) == (RunStage.ASSET_ANALYSIS, RunStatus.RUNNING)
    source = host.projects.get_project_path("project") / "source" / "can-nha-cu.txt"
    assert source.read_text(encoding="utf-8").startswith("# Căn nhà cũ\n")
    assert host.uploads == ["can-nha-cu.md"]
    assert host.projects.load_project("project")["source_language"] == "vi"

    stopped = await _tick(host)
    assert (stopped.status, stopped.reason) == (RunStatus.BLOCKED_CONFIGURATION, "STAGE_CAPABILITY_INCOMPLETE")


async def test_succeeded_task_with_blocked_story_never_handoffs(story_host: Host):
    host = story_host
    await _tick(host)
    await _tick(host)
    task_id = await _story_task(host)
    await RunStateStore(host.sessions, task_id=task_id).apply(
        lambda s: (set_phase(s, RunPhase.BLOCKED_QUALITY, reason="review failed"), None)
    )
    async with host.sessions() as session, session.begin():
        await session.execute(sa.update(Task).where(Task.task_id == task_id).values(status="succeeded"))

    failed = await _tick(host)

    assert (failed.stage, failed.status, failed.reason) == (RunStage.STORY, RunStatus.FAILED_QUALITY, "BLOCKED_QUALITY")
    handoff_call_count = len(host.uploads)
    assert handoff_call_count == 0
    assert list((host.projects.get_project_path("project") / "source").glob("*.txt")) == []


async def test_a_story_task_that_stopped_while_running_is_an_unknown_outcome(story_host: Host):
    host = story_host
    await _tick(host)
    await _tick(host)
    task_id = await _story_task(host)
    async with host.sessions() as session, session.begin():
        await session.execute(sa.update(Task).where(Task.task_id == task_id).values(status="failed"))

    blocked = await _tick(host)

    assert (blocked.stage, blocked.status, blocked.reason) == (
        RunStage.STORY,
        RunStatus.BLOCKED_UNKNOWN,
        "OUTCOME_UNKNOWN",
    )


async def test_story_start_replays_to_the_same_story_run(story_host: Host):
    host = story_host
    await _tick(host)
    await _tick(host)
    adapter = host.controller._adapters[RunStage.STORY]
    async with host.sessions() as session, session.begin():
        run = await ProductionRunRepository(session).claim_due(owner_id=OWNER, lease_seconds=120)
        assert run is not None
        step = await ProductionRunRepository(session).current_step(run=run)
    assert step is not None
    intent, receipt = step

    replay = await adapter.dispatch(intent)

    assert replay == receipt
    async with host.sessions() as session:
        tasks = (await session.execute(sa.select(Task).where(Task.task_type == "story_authoring_run"))).scalars()
        assert len(list(tasks)) == 1


async def test_a_manifest_with_open_findings_is_never_committed_automatically(story_host: Host, monkeypatch):
    from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority

    host = story_host
    await _tick(host)
    await _tick(host)
    await _execute_story(host)
    await _tick(host)

    async def refuse(cls, **kwargs):
        raise NarrativeDecisionAuthorizationError("UNRESOLVED_STORY_FINDINGS")

    monkeypatch.setattr(AutomaticNarrativeAuthority, "bind", classmethod(refuse))
    blocked = await _tick(host)

    assert (blocked.stage, blocked.status, blocked.reason) == (
        RunStage.STORY_COMMIT,
        RunStatus.BLOCKED_CONFIGURATION,
        "STORY_EXCEPTION_REQUIRES_HUMAN",
    )
    state = await RunStateStore(host.sessions, task_id=await _story_task(host)).load()
    assert state.phase is RunPhase.READY_FOR_APPROVAL


async def test_revoked_delegation_stops_the_commit_before_any_owner_write(story_host: Host):
    host = story_host
    await _tick(host)
    await _tick(host)
    await _execute_story(host)
    await _tick(host)
    await host.issuer.revoke(interactive_token=auth.create_token("actor"), run_id=host.run.run_id, expected_version=1)

    blocked = await _tick(host)

    assert (blocked.stage, blocked.status, blocked.reason) == (
        RunStage.STORY_COMMIT,
        RunStatus.BLOCKED_CONFIGURATION,
        "AUTOMATION_GRANT_NOT_CURRENT",
    )
    state = await RunStateStore(host.sessions, task_id=await _story_task(host)).load()
    assert state.phase is RunPhase.READY_FOR_APPROVAL


async def test_a_source_the_user_adds_mid_run_blocks_without_adopting_it(story_host: Host):
    host = story_host
    await _tick(host)
    (host.projects.get_project_path("project") / "source" / "khac.txt").write_text("Một truyện khác.", encoding="utf-8")

    blocked = await _tick(host)

    assert (blocked.stage, blocked.status, blocked.reason) == (
        RunStage.STORY,
        RunStatus.BLOCKED_INPUT_CHANGED,
        "EXTERNAL_INPUT_CHANGED",
    )
    async with host.sessions() as session:
        assert (await session.execute(sa.select(Task))).first() is None


async def test_a_witnessed_setting_moves_the_witness_and_a_run_owned_field_does_not(story_host: Host):
    host = story_host
    witness = ProjectInputWitness(host.sessions, projects=host.projects)
    before = await witness.digest(user_id="default", project_name="project")

    def own(project):
        project["episodes"] = [{"episode": 1}]
        project["characters"] = {"Lan": {"description": "x"}}

    host.projects.update_project("project", own)
    assert await witness.digest(user_id="default", project_name="project") == before

    def user(project):
        project["narration_speed"] = 1.25

    host.projects.update_project("project", user)
    assert await witness.digest(user_id="default", project_name="project") != before
