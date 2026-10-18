"""Human actions on a story run, end to end on the real owners: brief, Gate A, start, the scripted run,
touchpoint 2, commit, export, hand-off to a real project source, and the lifecycle refusals.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.gates import GreenlightRepository
from lib.project_manager import ProjectManager
from r2.contracts.gates import GateAuthorization, GreenlightDecision
from server.services.governance_grants import CurrentShowrunnerGrantReader
from server.story_authoring.authority import GrantNarrativeShowrunnerAuthority
from server.story_authoring.commit import CommitRefused
from server.story_authoring.driver import StoryBrief
from server.story_authoring.executor import execute_story_run_task
from server.story_authoring.handoff import HandoffRefusal, HandoffRefused, OnConflict
from server.story_authoring.runtime import RunPhase, RunStateStore
from server.story_authoring.service import StoryActionRefused, StoryAuthoringService, StoryRunRef
from server.tool_runtime import (
    CallerContext,
    ProjectScope,
    Services,
    ToolRequest,
    UploadSourceRequest,
    upload_source,
)
from tests.integration.server.story_authoring.test_driver import MODEL, ScriptedModel
from tests.integration.server.story_authoring.test_executor import BASE_URL, _provider
from tests.integration.server.story_authoring.test_narrative import IDENTITY, NOW

type Factory = async_sessionmaker[AsyncSession]

SPONSOR = "sponsor"
PROJECT = IDENTITY.project_name
USER = IDENTITY.user_id


class _Unused:
    pass


def _service(factory: Factory, grants: CurrentShowrunnerGrantReader | None, projects: ProjectManager):
    return StoryAuthoringService(
        session_factory=factory,
        authority=GrantNarrativeShowrunnerAuthority(factory, grants),
        project_dir_for=projects.get_project_path,
        clock=lambda: NOW,
    )


async def _greenlight(factory: Factory, digest: str, action: str = "GREENLIGHT") -> str:
    decision_id = str(uuid.uuid4())
    decision = GreenlightDecision(
        decision_id=decision_id,
        user_id=USER,
        project_name=PROJECT,
        source_digest=digest,
        action=action,
        authorization=GateAuthorization(
            authenticated_principal=SPONSOR, authority_role="HUMAN_OPERATOR", authorized_at=datetime.now(UTC)
        ),
        sequence=1,
        created_at=datetime.now(UTC),
    )
    async with factory() as session:
        await GreenlightRepository(session).append(decision)
        await session.commit()
    return decision_id


async def _brief(service: StoryAuthoringService, factory: Factory) -> StoryBrief:
    provider_id = await _provider(factory)
    return await service.draft_brief(
        idea="Một người con về làng bán căn nhà của cha.", genre="đời thường", provider_id=provider_id, model_id=MODEL
    )


async def _started(service: StoryAuthoringService, factory: Factory) -> StoryRunRef:
    brief = await _brief(service, factory)
    decision = await _greenlight(factory, brief.digest())
    return await service.start(
        user_id=USER, project_name=PROJECT, principal=SPONSOR, brief=brief, gate_a_decision_id=decision
    )


async def _execute(factory: Factory, ref: StoryRunRef, projects: ProjectManager, model: ScriptedModel) -> dict:
    def client_for(base_url: str, api_key: str | None):
        from lib.text_backends.ollama import OllamaChatClient

        assert (base_url, api_key) == (BASE_URL, None)
        return OllamaChatClient(base_url=base_url, transport=httpx.MockTransport(model.handler))

    return await execute_story_run_task(
        PROJECT,
        ref.run_id,
        {"brief": ref.brief.model_dump(mode="json")},
        user_id=USER,
        task_id=ref.task_id,
        session_factory=factory,
        project_dir=projects.get_project_path(PROJECT),
        client_for=client_for,
        clock=lambda: NOW,
    )


def _upload(projects: ProjectManager):
    services = Services(projects=projects, workflow_planner=_Unused(), capabilities=_Unused())
    scope = ProjectScope(project_name=PROJECT, projects_root=projects.projects_root)
    calls: list[str] = []

    async def upload(filename: str, content: str, on_conflict: OnConflict) -> dict[str, object]:
        calls.append(filename)
        outcome = await upload_source(
            ToolRequest(UploadSourceRequest(filename=filename, content=content, on_conflict=on_conflict)),
            scope,
            CallerContext(user_id=USER, source="embedded"),
            services,
        )
        assert outcome.problem is None, outcome.problem
        assert outcome.value is not None
        return outcome.value

    return upload, calls


async def test_a_greenlit_brief_runs_to_an_approved_manuscript_handed_to_video(
    concurrent_session_factory: Factory, grants, projects: ProjectManager
):
    service = _service(concurrent_session_factory, grants, projects)
    ref = await _started(service, concurrent_session_factory)
    assert (await _execute(concurrent_session_factory, ref, projects, ScriptedModel()))["phase"] == "READY_FOR_APPROVAL"

    _, state = await service.get(user_id=USER, project_name=PROJECT, run_id=ref.run_id)
    offered = service.offered(PROJECT, state)
    assert offered is not None
    assert [(s["chapter"], s["scene"]) for s in offered["scenes"]] == [(c, s) for c in (1, 2, 3) for s in (1, 2, 3)]
    assert offered["packaging"]["titles"][0]["title"] == "Căn nhà cũ"

    with pytest.raises(StoryActionRefused, match="NOT_COMMITTED"):
        await service.export(user_id=USER, project_name=PROJECT, run_id=ref.run_id)
    committed = await service.approve(
        user_id=USER,
        project_name=PROJECT,
        run_id=ref.run_id,
        principal=SPONSOR,
        manifest_digest_seen=offered["manifest_digest"],
        accepted_exceptions=offered["exceptions_offered"],
    )
    assert committed.phase is RunPhase.COMMITTED

    export = await service.export(user_id=USER, project_name=PROJECT, run_id=ref.run_id)
    assert export.decode("utf-8").startswith("# Căn nhà cũ\n")

    upload, calls = _upload(projects)
    send = {"user_id": USER, "project_name": PROJECT, "run_id": ref.run_id, "principal": SPONSOR, "upload": upload}
    project = projects.load_project(PROJECT)
    record = await service.send_to_video(command_id="cmd-00000001", project=project, **send)
    again = await service.send_to_video(command_id="cmd-00000001", project=project, **send)

    assert record == again
    assert (record.done, record.path, calls) == (True, "source/can-nha-cu.txt", ["can-nha-cu.md"])
    source = projects.get_project_path(PROJECT) / "source" / "can-nha-cu.txt"
    assert source.read_text(encoding="utf-8") == export.decode("utf-8")
    with pytest.raises(HandoffRefused) as other:
        await service.send_to_video(command_id="cmd-00000002", project=project, **send)
    assert other.value.code is HandoffRefusal.ALREADY_HANDED_OFF

    withdrawn = await service.withdraw(user_id=USER, project_name=PROJECT, run_id=ref.run_id, principal=SPONSOR)
    assert withdrawn.phase is RunPhase.WITHDRAWN
    with pytest.raises(StoryActionRefused, match="NOT_COMMITTED"):
        await service.export(user_id=USER, project_name=PROJECT, run_id=ref.run_id)


async def test_a_pending_hand_off_whose_source_was_written_completes_without_a_second_upload(
    concurrent_session_factory: Factory, grants, projects: ProjectManager
):
    service = _service(concurrent_session_factory, grants, projects)
    ref = await _started(service, concurrent_session_factory)
    await _execute(concurrent_session_factory, ref, projects, ScriptedModel())
    _, state = await service.get(user_id=USER, project_name=PROJECT, run_id=ref.run_id)
    offered = service.offered(PROJECT, state)
    assert offered is not None
    await service.approve(
        user_id=USER,
        project_name=PROJECT,
        run_id=ref.run_id,
        principal=SPONSOR,
        manifest_digest_seen=offered["manifest_digest"],
        accepted_exceptions=offered["exceptions_offered"],
    )
    real_upload, _ = _upload(projects)

    async def crash_after_writing(filename: str, content: str, on_conflict: OnConflict) -> dict[str, object]:
        await real_upload(filename, content, on_conflict)
        raise RuntimeError("process killed after the source was written")

    send = {
        "user_id": USER,
        "project_name": PROJECT,
        "run_id": ref.run_id,
        "principal": SPONSOR,
        "command_id": "cmd-00000001",
    }
    project = projects.load_project(PROJECT)
    with pytest.raises(HandoffRefused):
        await service.send_to_video(project=project, upload=crash_after_writing, **send)

    retry_upload, calls = _upload(projects)
    record = await service.send_to_video(project=project, upload=retry_upload, **send)

    assert (record.done, record.path, calls) == (True, "source/can-nha-cu.txt", [])
    assert sorted(p.name for p in (projects.get_project_path(PROJECT) / "source").iterdir()) == ["can-nha-cu.txt"]


async def test_start_requires_a_current_greenlight_of_this_exact_brief(
    concurrent_session_factory: Factory, grants, projects: ProjectManager
):
    service = _service(concurrent_session_factory, grants, projects)
    brief = await _brief(service, concurrent_session_factory)
    start = {"user_id": USER, "project_name": PROJECT, "principal": SPONSOR, "brief": brief}

    other = await _greenlight(concurrent_session_factory, brief.model_copy(update={"idea": "Ý khác."}).digest())
    with pytest.raises(StoryActionRefused, match="GATE_A_DIGEST_MISMATCH"):
        await service.start(gate_a_decision_id=other, **start)
    with pytest.raises(StoryActionRefused, match="GATE_A_MISSING"):
        await service.start(gate_a_decision_id="no-such-decision", **start)

    decision = await _greenlight(concurrent_session_factory, brief.digest())
    first = await service.start(gate_a_decision_id=decision, **start)
    assert await service.start(gate_a_decision_id=decision, **start) == first

    revoked = await _greenlight(concurrent_session_factory, brief.digest())
    await _greenlight(concurrent_session_factory, brief.digest(), action="REVOKE")
    with pytest.raises(StoryActionRefused, match="GATE_A_SUPERSEDED"):
        await service.start(gate_a_decision_id=revoked, **start)

    with pytest.raises(StoryActionRefused, match="NOT_AUTHORIZED"):
        await service.start(gate_a_decision_id=decision, **{**start, "principal": "intruder"})


async def test_revise_discard_and_retry_follow_the_lifecycle(
    concurrent_session_factory: Factory, grants, projects: ProjectManager
):
    service = _service(concurrent_session_factory, grants, projects)
    ref = await _started(service, concurrent_session_factory)
    act = {"user_id": USER, "project_name": PROJECT, "run_id": ref.run_id, "principal": SPONSOR}

    blocking = ScriptedModel()
    blocking.overrides["working_title"] = lambda _p, _s: {"working_title": "thiếu"}
    assert (await _execute(concurrent_session_factory, ref, projects, blocking))["phase"] == "BLOCKED_QUALITY"
    with pytest.raises(StoryActionRefused, match="ACTION_NOT_ALLOWED"):
        await service.withdraw(**act)

    retried = await service.retry(**act)
    assert retried.phase is RunPhase.RUNNING
    assert retried.node("seed").generation_epoch == 2
    assert (await _execute(concurrent_session_factory, ref, projects, ScriptedModel()))["phase"] == "READY_FOR_APPROVAL"

    with pytest.raises(StoryActionRefused, match="UNKNOWN_TARGET"):
        await service.revise(target="scene_draft[9,9]", note="x", **act)
    revised = await service.revise(target="chapter[2]", note="Cho Lan nói nhiều hơn.", **act)
    assert revised.phase is RunPhase.RUNNING
    assert revised.intents["scene_draft[2,1]"] == ("Cho Lan nói nhiều hơn.",)
    assert (await _execute(concurrent_session_factory, ref, projects, ScriptedModel()))["phase"] == "READY_FOR_APPROVAL"

    discarded = await service.discard(**act)
    assert discarded.phase is RunPhase.DISCARDED
    offered = service.offered(PROJECT, discarded)
    assert offered is not None
    with pytest.raises(CommitRefused):
        await service.approve(
            manifest_digest_seen=offered["manifest_digest"], accepted_exceptions=offered["exceptions_offered"], **act
        )
    store = RunStateStore(concurrent_session_factory, task_id=ref.task_id)
    assert (await store.load()).phase is RunPhase.DISCARDED
