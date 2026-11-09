"""Production run routes on real interactive auth, signed Governance custody and PostgreSQL run rows."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.production_run import ProductionPolicyModel
from lib.db.repositories.automation_grants import AutomationGrantRepository
from lib.db.repositories.production_runs import ProductionRunRepository
from r2.automation.identity import policy_digest
from r2.contracts.automation import (
    AutomationMode,
    Checkpoint,
    PreflightReport,
    RunPolicy,
    RunScope,
    RunStage,
)
from server import auth
from server.error_handlers import register_error_handlers
from server.production_run.controller import ProductionController
from server.production_run.scheduler import ProductionScheduler
from server.production_run.service import (
    ProductionActivation,
    ProductionRunRefused,
    ProductionRunService,
    policy_for_mode,
)
from server.routers import production_runs
from tests.auth_deps import AUTH_DEPENDENCIES
from tests.integration.lib.db.repositories.test_production_runs import policy
from tests.integration.server.production_run.test_controller_recovery import INPUT, FakeOwner, Witness
from tests.integration.server.services.test_automation_grants import custodian
from tests.integration.server.services.test_automation_grants import interactive_env as interactive_env
from tests.integration.server.services.test_quality_profile_custodian import prepare_qualified_custody

PROJECT = "project"
BASE = "/api/v1/projects/project/production-runs"


class Policies:
    def __init__(self) -> None:
        self.refusal: ProductionRunRefused | None = None
        self.semi_checkpoints = frozenset({Checkpoint.STORY_MANUSCRIPT})
        self.semi_limits: dict[str, int] = {}

    async def resolve(self, *, user_id, project_name, mode):
        if self.refusal is not None:
            raise self.refusal
        if mode is AutomationMode.SEMI:
            return RunPolicy.model_validate(
                {**policy().model_dump(), **self.semi_limits, "mode": mode, "checkpoints": self.semi_checkpoints}
            )
        return policy()


class Preflight:
    def __init__(self) -> None:
        self.reasons: tuple[str, ...] = ()

    async def check(self, *, user_id, project_name, policy):
        return PreflightReport(
            user_id=user_id,
            project_name=project_name,
            input_digest=INPUT,
            policy_digest=policy_digest(policy),
            route_digests=policy.route_digests,
            dispatch_allowed=not self.reasons,
            blocking_reasons=self.reasons,
            checked_at=datetime.now(UTC),
        )


@dataclass
class Host:
    http: AsyncClient
    sessions: async_sessionmaker[AsyncSession]
    scheduler: ProductionScheduler
    owner: FakeOwner
    witness: Witness
    preflight: Preflight
    policies: Policies
    custodian: Any = None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {auth.create_token('actor')}"}

    async def start(self, *, command_id="start-command-1", mode="auto", idea="Chuyến đò cuối.", targets=None):
        offer = (await self.http.get(BASE, headers=self.headers)).json()["start"]
        body = {
            "command_id": command_id,
            "mode": mode,
            "idea": idea,
            "expected_input_digest": offer["input_digest"],
            "policy_digest": offer["policy_digests"][mode],
        }
        if targets is not None:
            body["targets"] = targets
        return await self.http.post(BASE, json=body, headers=self.headers)

    async def command(self, run: dict, action: str, *, command_id: str, **changes):
        body = {
            "command_id": command_id,
            "expected_version": run["version"],
            "expected_input_digest": run["input_digest"],
            "policy_digest": run["policy_digest"],
            **changes,
        }
        return await self.http.post(f"{BASE}/{run['run_id']}/{action}", json=body, headers=self.headers)

    async def read(self, run: dict) -> dict:
        return (await self.http.get(f"{BASE}/{run['run_id']}", headers=self.headers)).json()

    async def grant(self, run: dict):
        async with self.sessions() as session:
            return await AutomationGrantRepository(session).head(
                RunScope(user_id=run["user_id"], project_name=run["project_name"], run_id=run["run_id"])
            )


@pytest.fixture
async def host(concurrent_session_factory, tmp_path, interactive_env):
    from server.services.governance_attestation import serve_governance_attestor

    sessions = concurrent_session_factory
    root, runtime, *_ = await prepare_qualified_custody(sessions, tmp_path)
    async with serve_governance_attestor(
        root, runtime, session_factory=sessions, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        owner, witness, preflight, policies = FakeOwner(), Witness(), Preflight(), Policies()
        controller = ProductionController(
            sessions, adapters=dict.fromkeys(RunStage, owner), witness=witness, poll_seconds=0
        )
        scheduler = ProductionScheduler(sessions, controller, owner_id="host", max_runs_per_scan=1)
        app = FastAPI()
        grants = custodian(sessions, root, runtime)
        app.state.production_run_service = ProductionRunService(
            sessions,
            custodian=grants,
            policies=policies,
            witness=witness,
            preflight=preflight,
            activation=ProductionActivation(enabled=True),
            on_change=scheduler.wake,
            has_story=_has_story,
        )
        app.include_router(production_runs.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
        register_error_handlers(app)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            yield Host(http, sessions, scheduler, owner, witness, preflight, policies, grants)


async def test_double_start_and_lost_response_retry_return_one_run_and_one_grant(host):
    first, second = await asyncio.gather(host.start(), host.start())
    retry = await host.start()

    assert first.status_code == second.status_code == retry.status_code == 200, first.text
    assert first.json()["run_id"] == second.json()["run_id"] == retry.json()["run_id"]
    grant = await host.grant(first.json())
    assert grant is not None
    assert (grant.version, grant.state, grant.issuer_id) == (1, "ACTIVE", "actor")
    assert grant.principal != "actor"
    runs = (await host.http.get(BASE, headers=host.headers)).json()["runs"]
    assert [run["run_id"] for run in runs] == [first.json()["run_id"]]


async def test_the_offer_names_the_episode_limit_and_a_start_beyond_it_is_refused(host):
    offer = (await host.http.get(BASE, headers=host.headers)).json()["start"]

    refused = await host.start(targets=["episode:1", "episode:2"])

    assert offer["max_target_episodes"] == 1
    assert refused.status_code == 422, refused.text
    assert (await host.http.get(BASE, headers=host.headers)).json()["runs"] == []


async def test_a_runs_report_is_empty_before_quality_and_story_and_unknown_runs_are_not_found(host):
    response = await host.start()
    assert response.status_code == 200, response.text
    started = response.json()

    report = await host.http.get(f"{BASE}/{started['run_id']}/report", headers=host.headers)
    missing = await host.http.get(f"{BASE}/no-such-run/report", headers=host.headers)

    assert report.status_code == 200, report.text
    assert report.json() == {"run_id": started["run_id"], "quality": [], "story_exceptions": [], "previews": []}
    assert missing.status_code == 404
    progress = await host.http.get(f"{BASE}/{started['run_id']}/progress", headers=host.headers)
    body = progress.json()
    assert datetime.fromisoformat(body.pop("started_at")) == datetime.fromisoformat(started["created_at"])
    assert body == {"run_id": started["run_id"], "stage": "BRIEF", "stages": [], "tasks": {}}
    preview = await host.http.get(f"{BASE}/{started['run_id']}/outputs/1/final", headers=host.headers)
    assert preview.status_code == 404


async def test_progress_names_when_each_passed_stage_finished(host):
    run = (await host.start()).json()
    await host.scheduler.scan_once()
    await host.scheduler.scan_once()

    progress = (await host.http.get(f"{BASE}/{run['run_id']}/progress", headers=host.headers)).json()

    started = datetime.fromisoformat(progress["started_at"])
    finished = [(item["stage"], datetime.fromisoformat(item["finished_at"])) for item in progress["stages"]]
    assert [stage for stage, _ in finished][:1] == ["BRIEF"], progress
    assert progress["stage"] != "BRIEF"
    assert all(started <= at for _, at in finished)
    assert [at for _, at in finished] == sorted(at for _, at in finished)


async def test_readiness_names_preflight_reasons_and_the_policy_a_start_would_freeze(host):
    ready = (await host.http.get("/api/v1/projects/project/automation/readiness", headers=host.headers)).json()
    host.preflight.reasons = ("MISSING_QUALIFIED_REVIEWER",)
    blocked = (await host.http.get("/api/v1/projects/project/automation/readiness", headers=host.headers)).json()

    assert (ready["ready"], ready["reasons"]) == (True, [])
    assert ready["limits"]["max_target_episodes"] == 1
    assert (blocked["ready"], blocked["reasons"]) == (False, ["MISSING_QUALIFIED_REVIEWER"])


async def test_a_project_without_automation_settings_is_offered_nothing_instead_of_failing(host):
    host.policies.refusal = ProductionRunRefused(
        "AUTOMATION_NOT_CONFIGURED", 409, ("PROJECT_AUTOMATION_SETTINGS_MISSING",)
    )

    listed = await host.http.get(BASE, headers=host.headers)

    assert listed.status_code == 200, listed.text
    assert listed.json()["start"] == {
        "enabled": False,
        "reason": "AUTOMATION_NOT_CONFIGURED",
        "reasons": ["PROJECT_AUTOMATION_SETTINGS_MISSING"],
    }


async def test_same_start_command_with_a_changed_idea_conflicts(host):
    assert (await host.start()).status_code == 200

    replay = await host.start(idea="Một câu chuyện khác.")

    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == "COMMAND_REPLAY_CONFLICT"


async def test_start_requires_an_authenticated_session(host):
    response = await host.http.post(
        BASE,
        json={
            "command_id": "start-command-1",
            "idea": "x",
            "expected_input_digest": INPUT,
            "policy_digest": policy_digest(policy()),
        },
    )
    assert response.status_code == 401


STORIES = {"has": True}


async def _has_story(_project_name: str) -> bool:
    return STORIES["has"]


async def test_a_run_from_the_projects_story_needs_no_idea_and_starts_at_asset_analysis(host):
    offer = (await host.http.get(BASE, headers=host.headers)).json()["start"]
    body = {
        "command_id": "start-from-project",
        "story_source": "project",
        "expected_input_digest": offer["input_digest"],
        "policy_digest": offer["policy_digests"]["auto"],
    }
    both = await host.http.post(BASE, json={**body, "idea": "Chuyến đò cuối."}, headers=host.headers)
    assert both.status_code == 422
    STORIES["has"] = False
    try:
        missing = await host.http.post(BASE, json=body, headers=host.headers)
    finally:
        STORIES["has"] = True
    assert (missing.status_code, missing.json()["detail"]["code"]) == (409, "PROJECT_SOURCE_MISSING")
    started = await host.http.post(BASE, json=body, headers=host.headers)
    assert started.status_code == 200, started.text
    assert started.json()["stage"] == "ASSET_ANALYSIS"


@pytest.mark.parametrize("moved", ["input", "policy", "preflight"])
async def test_start_refuses_moved_input_policy_or_failed_preflight(host, moved):
    offer = (await host.http.get(BASE, headers=host.headers)).json()["start"]
    body = {
        "command_id": "start-command-1",
        "idea": "Chuyến đò cuối.",
        "expected_input_digest": offer["input_digest"],
        "policy_digest": offer["policy_digests"]["auto"],
    }
    if moved == "input":
        host.witness.value = "sha256:" + "e" * 64
    elif moved == "policy":
        body["policy_digest"] = offer["policy_digests"]["semi"]
    else:
        host.preflight.reasons = ("DISK_CAPACITY_INSUFFICIENT",)

    response = await host.http.post(BASE, json=body, headers=host.headers)

    assert response.status_code == 409
    assert (
        response.json()["detail"]["code"]
        == {
            "input": "INPUT_MOVED",
            "policy": "POLICY_MOVED",
            "preflight": "PREFLIGHT_BLOCKED",
        }[moved]
    )
    assert (await host.http.get(BASE, headers=host.headers)).json()["runs"] == []


async def test_pause_resume_and_cancel_follow_the_run_and_renew_on_resume(host):
    run = (await host.start()).json()

    paused = await host.command(run, "pause", command_id="pause-command-1")
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "PAUSED"
    replay = await host.command(run, "pause", command_id="pause-command-1")
    assert replay.json()["version"] == paused.json()["version"]
    assert await host.scheduler.scan_once() == 0

    resumed = await host.command(paused.json(), "resume", command_id="resume-command-1")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "RUNNING"
    grant = await host.grant(run)
    assert grant is not None
    assert (grant.version, grant.state, grant.start_command_id) == (2, "ACTIVE", "start-command-1")

    cancelled = await host.command(resumed.json(), "cancel", command_id="cancel-command-1")
    assert cancelled.json()["status"] == "CANCELLED"
    again = await host.command(cancelled.json(), "resume", command_id="resume-command-2")
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "RUN_NOT_RESUMABLE"
    assert host.owner.provider_submit_count == 0


async def test_mode_change_needs_a_paused_boundary_and_records_a_new_policy_and_grant(host):
    run = (await host.start()).json()
    semi = run["mode_policy_digests"]["semi"]

    early = await host.command(run, "mode", command_id="mode-command-1", mode="semi", policy_digest=semi)
    assert early.status_code == 409
    assert early.json()["detail"]["code"] == "MODE_CHANGE_REQUIRES_PAUSE"

    paused = (await host.command(run, "pause", command_id="pause-command-1")).json()
    changed = await host.command(paused, "mode", command_id="mode-command-2", mode="semi", policy_digest=semi)

    assert changed.status_code == 200, changed.text
    view = changed.json()
    assert (view["status"], view["policy"]["mode"], view["policy_digest"]) == ("PAUSED", "semi", semi)
    assert set(view["policy"]["checkpoints"]) == {"SCRIPT_PACKAGE", "FINAL_FILM"}
    grant = await host.grant(run)
    assert grant is not None
    assert (grant.version, grant.policy_digest) == (2, semi)
    async with host.sessions() as session:
        stored = await session.scalar(sa.select(sa.func.count()).select_from(ProductionPolicyModel))
    assert stored == 2
    assert policy_for_mode(policy(), AutomationMode.SEMI).mode is AutomationMode.SEMI


async def test_mode_change_refuses_a_digest_for_another_policy(host):
    run = (await host.start()).json()
    paused = (await host.command(run, "pause", command_id="pause-command-1")).json()

    response = await host.command(
        paused, "mode", command_id="mode-command-1", mode="semi", policy_digest=run["mode_policy_digests"]["auto"]
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "POLICY_MOVED"


async def test_semi_review_approves_only_the_exact_pending_checkpoint(host):
    run = (await host.start(mode="semi")).json()
    await host.scheduler.scan_once()
    await host.scheduler.scan_once()
    waiting = await host.read(run)
    assert waiting["status"] == "WAITING_REVIEW", waiting
    pending = waiting["pending_review"]
    body = {
        "command_id": "review-command-1",
        "expected_version": waiting["version"],
        "checkpoint": pending["checkpoint"],
        "binding_digest": pending["binding_digest"],
        "decision": "APPROVE",
    }

    wrong = await host.http.post(
        f"{BASE}/{run['run_id']}/review",
        json={**body, "command_id": "review-command-0", "binding_digest": "sha256:" + "0" * 64},
        headers=host.headers,
    )
    assert wrong.status_code == 409
    approved = await host.http.post(f"{BASE}/{run['run_id']}/review", json=body, headers=host.headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "RUNNING"
    [approval] = approved.json()["review_approvals"]
    assert (approval["checkpoint"], approval["actor_id"]) == ("STORY_MANUSCRIPT", "actor")
    replay = await host.http.post(f"{BASE}/{run['run_id']}/review", json=body, headers=host.headers)
    assert replay.json()["version"] == approved.json()["version"]

    submitted = host.owner.provider_submit_count
    await host.scheduler.scan_once()
    assert (await host.read(run))["stage"] == "STORY_COMMIT"
    assert host.owner.provider_submit_count == submitted


async def _waiting_review(host, run: dict) -> dict:
    for _ in range(40):
        current = await host.read(run)
        if current["status"] == "WAITING_REVIEW":
            return current
        await host.scheduler.scan_once()
    raise AssertionError(await host.read(run))


async def test_a_final_film_review_can_send_the_final_back_to_media_as_a_new_generation(host):
    host.policies.semi_checkpoints = frozenset({Checkpoint.FINAL_FILM})
    # Two passes through MEDIA..QUALITY plus the stages before them.
    host.policies.semi_limits = {"max_cost_minor_units": 1000, "max_model_calls": 100, "max_tasks": 100}
    host.owner.states[RunStage.QUALITY] = "PASS"
    dispatched: list[tuple[str, int]] = []
    owner_dispatch = host.owner.dispatch

    async def recording_dispatch(intent):
        dispatched.append((intent.identity.stage.value, intent.identity.generation))
        return await owner_dispatch(intent)

    host.owner.dispatch = recording_dispatch
    run = (await host.start(mode="semi")).json()
    waiting = await _waiting_review(host, run)
    pending = waiting["pending_review"]
    assert (waiting["stage"], pending["checkpoint"]) == ("QUALITY", "FINAL_FILM"), waiting
    before_rework = len(dispatched)
    body = {
        "command_id": "review-rework-1",
        "expected_version": waiting["version"],
        "checkpoint": pending["checkpoint"],
        "binding_digest": pending["binding_digest"],
        "decision": "REWORK",
    }

    reworked = await host.http.post(f"{BASE}/{run['run_id']}/review", json=body, headers=host.headers)

    assert reworked.status_code == 200, reworked.text
    view = reworked.json()
    assert (view["status"], view["stage"], view["generation"]) == ("RUNNING", "MEDIA", waiting["generation"] + 1)
    assert view["pending_review"] is None
    assert view["completed_targets"] == []
    again = await _waiting_review(host, run)
    assert again["pending_review"]["checkpoint"] == "FINAL_FILM"
    assert again["pending_review"]["binding_digest"] != pending["binding_digest"]
    # Every stage from MEDIA to QUALITY ran again as the new generation; nothing before MEDIA ran again.
    redone = sorted(set(dispatched[before_rework:]), key=lambda item: list(RunStage).index(RunStage(item[0])))
    generation = waiting["generation"] + 1
    assert redone == [(stage, generation) for stage in ("MEDIA", "RENDER", "MASTER", "QUALITY")]
    # Later stages read the new generation's outcomes, not the earlier generation's.
    async with host.sessions() as session:
        repository = ProductionRunRepository(session)
        snapshot = await repository.get(user_id=run["user_id"], project_name=run["project_name"], run_id=run["run_id"])
        assert snapshot is not None
        for stage in (RunStage.MEDIA, RunStage.RENDER, RunStage.MASTER):
            outcome = await repository.stage_outcome(run=snapshot, stage=stage)
            assert outcome is not None
            assert outcome.generation == generation
        script = await repository.stage_outcome(run=snapshot, stage=RunStage.SCRIPT)
        assert script is not None
        assert script.generation == waiting["generation"]


async def test_rework_is_refused_at_a_checkpoint_before_the_final(host):
    run = (await host.start(mode="semi")).json()
    waiting = await _waiting_review(host, run)
    pending = waiting["pending_review"]
    assert pending["checkpoint"] == "STORY_MANUSCRIPT"

    refused = await host.http.post(
        f"{BASE}/{run['run_id']}/review",
        json={
            "command_id": "review-rework-2",
            "expected_version": waiting["version"],
            "checkpoint": pending["checkpoint"],
            "binding_digest": pending["binding_digest"],
            "decision": "REWORK",
        },
        headers=host.headers,
    )

    assert refused.status_code == 422, refused.text
    assert (await host.read(run))["status"] == "WAITING_REVIEW"


async def test_external_edit_blocks_and_only_a_digest_bound_resume_starts_a_new_lineage(host):
    run = (await host.start()).json()
    new_input = "sha256:" + "e" * 64
    host.witness.value = new_input
    await host.scheduler.scan_once()
    blocked = await host.read(run)
    assert (blocked["status"], blocked["reason"]) == ("BLOCKED_INPUT_CHANGED", "EXTERNAL_INPUT_CHANGED")

    other = await host.command(
        blocked, "resume", command_id="resume-command-1", expected_input_digest="sha256:" + "f" * 64
    )
    assert other.status_code == 409
    assert other.json()["detail"]["code"] == "INPUT_MOVED"

    rebound = await host.command(blocked, "resume", command_id="resume-command-2", expected_input_digest=new_input)
    assert rebound.status_code == 200, rebound.text
    view = rebound.json()
    assert (view["input_digest"], view["generation"], view["stage"]) == (new_input, 2, "BRIEF")
    grant = await host.grant(run)
    assert grant is not None
    assert (grant.version, grant.input_digest) == (2, new_input)
    await host.scheduler.scan_once()
    assert (await host.read(run))["stage"] == "STORY"


async def test_read_payload_carries_no_tokens_or_provider_secrets(host):
    run = (await host.start()).json()

    response = await host.http.get(f"{BASE}/{run['run_id']}", headers=host.headers)

    assert response.status_code == 200
    assert {"status", "stage", "reason", "policy", "completed_targets", "mode_policy_digests"} <= response.json().keys()
    text = response.text.lower()
    assert "bearer" not in text
    assert "token" not in text
    assert "credential" not in text


async def test_unwired_host_reads_runs_but_refuses_commands(concurrent_session_factory, interactive_env, monkeypatch):
    monkeypatch.setattr(production_runs, "async_session_factory", concurrent_session_factory)
    app = FastAPI()
    app.include_router(production_runs.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    headers = {"Authorization": f"Bearer {auth.create_token('actor')}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        listed = await http.get(BASE, headers=headers)
        started = await http.post(
            BASE,
            json={
                "command_id": "start-command-1",
                "idea": "x",
                "expected_input_digest": INPUT,
                "policy_digest": policy_digest(policy()),
            },
            headers=headers,
        )

    assert listed.status_code == 200
    assert listed.json() == {"start": {"enabled": False, "reason": "RELEASE_GATE_PENDING"}, "runs": []}
    assert started.status_code == 503
    assert started.json()["detail"]["code"] == "AUTOMATIC_PRODUCTION_NOT_ACTIVATED"


async def test_start_retry_after_a_mode_change_returns_the_same_run(host):
    run = (await host.start()).json()
    paused = (await host.command(run, "pause", command_id="pause-command-1")).json()
    semi = run["mode_policy_digests"]["semi"]
    assert (
        await host.command(paused, "mode", command_id="mode-command-1", mode="semi", policy_digest=semi)
    ).status_code == 200

    retry = await host.http.post(
        BASE,
        json={
            "command_id": "start-command-1",
            "mode": "auto",
            "idea": "Chuyến đò cuối.",
            "expected_input_digest": run["input_digest"],
            "policy_digest": run["policy_digest"],
        },
        headers=host.headers,
    )

    assert retry.status_code == 200, retry.text
    assert (retry.json()["run_id"], retry.json()["policy"]["mode"]) == (run["run_id"], "semi")


async def test_a_succeeded_runs_archive_downloads_only_verified_and_only_in_its_project(host, tmp_path, monkeypatch):
    import hashlib

    from lib.db.models.production_run import ProductionRunModel
    from lib.project_manager import ProjectManager
    from r2.contracts.automation import OwnerReceipt, RunSnapshot, RunStatus, TargetOutput
    from server.routers import production_runs as routes

    run = (await host.start()).json()
    projects = ProjectManager(tmp_path / "projects")
    archive = tmp_path / "projects" / run["project_name"] / "production" / "automation" / "episode_1.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"verified-archive")
    digest = "sha256:" + hashlib.sha256(b"verified-archive").hexdigest()
    monkeypatch.setattr(routes, "get_project_manager", lambda: projects)
    receipt = OwnerReceipt(
        owner="export", receipt_ref="episode:1:archive@production/automation/episode_1.zip", digest=digest
    )
    async with host.sessions() as session, session.begin():
        row = await session.get(ProductionRunModel, run["run_id"])
        snapshot = RunSnapshot.model_validate_json(row.snapshot_json)
        succeeded = snapshot.model_copy(
            update={
                "status": RunStatus.SUCCEEDED,
                "completed_targets": (
                    TargetOutput(
                        target="episode:1",
                        generation=snapshot.generation,
                        input_digest=snapshot.input_digest,
                        policy_digest=run["policy_digest"],
                        master_digest=digest,
                        quality_run=receipt,
                        quality_decision="PASS",
                        export=receipt,
                        final_digest=digest,
                        archive_digest=digest,
                        archive_size=len(b"verified-archive"),
                        verified=True,
                    ),
                ),
            }
        )
        row.snapshot_json, row.status = succeeded.model_dump_json(), "SUCCEEDED"
    url = f"{BASE}/{run['run_id']}/outputs/1"

    ok = await host.http.get(url, headers=host.headers)
    other = await host.http.get(url.replace(run["project_name"], "another-project"), headers=host.headers)
    anonymous = await host.http.get(url)
    archive.write_bytes(b"substituted-archive")
    changed = await host.http.get(url, headers=host.headers)

    assert (ok.status_code, ok.content) == (200, b"verified-archive")
    assert other.status_code == 404
    assert anonymous.status_code == 401
    assert changed.status_code == 409


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        (
            "PUT",
            "automation/settings",
            {
                "launch_profile_id": "fiction_narration_vi_v1",
                "routes": [
                    {"role": role, "provider_id": "custom-1", "model_id": "m"}
                    for role in ("writer", "script", "reviewer_a", "reviewer_b", "image", "video", "audio")
                ],
            },
        ),
        ("POST", "automation/qualification/reviewers", None),
        ("POST", "automation/qualification/launch", None),
    ],
    ids=["settings", "reviewer-qualification", "launch-qualification"],
)
async def test_setup_and_qualification_need_the_projects_showrunner(host, method, path, body):
    stranger = {"Authorization": f"Bearer {auth.create_token('intruder')}"}

    response = await host.http.request(method, f"/api/v1/projects/project/{path}", json=body, headers=stranger)

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "NOT_AUTHORIZED"


async def test_a_queued_task_of_a_run_executes_only_while_the_run_may_still_act(host):
    from lib.db.repositories.task_repo import TaskRepository
    from server.production_run.execution_guard import (
        RunTaskRefused,
        configure_run_task_authority,
        require_run_task_authorized,
    )

    run = (await host.start()).json()
    async with host.sessions() as session:
        queued = await TaskRepository(session).enqueue(
            project_name=run["project_name"],
            task_type="text_script_plan",
            media_type="text",
            resource_id="episode-1",
            payload={},
            user_id=run["user_id"],
            actor_scope=f"production-run:{run['run_id']}",
            command_id="step-1:script-plan:1",
            command_digest="sha256:" + "d" * 64,
        )
        await session.commit()

    configure_run_task_authority(None)
    async with host.sessions() as session:
        with pytest.raises(RunTaskRefused, match="AUTOMATION_GOVERNANCE_NOT_ACTIVATED"):
            await require_run_task_authorized(session, queued)

    configure_run_task_authority(host.custodian.authority())
    try:
        async with host.sessions() as session:
            await require_run_task_authorized(session, queued)
        async with host.sessions() as session:
            await require_run_task_authorized(session, {"task_id": "a-task-no-run-submitted"})

        paused = await host.command(run, "pause", command_id="pause-command-1")
        assert paused.status_code == 200, paused.text

        async with host.sessions() as session:
            with pytest.raises(RunTaskRefused, match="AUTOMATION_AUTHORITY_NOT_CURRENT"):
                await require_run_task_authorized(session, queued)
    finally:
        configure_run_task_authority(None)
