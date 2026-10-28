"""Run closure on real PostgreSQL: real A4 receipts, a qualified showrunner observation and sealed runs.

Profile, master, manifest and governance rows are fixture state seeded through existing repositories and
the real signed/checkpointed governance archive; they confer no Human authority beyond the test.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import r2.contracts.quality as q
from lib.db.models.quality_runs import QualityHumanObservationModel, QualityRunModel
from r2.advanced_creative.exploration import uuid7
from r2.quality.digests import compute_digest
from r2.quality.errors import (
    CommandReplayConflictError,
    RequiredEvidenceMissingError,
    SubjectStaleError,
)
from r2.quality.probes import ProbeCatalog
from r2.quality.runs import HumanObservationRequest
from server import auth
from server.services import quality_probe_runtime as runtime
from server.services.governance_attestation import serve_governance_attestor
from server.services.governance_startup import verify_governance_activated_startup
from server.services.quality_runs import HumanObservationService, QualityRunService, run_validity
from tests.integration.lib.db.repositories.test_quality_profiles_repository import append, request_for
from tests.integration.server.services.test_quality_probe_recipes import FIXTURES, config_for, host
from tests.integration.server.services.test_quality_probe_runtime import sha
from tests.integration.server.services.test_quality_probes import ACTOR, bound_policy, probe_request, promote
from tests.integration.server.services.test_quality_probes import service as probe_service
from tests.integration.server.services.test_quality_profile_custodian import SECRET, prepare_qualified_custody
from tests.unit.r2.quality.test_runs import human_slot, requirement, technical_slot

type Factory = async_sessionmaker[AsyncSession]
ROOT = Path(__file__).resolve().parents[4]
# The governance custody fixture already installs the A3 publication triggers.
MIGRATIONS = ("07fd34535384_quality_probe_evidence.py", "57f67bae0cb4_quality_run_closure.py")


def install(name: str):
    spec = importlib.util.spec_from_file_location("m10_fixture_" + name[:12], ROOT / "alembic/versions" / name)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.install_immutability


def policy_for(config) -> dict[str, Any]:
    policy = bound_policy(config)
    policy["assessment_requirements"] = [
        requirement("technical-required", [technical_slot()]),
        requirement("review-required", [human_slot("human")]),
    ]
    return policy


@pytest.fixture
async def closure_host(session_factory: Factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tests.unit.r2.contracts.test_quality import binding_data

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", SECRET)
    factory = session_factory
    async with factory() as session, session.begin():
        if session.get_bind().dialect.name != "postgresql":
            pytest.skip("run custody requires real PostgreSQL")
        connection = await session.connection()
        for name in MIGRATIONS:
            await connection.run_sync(install(name))
    (tmp_path / "governance").mkdir(mode=0o700)
    root_dir, socket_dir, *_ = await prepare_qualified_custody(factory, tmp_path / "governance")
    project = tmp_path / "project"
    project.mkdir(mode=0o700)
    (tmp_path / "work").mkdir(mode=0o700)
    config = config_for("DECODE")
    profile = await append(factory, request_for(1, "publish-1", policy=policy_for(config)))
    root = await promote(factory, project, FIXTURES / "av.mp4", "1")
    dependency = await promote(
        factory,
        project,
        FIXTURES / "video_only.mp4",
        "dep-1",
        key=binding_data()["dependency_heads"][0]["artifact_key"],
    )

    async def reader():
        return await verify_governance_activated_startup(
            root_dir / "read", socket_dir, session_factory=factory, expected_uid=os.getuid(), expected_gid=os.getgid()
        )

    env: dict[str, Any] = {
        "factory": factory,
        "project": project,
        "config": config,
        "profile": profile,
        "root": root,
        "dependency": dependency,
        "selected": {root.artifact_key: "candidate-1", dependency.artifact_key: "candidate-dep-1"},
        "runtime": runtime.QualityProbeRuntime(
            runtime.ProbeHost(tools=host().tools, vmaf_model=host().vmaf_model, work_root=tmp_path / "work")
        ),
        "catalog": ProbeCatalog(schema_id="m10.probe-catalog.v1", configs=(config,)),
        "reader": reader,
    }
    write_manifest(project, subject_of(env))
    async with serve_governance_attestor(
        root_dir, socket_dir, session_factory=factory, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        yield env


def probe_for(env, profile=None):
    return probe_request(
        profile or env["profile"],
        env["root"],
        requirement_id="technical-required",
        dependencies=(env["dependency"],),
        selected=env["selected"],
    )


def subject_of(env) -> q.AssessedSubject:
    return probe_for(env).subject


def write_manifest(project: Path, subject: q.AssessedSubject, *, change: dict[str, Any] | None = None) -> None:
    from lib.artifact_manifest import ArtifactKey, ArtifactManifestEntry, ProjectArtifactManifestAdapter
    from r2.contracts.quality import decode_episode_video_key

    adapter = ProjectArtifactManifestAdapter(project)
    for snapshot in subject.master_binding.metadata_snapshots:
        episode, resource = decode_episode_video_key(snapshot.artifact_key)
        body = snapshot.body.model_dump(mode="json") | (change or {})
        adapter.put_entry(
            ArtifactKey.episode_video(episode, resource),
            ArtifactManifestEntry(
                artifact_path=f"videos/episode_{episode}/{resource}.mp4", basis_digest="sha256-v1:" + "e" * 64, r2=body
            ),
        )


async def technical(env, profile=None) -> q.TechnicalObservation:
    request = probe_for(env, profile)
    return await (await probe_service(env, request)).observe(request)


def human_request(env, *, command_id: str = "human-1", profile=None, **changes: Any) -> HumanObservationRequest:
    return HumanObservationRequest.model_validate(
        {
            "user_id": "default",
            "project_name": "project",
            "actor_id": ACTOR,
            "command_id": command_id,
            "subject": subject_of(env).model_dump(mode="json"),
            "profile": (profile or env["profile"]).model_dump(mode="json"),
            "requirement_id": "review-required",
            "slot_id": "human",
            "status": "PASS",
            "rubric_id": "rubric",
            "rubric_digest": sha(b"rubric"),
            "segment_closure_digest": sha(b"segments"),
            "reviewer_evidence_digest": sha(b"notes"),
            "findings": [],
            "evidence_refs": ["review-notes"],
            "evidence_digest": sha(b"notes"),
        }
        | changes
    )


async def human(env, request, *, token: str | None = "default", actor: str = ACTOR, clock=None):
    service = await HumanObservationService.for_request(
        request,
        env["factory"],
        interactive_token=auth.create_token(actor) if token == "default" else token,
        grant_reader=env["reader"],
        project_root=env["project"],
        clock=clock,
    )
    return await service.record(request)


def completion(env, observations, *, command_id: str = "seal-1", profile=None) -> q.CompleteRunCommand:
    profile = profile or env["profile"]
    subject = subject_of(env)
    bindings = tuple(
        q.ObservationBinding(
            observation_id=o.observation_id,
            observation_type=o.observation_type,
            observation_digest=compute_digest(
                "m10.technical-observation.v1"
                if o.observation_type == q.ObservationType.TECHNICAL
                else "m10.narrative-observation.v1",
                o,
            ),
            requirement_id=o.requirement_id,
            slot_id=o.slot_id,
        )
        for o in observations
    )
    ordered = q.RunCompletionSubject.observation_order(bindings)
    body: dict[str, Any] = {
        "command": {
            "user_id": "default",
            "project_name": "project",
            "actor_id": ACTOR,
            "operation": "COMPLETE_RUN",
            "command_id": command_id,
            "request_digest": "sha256:" + "0" * 64,
        },
        "subject": {
            "user_id": "default",
            "project_name": "project",
            "actor_id": ACTOR,
            "run_id": uuid7(),
            "subject": subject.model_dump(mode="json"),
            "subject_digest": compute_digest("m10.assessed-subject.v1", subject),
            "profile_id": profile.profile_id,
            "profile_revision": profile.revision,
            "profile_digest": profile.profile_digest,
            "observations": [b.model_dump(mode="json") for b in ordered],
            "observation_closure_digest": compute_digest("m10.observation-closure.v1", ordered),
            "requirements_digest": compute_digest(
                "m10.assessment-requirements.v1", profile.policy.assessment_requirements
            ),
            "execution_refs": sorted(
                o.probe_receipt_ref for o in observations if isinstance(o, q.TechnicalObservation)
            ),
        },
    }
    body["command"]["request_digest"] = compute_digest("m10.run-completion-request.v1", body)
    return q.CompleteRunCommand.model_validate(body)


async def seal(env, command: q.CompleteRunCommand, *, reader=None) -> q.QualityRun:
    service = await QualityRunService.for_request(
        command,
        env["factory"],
        interactive_token=auth.create_token(ACTOR),
        grant_reader=reader or env["reader"],
        project_root=env["project"],
    )
    return await service.complete(command)


async def validity(env, run: q.QualityRun) -> str:
    result = await run_validity(
        env["factory"],
        env["reader"],
        project_root=env["project"],
        user_id="default",
        project_name="project",
        run_id=run.run_id,
    )
    return result.state


async def sealed(env, command_id: str = "seal-1") -> q.QualityRun:
    probe = await technical(env)
    review = await human(env, human_request(env))
    return await seal(env, completion(env, [probe, review], command_id=command_id))


async def test_qualified_human_observation_is_recorded_with_host_derived_identity_and_replays(closure_host) -> None:
    env = closure_host
    request = human_request(env)
    observation = await human(env, request)
    assert observation.assessor_identity == ACTOR
    assert observation.independence_group == "human:" + ACTOR
    assert observation.assessor_qualification_ref == "m10.qualification.human-showrunner.v1"
    assert await human(env, request) == observation
    with pytest.raises(CommandReplayConflictError):
        await human(env, human_request(env, status="FAIL"))
    async with env["factory"]() as session:
        count = sa.select(sa.func.count()).select_from(QualityHumanObservationModel)
        assert (await session.execute(count)).scalar_one() == 1


@pytest.mark.parametrize("token", [None, "arc-key", "other"])
async def test_unauthenticated_or_other_actor_cannot_record(closure_host, token) -> None:
    env = closure_host
    bad = auth.create_token("someone-else") if token == "other" else token
    with pytest.raises(RequiredEvidenceMissingError):
        await human(env, human_request(env), token=bad)


async def test_actor_without_a_showrunner_grant_is_unqualified(closure_host) -> None:
    env = closure_host
    with pytest.raises(RequiredEvidenceMissingError):
        await human(env, human_request(env, actor_id="intruder"), actor="intruder")


async def test_technical_slot_cannot_take_a_human_observation(closure_host) -> None:
    env = closure_host
    with pytest.raises(RequiredEvidenceMissingError):
        await human(env, human_request(env, requirement_id="technical-required", slot_id="technical"))


async def test_run_seals_from_real_receipts_replays_and_is_current(closure_host) -> None:
    env = closure_host
    probe = await technical(env)
    review = await human(env, human_request(env))
    command = completion(env, [probe, review])
    run = await seal(env, command)
    assert {r.slot_id: r.state for r in run.slot_results} == {"technical": "SATISFIED", "human": "SATISFIED"}
    assert await seal(env, command) == run
    assert await validity(env, run) == "CURRENT"


async def test_receipt_replay_needs_no_live_governance(closure_host) -> None:
    env = closure_host
    probe = await technical(env)
    review = await human(env, human_request(env))
    command = completion(env, [probe, review])
    run = await seal(env, command)

    async def unavailable():
        raise RequiredEvidenceMissingError()

    assert await seal(env, command, reader=unavailable) == run


async def test_old_human_evidence_is_expired_at_database_time(closure_host) -> None:
    env = closure_host
    probe = await technical(env)
    review = await human(env, human_request(env), clock=lambda: datetime.now(UTC) - timedelta(days=30))
    run = await seal(env, completion(env, [probe, review]))
    assert await validity(env, run) == "EXPIRED"


async def test_incomplete_or_tampered_completion_refuses(closure_host) -> None:
    env = closure_host
    probe = await technical(env)
    with pytest.raises(RequiredEvidenceMissingError):
        await seal(env, completion(env, [probe]))
    review = await human(env, human_request(env))
    data = completion(env, [probe, review], command_id="seal-2").model_dump(mode="json")
    data["subject"]["execution_refs"] = ["forged-execution"]
    data["command"]["request_digest"] = compute_digest("m10.run-completion-request.v1", data)
    with pytest.raises(RequiredEvidenceMissingError):
        await seal(env, q.CompleteRunCommand.model_validate(data))
    async with env["factory"]() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(QualityRunModel))).scalar_one() == 0


async def test_evidence_from_another_profile_revision_is_refused(closure_host) -> None:
    env = closure_host
    probe = await technical(env)
    review = await human(env, human_request(env))
    newer = await append(env["factory"], request_for(2, "publish-2", policy=policy_for(env["config"])))
    with pytest.raises(RequiredEvidenceMissingError):
        await seal(env, completion(env, [probe, review], profile=newer))


async def test_intervening_reevaluation_supersedes_even_after_a_historical_only_revision(closure_host) -> None:
    env = closure_host
    run = await sealed(env)
    policy = policy_for(env["config"])
    await append(env["factory"], request_for(2, "publish-2", policy=policy, supersession_effect="REEVALUATE_CURRENT"))
    await append(env["factory"], request_for(3, "publish-3", policy=policy, supersession_effect="HISTORICAL_ONLY"))
    assert await validity(env, run) == "SUPERSEDED"


async def test_changed_master_or_manifest_metadata_is_stale_and_old_runs_stay_readable(closure_host) -> None:
    env = closure_host
    run = await sealed(env)
    write_manifest(env["project"], subject_of(env), change={"content_fingerprint": "sha256:" + "9" * 64})
    assert await validity(env, run) == "STALE"
    with pytest.raises(SubjectStaleError):
        await human(env, human_request(env, command_id="human-2"))
    write_manifest(env["project"], subject_of(env))
    assert await validity(env, run) == "CURRENT"
    await promote(env["factory"], env["project"], FIXTURES / "video_only.mp4", "2")
    assert await validity(env, run) == "STALE"


async def test_newer_run_supersedes_and_corrupted_evidence_or_profile_invalidates(closure_host) -> None:
    env = closure_host
    first = await sealed(env, "seal-a")
    probe = await technical(env)
    review = await human(env, human_request(env, command_id="human-b"))
    second = await seal(env, completion(env, [probe, review], command_id="seal-b"))
    assert await validity(env, first) == "SUPERSEDED"
    async with env["factory"]() as session, session.begin():
        await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            sa.text("UPDATE m10_quality_human_observations SET observation_digest = 'sha256:' || repeat('0', 64)")
        )
    assert await validity(env, second) == "INVALIDATED"
    async with env["factory"]() as session, session.begin():
        await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            sa.text("UPDATE m10_quality_profile_revisions SET profile_digest = 'sha256:' || repeat('0', 64)")
        )
    assert await validity(env, first) == "INVALIDATED"


@pytest.mark.parametrize("table", ["m10_quality_human_observations", "m10_quality_runs", "m10_quality_run_commands"])
async def test_raw_update_and_delete_are_refused(closure_host, table: str) -> None:
    env = closure_host
    await sealed(env)
    for statement in (f"UPDATE {table} SET user_id = user_id", f"DELETE FROM {table}"):
        with pytest.raises(sa.exc.DBAPIError, match="M10_IMMUTABLE_RUN_ROW"):
            async with env["factory"]() as session, session.begin():
                await session.execute(sa.text(statement))


async def test_sealing_waits_for_a_concurrent_master_authority_writer(closure_host) -> None:
    import asyncio

    from server.services.master_authority import lock_current_master_rows

    env = closure_host
    probe = await technical(env)
    review = await human(env, human_request(env))
    command = completion(env, [probe, review])
    keys = [env["root"].artifact_key, env["dependency"].artifact_key]
    async with env["factory"]() as writer, writer.begin():
        await lock_current_master_rows(writer, user_id="default", project_name="project", artifact_keys=keys)
        task = asyncio.create_task(seal(env, command))
        done, _ = await asyncio.wait({task}, timeout=1.5)
        assert not done
    run = await asyncio.wait_for(task, timeout=30)
    assert run.run_id == command.subject.run_id
