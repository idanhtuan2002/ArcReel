"""Idea to a handed-off manuscript through the real controller, story owners and signed run delegation."""

from __future__ import annotations

import json
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
    RunScope,
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
from server.story_authoring.artifacts import StoryBlobStore
from server.story_authoring.authority import GrantNarrativeShowrunnerAuthority
from server.story_authoring.commit import load_offered_manifest, manifest_bytes
from server.story_authoring.driver import StoryBrief
from server.story_authoring.executor import execute_story_run_task
from server.story_authoring.runtime import RunPhase, RunState, RunStateStore, set_phase
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
def story_policy(request):
    """Policy fields a test module replaces; called with the session factory after custody exists, before the run.
    A test may give its own (indirect parametrization) as an async callable of the session factory."""
    given = getattr(request, "param", None)

    async def overrides(sessions) -> dict:
        return await given(sessions) if given is not None else {}

    return overrides


@pytest.fixture
def story_start() -> dict:
    """Start command fields a test module replaces."""
    return {"idea": "Một người con về làng bán căn nhà của cha."}


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
async def story_host(concurrent_session_factory, tmp_path, interactive_env, story_policy, story_start):
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
                    **story_start,
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


async def _execute_story(host: Host, *, asked: list[str] | None = None, model_name: str = MODEL) -> str:
    """Run the story task to its next stop on the local model ``model_name``; ``asked`` collects the model each
    call named."""
    async with host.sessions() as session:
        task = (await session.execute(sa.select(Task).where(Task.task_type == "story_authoring_run"))).scalar_one()
    import json

    payload = json.loads(task.payload_json)
    model = ScriptedModel(model_name)

    async def handler(request: httpx.Request) -> httpx.Response:
        if asked is not None and request.url.path.endswith("/chat"):
            asked.append(json.loads(request.content)["model"])
        return await model.handler(request)

    def client_for(base_url, api_key):
        from lib.text_backends.ollama import OllamaChatClient

        assert base_url == BASE_URL
        return OllamaChatClient(base_url=base_url, transport=httpx.MockTransport(handler))

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
    offered_manifest = load_offered_manifest(StoryBlobStore(host.projects.get_project_path("project")), state)
    assert state.commit.approval.accepted_exceptions == tuple(sorted(offered_manifest.exceptions_offered))

    handed = await _tick(host)
    assert (handed.stage, handed.status) == (RunStage.ASSET_ANALYSIS, RunStatus.RUNNING)
    source = host.projects.get_project_path("project") / "source" / "can-nha-cu.txt"
    assert source.read_text(encoding="utf-8").startswith("Căn nhà cũ\n\n")
    assert host.uploads == ["can-nha-cu.md"]
    assert host.projects.load_project("project")["source_language"] == "vi"

    stopped = await _tick(host)
    assert (stopped.status, stopped.reason) == (RunStatus.BLOCKED_CONFIGURATION, "STAGE_CAPABILITY_INCOMPLETE")

    # The run's own hand-off leaves its input as it was; an edit to that handed-off story part moves it (ADR-0115).
    witness = ProjectInputWitness(host.sessions, projects=host.projects)
    assert await witness.digest(user_id="default", project_name="project") == handed.input_digest
    source.write_text(source.read_text(encoding="utf-8") + "\nMột câu thêm vào.", encoding="utf-8")
    assert await witness.digest(user_id="default", project_name="project") != handed.input_digest


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


async def test_a_story_task_refused_before_the_run_authority_was_installed_is_queued_again(story_host: Host):
    host = story_host
    await _tick(host)
    await _tick(host)
    task_id = await _story_task(host)
    async with host.sessions() as session, session.begin():
        await session.execute(
            sa.update(Task)
            .where(Task.task_id == task_id)
            .values(status="failed", error_message="AUTOMATION_GOVERNANCE_NOT_ACTIVATED")
        )
    # A release before this check blocked the run; the Showrunner's Resume reads the step again.
    async with host.sessions() as session, session.begin():
        repository = ProductionRunRepository(session)
        live = await repository.locked(RunScope(user_id="default", project_name="project", run_id=host.run.run_id))
        await repository.apply_command(
            expected=live,
            updated=live.model_copy(
                update={
                    "status": RunStatus.BLOCKED_UNKNOWN,
                    "reason": "OUTCOME_UNKNOWN",
                    "version": live.version + 1,
                    "fencing_epoch": live.fencing_epoch + 1,
                }
            ),
        )
        live = await repository.locked(RunScope(user_id="default", project_name="project", run_id=host.run.run_id))
        await repository.apply_command(
            expected=live,
            updated=live.model_copy(
                update={
                    "status": RunStatus.RUNNING,
                    "reason": None,
                    "version": live.version + 1,
                    "fencing_epoch": live.fencing_epoch + 1,
                }
            ),
        )

    waiting = await _tick(host)

    assert (waiting.stage, waiting.status) == (RunStage.STORY, RunStatus.WAITING_TASK)
    async with host.sessions() as session:
        row = (await session.execute(sa.select(Task).where(Task.task_id == task_id))).scalar_one()
    assert (row.status, row.error_message) == ("queued", None)


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


async def test_recorded_critical_findings_are_accepted_as_is_and_the_run_continues(story_host: Host):
    import json

    host = story_host
    await _tick(host)
    await _tick(host)
    await _execute_story(host)
    store = RunStateStore(host.sessions, task_id=await _story_task(host))
    blobs = StoryBlobStore(host.projects.get_project_path("project"))
    finding = {"id": "F001", "code": "NO_ENDING", "severity": "NARRATIVE_CRITICAL", "node_id": "scene_draft[1,1]"}
    record = blobs.put(json.dumps({"findings": [finding], "packaging": None}).encode())
    manifest = load_offered_manifest(blobs, await store.load()).model_copy(
        update={"findings_open": ("F001",), "exceptions_offered": ("F001",), "quality_record_digest": record}
    )
    offered = blobs.put(manifest_bytes(manifest))

    def reoffer(state: RunState) -> tuple[RunState, None]:
        assert state.commit is not None
        return state.model_copy(
            update={"commit": state.commit.model_copy(update={"offered_manifest_digest": offered})}
        ), None

    await store.apply(reoffer)

    await _tick(host)
    committed = await _tick(host)

    assert (committed.stage, committed.status, committed.reason) == (RunStage.HANDOFF, RunStatus.RUNNING, None)
    state = await store.load()
    assert state.phase is RunPhase.COMMITTED
    assert state.commit is not None
    assert state.commit.approval is not None
    assert state.commit.approval.accepted_exceptions == ("F001",)


async def test_a_manifest_whose_findings_are_not_recorded_is_never_committed_automatically(
    story_host: Host, monkeypatch
):
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
        "STORY_FINDINGS_NOT_RECORDED",
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


async def test_a_story_whose_project_main_canon_was_taken_blocks_the_run_with_the_rebase_reason(story_host: Host):
    from datetime import UTC, datetime

    from lib.db.models.canon import CanonBranchModel

    host = story_host
    await _tick(host)
    await _tick(host)
    await _execute_story(host)
    await _tick(host)
    async with host.sessions() as session:  # another story run of the project took MAIN first
        session.add(
            CanonBranchModel(
                branch_id="story-other-canon",
                user_id=host.run.user_id,
                project_name=host.run.project_name,
                branch_type="MAIN",
                parent_branch_id=None,
                parent_version_id=None,
                head_version_id=None,
                created_at=datetime.now(UTC),
                created_by="run:other",
            )
        )
        await session.commit()

    blocked = await _tick(host)

    assert (blocked.stage, blocked.reason) == (RunStage.STORY_COMMIT, "STORY_CANON_BASE_MOVED")
    state = await RunStateStore(host.sessions, task_id=await _story_task(host)).load()
    assert state.phase is RunPhase.COMMIT_BLOCKED


async def test_a_story_blocked_below_its_bound_is_topped_up_and_goes_on_from_where_it_stopped(story_host: Host):
    from server.production_run.story_adapter import TOP_UP_LIMIT
    from server.story_authoring.driver import run_call_bound

    host = story_host
    await _tick(host)
    await _tick(host)
    task_id = await _story_task(host)
    store = RunStateStore(host.sessions, task_id=task_id)
    before = (await store.load()).limits
    # A film run's story share is cut below the structural bound.
    assert before.generate_calls_max < run_call_bound(before.chapters)
    await store.apply(lambda s: (set_phase(s, RunPhase.BLOCKED_BUDGET, reason="cap generate_calls reached"), None))
    async with host.sessions() as session, session.begin():
        await session.execute(sa.update(Task).where(Task.task_id == task_id).values(status="succeeded"))

    reworked = await _tick(host)
    assert (reworked.stage, reworked.status, reworked.generation) == (RunStage.STORY, RunStatus.RUNNING, 2)
    waiting = await _tick(host)
    assert (waiting.stage, waiting.status) == (RunStage.STORY, RunStatus.WAITING_TASK)
    state = await store.load()
    assert state.phase is RunPhase.RUNNING
    [top_up] = state.top_ups
    assert top_up.limits_before == before
    assert state.limits.generate_calls_max == run_call_bound(before.chapters)
    assert state.limits.wall_clock_max_seconds > before.wall_clock_max_seconds
    assert TOP_UP_LIMIT == 2

    assert await _execute_story(host) == "READY_FOR_APPROVAL"
    offered = await _tick(host)
    assert (offered.stage, offered.status) == (RunStage.STORY_COMMIT, RunStatus.RUNNING)
    committed = await _tick(host)
    assert (committed.stage, committed.status, committed.reason) == (RunStage.HANDOFF, RunStatus.RUNNING, None)
    async with host.sessions() as session:
        rows = (
            (await session.execute(sa.select(ProductionUsageModel).where(ProductionUsageModel.owner == "story-run")))
            .scalars()
            .all()
        )
    assert len(rows) == 2
    final = await store.load()
    spent = final.usage.generate_calls + final.usage.count_calls
    assert sum(int(json.loads(row.usage_json)["model_calls"]) for row in rows) == spent


async def test_a_paid_story_or_one_at_its_bound_stays_blocked_for_the_showrunner(story_host: Host):
    host = story_host
    await _tick(host)
    await _tick(host)
    task_id = await _story_task(host)
    store = RunStateStore(host.sessions, task_id=task_id)
    from server.story_authoring.driver import run_call_bound

    await store.apply(
        lambda s: (
            set_phase(
                s.model_copy(
                    update={
                        "limits": s.limits.model_copy(update={"generate_calls_max": run_call_bound(s.limits.chapters)})
                    }
                ),
                RunPhase.BLOCKED_BUDGET,
                reason="cap generate_calls reached",
            ),
            None,
        )
    )
    blocked = await _tick(host)
    assert (blocked.stage, blocked.status, blocked.reason) == (
        RunStage.STORY,
        RunStatus.BLOCKED_BUDGET,
        "BLOCKED_BUDGET",
    )
    assert (await store.load()).top_ups == ()


async def _cancel(host: Host, run: RunSnapshot) -> None:
    from lib.db.models.production_run import ProductionRunModel

    async with host.sessions() as session, session.begin():
        current = await ProductionRunRepository(session).get(
            user_id=run.user_id, project_name=run.project_name, run_id=run.run_id
        )
        assert current is not None
        ended = RunSnapshot.model_validate(
            {**current.model_dump(mode="python"), "status": RunStatus.CANCELLED, "reason": "CANCELLED_BY_USER"}
        )
        await session.execute(
            sa.update(ProductionRunModel)
            .where(ProductionRunModel.run_id == run.run_id)
            .values(status="CANCELLED", snapshot_json=ended.model_dump_json(), lease_owner=None, lease_until=None)
        )


async def _second_run(host: Host, policy: RunPolicy | None = None) -> RunSnapshot:
    policy = policy or host.run.policy
    witness = ProjectInputWitness(host.sessions, projects=host.projects)
    async with host.sessions() as session, session.begin():
        run = await ProductionRunRepository(session).create(
            command=RunCommand(
                user_id="default",
                project_name="project",
                command_id="start-2",
                action="START",
                expected_version=0,
                expected_input_digest=await witness.digest(user_id="default", project_name="project"),
                policy_digest=policy_digest(policy),
                idea="Một người con về làng bán căn nhà của cha.",
            ),
            policy=policy,
        )
    await host.issuer.issue(
        interactive_token=auth.create_token("actor"),
        request=GrantRequest(
            user_id=run.user_id,
            project_name=run.project_name,
            run_id=run.run_id,
            issuer_id="actor",
            command_id="start-2",
            expected_run_version=run.version,
            input_digest=run.input_digest,
            policy_digest=policy_digest(run.policy),
            operations=frozenset(AutomationOperation),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    )
    return run


async def _tick_run(host: Host, run_id: str) -> RunSnapshot:
    async with host.sessions() as session, session.begin():
        claimed = await ProductionRunRepository(session).claim_due(owner_id=OWNER, lease_seconds=120)
    assert claimed is not None
    assert claimed.run_id == run_id
    return await host.controller.tick(run_id=run_id, owner_id=OWNER)


async def test_a_new_run_takes_over_the_story_a_cancelled_run_left_unfinished(story_host: Host):
    from lib.db.models.host_hardening import CommandReceiptModel
    from server.production_run.execution_guard import configure_run_task_authority, require_run_task_authorized
    from server.production_run.story_adapter import adopted_story

    host = story_host
    await _tick(host)
    await _tick(host)
    task_id = await _story_task(host)
    store = RunStateStore(host.sessions, task_id=task_id)
    first = await store.load()
    # The first run is cancelled while its story was still writing; the task was refused and ended.
    async with host.sessions() as session, session.begin():
        await session.execute(sa.update(Task).where(Task.task_id == task_id).values(status="cancelled"))
    await _cancel(host, host.run)

    second = await _second_run(host)
    briefed = await _tick_run(host, second.run_id)
    assert (briefed.stage, briefed.status) == (RunStage.STORY, RunStatus.RUNNING)
    assert adopted_story(host.projects, "project", second.run_id) == first.run_id
    waiting = await _tick_run(host, second.run_id)
    assert (waiting.stage, waiting.status) == (RunStage.STORY, RunStatus.WAITING_TASK)

    async with host.sessions() as session:
        tasks = (await session.execute(sa.select(Task).where(Task.task_type == "story_authoring_run"))).scalars().all()
        owners = (
            (
                await session.execute(
                    sa.select(CommandReceiptModel.actor_scope).where(CommandReceiptModel.task_id == task_id)
                )
            )
            .scalars()
            .all()
        )
    assert [t.task_id for t in tasks] == [task_id]  # no second story run
    assert tasks[0].status == "queued"
    assert sorted(owners) == sorted([f"production-run:{host.run.run_id}", f"production-run:{second.run_id}"])
    state = await store.load()
    assert state.phase is RunPhase.RUNNING
    [taken] = state.top_ups
    assert taken.baseline == first.usage

    configure_run_task_authority(host.authority)
    try:
        async with host.sessions() as session:
            await require_run_task_authorized(session, {"task_id": task_id})
    finally:
        configure_run_task_authority(None)

    assert await _execute_story(host) == "READY_FOR_APPROVAL"
    offered = await _tick_run(host, second.run_id)
    assert (offered.stage, offered.status) == (RunStage.STORY_COMMIT, RunStatus.RUNNING)
    committed = await _tick_run(host, second.run_id)
    assert (committed.stage, committed.status, committed.reason) == (RunStage.HANDOFF, RunStatus.RUNNING, None)
    assert (await store.load()).phase is RunPhase.COMMITTED
    handed = await _tick_run(host, second.run_id)
    assert handed.stage is RunStage.ASSET_ANALYSIS


async def test_a_new_run_on_another_writer_takes_over_the_story_and_keeps_what_was_written(story_host: Host):
    """ADR-0138: the Showrunner switched the project's writer; the story goes on with it and nothing is rewritten."""
    from server.production_run.story_adapter import adopted_story

    host = story_host
    await _tick(host)
    await _tick(host)
    task_id = await _story_task(host)
    store = RunStateStore(host.sessions, task_id=task_id)
    first_models: list[str] = []
    assert await _execute_story(host, asked=first_models) == "READY_FOR_APPROVAL"
    assert set(first_models) == {MODEL}
    written = await store.load()
    heads = {node_id: node.head_revision_id for node_id, node in written.nodes.items()}
    # The writer's quota ran out before the Showrunner approved: the story stopped, its run was cancelled.
    await store.apply(lambda s: (set_phase(s, RunPhase.MODEL_UNAVAILABLE, reason="quota exhausted"), None))
    async with host.sessions() as session, session.begin():
        await session.execute(sa.update(Task).where(Task.task_id == task_id).values(status="succeeded"))
    await _cancel(host, host.run)

    other = await _provider(host.sessions, model="writer-two")
    routes = tuple(
        route.model_copy(update={"provider_id": other, "model_id": "writer-two", "model_identity": "writer-two"})
        if route.role in ("writer", "script")
        else route
        for route in host.run.policy.routes
    )
    second = await _second_run(host, host.run.policy.model_copy(update={"routes": routes}))
    briefed = await _tick_run(host, second.run_id)
    assert (briefed.stage, briefed.status) == (RunStage.STORY, RunStatus.RUNNING)
    assert adopted_story(host.projects, "project", second.run_id) == written.run_id
    waiting = await _tick_run(host, second.run_id)
    assert (waiting.stage, waiting.status) == (RunStage.STORY, RunStatus.WAITING_TASK)

    async with host.sessions() as session:
        task = (await session.execute(sa.select(Task).where(Task.task_id == task_id))).scalar_one()
    brief = StoryBrief.model_validate(json.loads(task.payload_json)["brief"])
    assert (brief.selection.provider_id, brief.selection.model_id) == (other, "writer-two")
    assert brief.basis is not None
    assert brief.basis.routes != brief.routes()
    assert brief.gate_a_decision_id is not None
    state = await store.load()
    assert state.phase is RunPhase.RUNNING
    [taken] = state.top_ups
    assert taken.baseline == written.usage

    second_models: list[str] = []
    assert await _execute_story(host, asked=second_models, model_name="writer-two") == "READY_FOR_APPROVAL"
    assert set(second_models) <= {"writer-two"}
    after = await store.load()
    assert {node_id: node.head_revision_id for node_id, node in after.nodes.items() if node_id in heads} == heads


FALLBACK = "writer-two"


async def _writer_fallback(sessions) -> dict:
    """ADR-0139: the run's writer falls back to another local model."""
    other = await _provider(sessions, model=FALLBACK)
    fallback = ModelRoute(
        role="writer",
        provider_id=other,
        model_id=FALLBACK,
        model_identity=FALLBACK,
        config_digest="sha256:" + "2" * 64,
        local=True,
        paid=False,
        currency="USD",
        max_cost_per_call=None,
    )
    return {"fallback_routes": (fallback,)}


def _list_fallbacks(host: Host, *models: str, local: bool = True) -> None:
    """The project's writer fallbacks as the settings hold them now (ADR-0139: edited freely, read when needed)."""
    [spare] = host.run.policy.fallback_routes
    entries = [
        {"role": "writer", "provider_id": spare.provider_id, "model_id": m, "model_identity": m, "local": local}
        for m in models
    ]

    def write(project: dict) -> None:
        project.setdefault("automation", {})["fallbacks"] = entries

    host.projects.update_project("project", write)


async def _stop(host: Host, task_id: str) -> None:
    store = RunStateStore(host.sessions, task_id=task_id)
    await store.apply(lambda s: (set_phase(s, RunPhase.MODEL_UNAVAILABLE, reason="429 quota exhausted"), None))
    async with host.sessions() as session, session.begin():
        await session.execute(sa.update(Task).where(Task.task_id == task_id).values(status="succeeded"))


async def _brief(host: Host, task_id: str) -> StoryBrief:
    async with host.sessions() as session:
        task = (await session.execute(sa.select(Task).where(Task.task_id == task_id))).scalar_one()
    return StoryBrief.model_validate(json.loads(task.payload_json)["brief"])


@pytest.mark.parametrize("story_policy", [_writer_fallback], indirect=True)
async def test_a_story_whose_writer_failed_goes_on_with_the_fallback_writer_in_the_same_run(story_host: Host):
    host = story_host
    _list_fallbacks(host, FALLBACK)
    await _tick(host)
    await _tick(host)
    task_id = await _story_task(host)
    store = RunStateStore(host.sessions, task_id=task_id)
    first: list[str] = []
    assert await _execute_story(host, asked=first) == "READY_FOR_APPROVAL"
    written = await store.load()
    heads = {node_id: node.head_revision_id for node_id, node in written.nodes.items()}
    await _stop(host, task_id)

    reworked = await _tick(host)
    assert (reworked.stage, reworked.status, reworked.generation) == (RunStage.STORY, RunStatus.RUNNING, 2)
    waiting = await _tick(host)
    assert (waiting.stage, waiting.status, waiting.reason) == (RunStage.STORY, RunStatus.WAITING_TASK, None)

    brief = await _brief(host, task_id)
    assert brief.selection.model_id == FALLBACK
    assert brief.basis is not None
    assert brief.gate_a_decision_id is not None
    state = await store.load()
    assert state.phase is RunPhase.RUNNING
    [moved] = state.top_ups
    assert moved.baseline == written.usage

    second: list[str] = []
    assert await _execute_story(host, asked=second, model_name=FALLBACK) == "READY_FOR_APPROVAL"
    assert set(second) <= {FALLBACK}
    after = await store.load()
    assert {node_id: node.head_revision_id for node_id, node in after.nodes.items() if node_id in heads} == heads
    offered = await _tick(host)
    assert (offered.stage, offered.status) == (RunStage.STORY_COMMIT, RunStatus.RUNNING)


@pytest.mark.parametrize("story_policy", [_writer_fallback], indirect=True)
async def test_a_story_on_the_last_writer_stays_stopped_for_the_showrunner(story_host: Host):
    host = story_host
    _list_fallbacks(host, FALLBACK)
    await _tick(host)
    await _tick(host)
    task_id = await _story_task(host)
    await _stop(host, task_id)
    assert (await _tick(host)).stage is RunStage.STORY  # moves to the fallback
    await _tick(host)
    assert (await _brief(host, task_id)).selection.model_id == FALLBACK
    await _stop(host, task_id)

    blocked = await _tick(host)
    assert blocked.stage is RunStage.STORY
    assert blocked.status is not RunStatus.RUNNING
    assert blocked.status is not RunStatus.WAITING_TASK
    assert (await _brief(host, task_id)).selection.model_id == FALLBACK


@pytest.mark.parametrize("story_policy", [_writer_fallback], indirect=True)
async def test_the_fallback_list_is_read_when_needed_and_held_to_the_runs_rules(story_host: Host):
    """Fallbacks removed while the run is open are not used; a cloud one under a local-only policy is passed over."""
    host = story_host
    await _tick(host)
    await _tick(host)
    task_id = await _story_task(host)
    _list_fallbacks(host)
    await _stop(host, task_id)
    stopped = await _tick(host)
    assert stopped.stage is RunStage.STORY
    assert stopped.status not in (RunStatus.RUNNING, RunStatus.WAITING_TASK)
    assert (await _brief(host, task_id)).selection.model_id == MODEL

    _list_fallbacks(host, FALLBACK, local=False)
    local_only = host.run.policy.model_copy(update={"local_only": True})
    from server.production_run.story_adapter import StoryAdapter

    adapter = StoryAdapter(host.sessions, authority=host.authority, stories=host.stories, projects=host.projects)
    run = host.run.model_copy(update={"policy": local_only})
    assert adapter._writer_order(run)[1:] == []
    _list_fallbacks(host, FALLBACK)
    assert adapter._writer_order(run)[1:] == [(host.run.policy.fallback_routes[0].provider_id, FALLBACK)]


async def _writer_fallback_without_repairs(sessions) -> dict:
    return {**await _writer_fallback(sessions), "unit_repair_limit": 0}


@pytest.mark.parametrize("story_policy", [_writer_fallback_without_repairs], indirect=True)
async def test_a_move_past_the_runs_repair_limit_leaves_the_story_stopped_for_a_human(story_host: Host):
    """Review M3: a fallback move is a STORY repair; past the limit the run blocks instead of failing for good."""
    host = story_host
    _list_fallbacks(host, FALLBACK)
    await _tick(host)
    await _tick(host)
    task_id = await _story_task(host)
    await _stop(host, task_id)

    stopped = await _tick(host)

    assert stopped.stage is RunStage.STORY
    assert stopped.status not in (RunStatus.RUNNING, RunStatus.WAITING_TASK, RunStatus.FAILED_QUALITY)
    assert (await _brief(host, task_id)).selection.model_id == MODEL


@pytest.mark.parametrize("story_policy", [_writer_fallback], indirect=True)
async def test_a_move_cut_off_after_its_state_was_written_is_finished_by_its_replay(story_host: Host):
    """Review M2: the state's top-up is written first; replaying the same move writes the brief and queues the task."""
    from server.production_run.story_adapter import rerouted_limits
    from server.story_authoring.runtime import top_up

    host = story_host
    await _tick(host)
    await _tick(host)
    task_id = await _story_task(host)
    await _stop(host, task_id)
    before = await _brief(host, task_id)
    [spare] = host.run.policy.fallback_routes
    moved = await host.stories.reroute_brief(
        StoryBrief.model_validate(before.model_dump(mode="json", exclude={"gate_a_decision_id"})),
        provider_id=spare.provider_id,
        model_id=FALLBACK,
        max_cost_minor_units=1,
        project_name="project",
    )
    moved = moved.model_copy(update={"gate_a_decision_id": before.gate_a_decision_id})
    store = RunStateStore(host.sessions, task_id=task_id)
    state = await store.load()
    limits = rerouted_limits(state.limits, moved.limits, state.usage.input_tokens, state.usage.output_tokens)
    # The crash: the state took the move, the task still names the old writer and is not queued.
    await store.apply(
        lambda s: (
            top_up(
                s,
                caller_ref="step-1",
                limits=limits,
                phases=frozenset({RunPhase.MODEL_UNAVAILABLE}),
                grow=False,
                reroute=True,
            ),
            None,
        )
    )
    assert (await _brief(host, task_id)).selection.model_id == MODEL

    run_id = (await store.load()).run_id
    again = await host.stories.reroute(
        user_id="default", project_name="project", run_id=run_id, caller_ref="step-1", brief=moved, limits=limits
    )

    assert len(again.top_ups) == 1
    assert (await _brief(host, task_id)).selection.model_id == FALLBACK
    async with host.sessions() as session:
        task = (await session.execute(sa.select(Task).where(Task.task_id == task_id))).scalar_one()
    assert task.status == "queued"
