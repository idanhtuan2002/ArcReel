"""The M10-B packaging check on real PostgreSQL: verified facts from a sealed run, one observation per command."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import r2.contracts.quality as q
from lib.db.models.quality_packaging import PackagingObservationModel
from lib.db.repositories.advanced_creative import ExplorationRepository
from r2.advanced_creative.digests import digest_payload
from r2.contracts import packaging as p
from r2.contracts.advanced_creative import (
    ExplorationKind,
    ExplorationRevision,
    LineageBinding,
    PackagingCandidate,
)
from r2.quality.digests import compute_digest
from r2.quality.errors import CommandReplayConflictError, ProfileStaleError, SubjectStaleError
from r2.quality.probes import ProbeCatalog
from server.services import quality_probe_runtime as runtime
from server.services.governance_attestation import serve_governance_attestor
from server.services.governance_startup import verify_governance_activated_startup
from server.services.quality_packaging import PackagingCheckService
from tests.integration.lib.db.repositories.test_quality_profiles_repository import append, request_for
from tests.integration.server.services.test_quality_probe_recipes import FIXTURES, config_for, host
from tests.integration.server.services.test_quality_probes import promote
from tests.integration.server.services.test_quality_profile_custodian import SECRET, prepare_qualified_custody
from tests.integration.server.services.test_quality_runs import (
    MIGRATIONS,
    completion,
    human,
    human_request,
    install,
    policy_for,
    seal,
    subject_of,
    technical,
    write_manifest,
)
from tests.unit.r2.contracts.test_packaging import candidate_body, constraints_data

type Factory = async_sessionmaker[AsyncSession]

NOW = datetime(2026, 10, 29, tzinfo=UTC)
PACKAGING_MIGRATION = "6e3b8d4f9c22_m10_packaging_observations.py"


def v2_policy(config) -> dict[str, Any]:
    constraints = constraints_data() | {
        "width": 64,
        "height": 64,
        "min_duration_ms": 1000,
        "max_duration_ms": 900000,
        "required_locales": [],
        "title_required_terms": [],
        "description_required_terms": [],
    }
    return policy_for(config) | {
        "schema_id": "m10.quality-policy.v2",
        "platform_constraints": constraints,
        "packaging_waiverable_rule_ids": ["title-length"],
    }


@pytest.fixture
async def packaging_host(session_factory: Factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tests.unit.r2.contracts.test_quality import binding_data

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", SECRET)
    factory = session_factory
    async with factory() as session, session.begin():
        if session.get_bind().dialect.name != "postgresql":
            pytest.skip("packaging custody requires real PostgreSQL")
        connection = await session.connection()
        for name in (*MIGRATIONS, PACKAGING_MIGRATION):
            await connection.run_sync(install(name))
    (tmp_path / "governance").mkdir(mode=0o700)
    root_dir, socket_dir, *_ = await prepare_qualified_custody(factory, tmp_path / "governance")
    project = tmp_path / "project"
    project.mkdir(mode=0o700)
    (tmp_path / "work").mkdir(mode=0o700)
    config = config_for("CONTAINER_STREAM")
    profile = await append(factory, request_for(1, "publish-1", policy=v2_policy(config)))
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
        probe = await technical(env)
        review = await human(env, human_request(env))
        env["run"] = await seal(env, completion(env, [probe, review]))
        yield env


def _lineage(env) -> LineageBinding:
    run = env["run"]
    return LineageBinding(
        project_name="project",
        content_basis_digest=run.subject.content_basis_digest,
        approved_master_id=env["root"].candidate_id,
        approved_master_digest=run.subject.artifact_digest,
        creative_profile_id=run.profile_id,
        creative_profile_version=str(run.profile_revision),
        policy_digest=env["profile"].policy_digest,
    )


def candidate_for(env, **changes: Any) -> PackagingCandidate:
    run, profile, root = env["run"], env["profile"], env["root"]
    constraints = profile.policy.platform_constraints
    media = Path(root.object_ref)
    source_ref = media.resolve().relative_to(env["project"].resolve()).as_posix()
    body = candidate_body() | {
        "approved_master_id": root.candidate_id,
        "approved_master_digest": run.subject.artifact_digest,
        "assessed_subject_digest": run.subject_digest,
        "quality_profile_id": profile.profile_id,
        "quality_profile_revision": profile.revision,
        "quality_profile_digest": profile.profile_digest,
        "constraint_snapshot_digest": compute_digest("m10.platform-constraints.v1", constraints),
        "description": "How the river shaped the valley over ten thousand years.",
        "chapters": [],
        "localization_variants": [],
        "variant_groups": [],
        "assets": [
            {
                "role": "video",
                "variant_id": None,
                "source_ref": source_ref,
                "content_digest": run.subject.artifact_digest,
                "media_type": "video/mp4",
                "byte_size": media.stat().st_size,
                "constraint_rule_id": "asset-video",
            }
        ],
    }
    body |= changes
    draft = PackagingCandidate.model_validate(body)
    return PackagingCandidate.model_validate(
        body
        | {
            "content_closure_digest": compute_digest("m10.packaging-content.v1", draft),
            "presentation_closure_digest": compute_digest("m10.packaging-presentation.v1", draft),
        }
    )


async def append_candidate(env, payload: PackagingCandidate, revision: int = 1, kind=ExplorationKind.PACKAGING):
    lineage = _lineage(env)
    candidate = ExplorationRevision(
        candidate_id="package",
        revision=revision,
        kind=kind,
        parent_revision=None if revision == 1 else revision - 1,
        payload=payload,
        payload_digest=digest_payload(payload, lineage),
        lineage=lineage,
        created_by="default",
        created_at=NOW,
    )
    async with env["factory"]() as session:
        await ExplorationRepository(session).append_revision(
            user_id="default",
            project_name="project",
            candidate=candidate,
            expected_head_version=None if revision == 1 else revision - 1,
            command_id=f"append-{revision}",
        )
        await session.commit()
    return candidate


def check_request(env, candidate: ExplorationRevision, command_id: str = "check-1") -> p.PackageCheckRequest:
    run = env["run"]
    from r2.quality.runs import run_digest

    body: dict[str, Any] = {
        "command": {
            "user_id": "default",
            "project_name": "project",
            "actor_id": "default",
            "operation": "CHECK_PACKAGE",
            "command_id": command_id,
            "request_digest": "sha256:" + "0" * 64,
        },
        "subject": {
            "user_id": "default",
            "project_name": "project",
            "actor_id": "default",
            "candidate_id": candidate.candidate_id,
            "candidate_revision": candidate.revision,
            "candidate_payload_digest": candidate.payload_digest,
            "quality_run_id": run.run_id,
            "quality_run_digest": run_digest(run),
        },
    }
    body["command"]["request_digest"] = compute_digest("m10.package-check-request.v1", body)
    return p.PackageCheckRequest.model_validate(body)


def service(env) -> PackagingCheckService:
    return PackagingCheckService(sessions=env["factory"], project_root=env["project"], clock=lambda: NOW)


async def test_a_clean_package_passes_on_verified_run_facts_and_replays_exactly(packaging_host) -> None:
    env = packaging_host
    candidate = await append_candidate(env, candidate_for(env))
    request = check_request(env, candidate)
    observation = await service(env).check(request)
    assert observation.status is q.ObservationStatus.PASS, observation.findings
    assert observation.packaging_subject.base_subject_digest == env["run"].subject_digest
    assert await service(env).check(request) == observation
    async with env["factory"]() as session:
        rows = (await session.execute(sa.select(sa.func.count()).select_from(PackagingObservationModel))).scalar_one()
    assert rows == 1


async def test_declared_bytes_that_differ_from_the_project_file_fail_integrity(packaging_host) -> None:
    env = packaging_host
    payload = candidate_for(env)
    asset = payload.assets[0].model_dump(mode="python") | {"byte_size": payload.assets[0].byte_size + 1}
    candidate = await append_candidate(env, candidate_for(env, assets=[asset]))
    observation = await service(env).check(check_request(env, candidate))
    assert observation.status is q.ObservationStatus.FAIL
    # The fixture snapshot binds the asset.integrity check to rule id "asset-thumbnail".
    assert [(f.rule_id, f.subject_locator) for f in observation.findings] == [("asset-thumbnail", "assets[video/-]")]


async def test_a_reused_command_for_another_candidate_conflicts(packaging_host) -> None:
    env = packaging_host
    first = await append_candidate(env, candidate_for(env))
    await service(env).check(check_request(env, first))
    second = await append_candidate(env, candidate_for(env, title="A second history of the river"), revision=2)
    with pytest.raises(CommandReplayConflictError):
        await service(env).check(check_request(env, second))


async def test_a_candidate_whose_head_is_not_packaging_is_refused(packaging_host) -> None:
    from tests.integration.lib.db.repositories.test_advanced_creative import _revision

    env = packaging_host
    first = await append_candidate(env, candidate_for(env))
    canvas = _revision(2, candidate_id="package", project="project")
    async with env["factory"]() as session:
        await ExplorationRepository(session).append_revision(
            user_id="default",
            project_name="project",
            candidate=canvas.model_copy(update={"created_by": "default"}),
            expected_head_version=1,
            command_id="canvas-2",
        )
        await session.commit()
    with pytest.raises(SubjectStaleError):
        await service(env).check(check_request(env, first))


async def test_a_v1_profile_cannot_govern_packaging(packaging_host, monkeypatch: pytest.MonkeyPatch) -> None:
    from lib.db.repositories.quality import QualityProfileRepository

    env = packaging_host
    candidate = await append_candidate(env, candidate_for(env))
    original = QualityProfileRepository.get_revision

    async def as_v1(self, **kwargs):
        profile = await original(self, **kwargs)
        assert profile is not None
        v1 = q.QualityPolicyV1.model_validate(
            profile.policy.model_dump(mode="python", exclude={"platform_constraints", "packaging_waiverable_rule_ids"})
            | {"schema_id": "m10.quality-policy.v1"}
        )
        return profile.model_copy(update={"policy": v1})

    monkeypatch.setattr(QualityProfileRepository, "get_revision", as_v1)
    with pytest.raises(ProfileStaleError):
        await service(env).check(check_request(env, candidate))


async def test_packaging_observation_rows_are_append_only(packaging_host) -> None:
    env = packaging_host
    candidate = await append_candidate(env, candidate_for(env))
    await service(env).check(check_request(env, candidate))
    for statement in (
        "UPDATE m10_packaging_observations SET status = status",
        "DELETE FROM m10_packaging_observations",
    ):
        with pytest.raises(sa.exc.DBAPIError, match="M10_IMMUTABLE_PACKAGING_ROW"):
            async with env["factory"]() as session, session.begin():
                await session.execute(sa.text(statement))


async def test_a_byte_identical_copy_is_not_the_approved_master(packaging_host) -> None:
    import shutil

    env = packaging_host
    shutil.copyfile(env["root"].object_ref, env["project"] / "copy.mp4")
    payload = candidate_for(env)
    asset = payload.assets[0].model_dump(mode="python") | {"source_ref": "copy.mp4"}
    candidate = await append_candidate(env, candidate_for(env, assets=[asset]))
    observation = await service(env).check(check_request(env, candidate))
    assert observation.status is q.ObservationStatus.FAIL
    assert [f.subject_locator for f in observation.findings] == ["assets[video/-]"]


@pytest.mark.parametrize("source_ref", ["../outside.mp4", "/etc/passwd", "link.mp4"])
async def test_unsafe_asset_paths_are_never_measured(packaging_host, source_ref: str) -> None:
    env = packaging_host
    (env["project"] / "link.mp4").symlink_to(env["root"].object_ref)
    payload = candidate_for(env)
    asset = payload.assets[0].model_dump(mode="python") | {"source_ref": source_ref}
    candidate = await append_candidate(env, candidate_for(env, assets=[asset]))
    observation = await service(env).check(check_request(env, candidate))
    assert observation.status is q.ObservationStatus.FAIL


async def append_with_lineage(env, payload: PackagingCandidate, **lineage_changes: Any) -> ExplorationRevision:
    lineage = _lineage(env).model_copy(update=lineage_changes)
    candidate = ExplorationRevision(
        candidate_id="package",
        revision=1,
        kind=ExplorationKind.PACKAGING,
        parent_revision=None,
        payload=payload,
        payload_digest=digest_payload(payload, lineage),
        lineage=lineage,
        created_by="default",
        created_at=NOW,
    )
    async with env["factory"]() as session:
        await ExplorationRepository(session).append_revision(
            user_id="default",
            project_name="project",
            candidate=candidate,
            expected_head_version=None,
            command_id="append-1",
        )
        await session.commit()
    return candidate


@pytest.mark.parametrize(
    "change",
    [
        {"content_basis_digest": "sha256:" + "e" * 64},
        {"approved_master_id": "another-master"},
        {"approved_master_digest": "sha256:" + "e" * 64},
        {"creative_profile_id": "0199f00d-0000-7000-8000-00000000abcd"},
        {"creative_profile_version": "2"},
        {"policy_digest": "sha256:" + "e" * 64},
    ],
)
async def test_m8_lineage_must_name_the_verified_run_master_and_profile(packaging_host, change) -> None:
    env = packaging_host
    candidate = await append_with_lineage(env, candidate_for(env), **change)
    with pytest.raises(SubjectStaleError):
        await service(env).check(check_request(env, candidate))


async def test_a_wrong_run_digest_is_stale(packaging_host) -> None:
    env = packaging_host
    candidate = await append_candidate(env, candidate_for(env))
    request = check_request(env, candidate)
    body = request.model_dump(mode="python")
    body["subject"]["quality_run_digest"] = "sha256:" + "e" * 64
    body["command"]["request_digest"] = compute_digest("m10.package-check-request.v1", body)
    with pytest.raises(SubjectStaleError):
        await service(env).check(p.PackageCheckRequest.model_validate(body))


async def test_a_run_without_a_container_probe_has_no_master_facts(packaging_host, monkeypatch) -> None:
    from lib.db.repositories.quality_runs import QualityRunRepository
    from r2.quality.errors import RequiredEvidenceMissingError

    env = packaging_host
    candidate = await append_candidate(env, candidate_for(env))

    async def none(self, **_: Any):
        return None

    monkeypatch.setattr(QualityRunRepository, "technical_observation", none)
    with pytest.raises(RequiredEvidenceMissingError):
        await service(env).check(check_request(env, candidate))


async def test_replay_needs_no_live_inputs_and_a_tampered_row_refuses(packaging_host) -> None:
    from r2.quality.errors import RequiredEvidenceMissingError

    env = packaging_host
    candidate = await append_candidate(env, candidate_for(env))
    request = check_request(env, candidate)
    observation = await service(env).check(request)
    os.unlink(env["root"].object_ref)
    assert await service(env).check(request) == observation
    for statement in (
        "UPDATE m10_packaging_observations SET observation_digest = 'sha256:' || repeat('0', 64)",
        "UPDATE m10_packaging_observations SET observation_json = "
        "jsonb_set(observation_json::jsonb, '{status}', '\"FAIL\"')::json",
    ):
        async with env["factory"]() as session, session.begin():
            await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
            savepoint = await session.begin_nested()
            await session.execute(sa.text(statement))
            from lib.db.repositories.quality_packaging import PackagingObservationRepository

            with pytest.raises(RequiredEvidenceMissingError):
                await PackagingObservationRepository(session).replay(request)
            await savepoint.rollback()


async def test_concurrent_exact_checks_record_one_observation(packaging_host) -> None:
    import asyncio

    env = packaging_host
    candidate = await append_candidate(env, candidate_for(env))
    request = check_request(env, candidate)
    first, second = await asyncio.gather(service(env).check(request), service(env).check(request))
    assert first == second
    async with env["factory"]() as session:
        rows = (await session.execute(sa.select(sa.func.count()).select_from(PackagingObservationModel))).scalar_one()
    assert rows == 1


async def test_a_stalled_measurement_stops_at_its_deadline(packaging_host) -> None:
    import time

    from r2.quality.errors import OperationalEnvelopeExceededError

    env = packaging_host
    candidate = await append_candidate(env, candidate_for(env))

    def stalled(*_: object):
        time.sleep(1.0)

    slow = PackagingCheckService(
        sessions=env["factory"],
        project_root=env["project"],
        clock=lambda: NOW,
        measure=stalled,
        deadline_seconds=lambda _constraints: 0.05,
    )
    with pytest.raises(OperationalEnvelopeExceededError):
        await slow.check(check_request(env, candidate))
    async with env["factory"]() as session:
        rows = (await session.execute(sa.select(sa.func.count()).select_from(PackagingObservationModel))).scalar_one()
    assert rows == 0


async def test_a_presentation_only_tamper_fails_at_the_service_boundary(packaging_host) -> None:
    env = packaging_host
    payload = candidate_for(env)
    forged = PackagingCandidate.model_validate(
        payload.model_dump(mode="python") | {"presentation_closure_digest": "sha256:" + "e" * 64}
    )
    candidate = await append_candidate(env, forged)
    observation = await service(env).check(check_request(env, candidate))
    assert observation.status is q.ObservationStatus.FAIL
    assert [f.subject_locator for f in observation.findings] == ["presentation_closure_digest"]
