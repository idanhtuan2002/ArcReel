"""Request-bound probe custody on real PostgreSQL with the real isolated runtime and M7 attempts.

Fixture rows (published profile, promoted master) are seeded through the existing repositories; they
confer no Human authority. Runtime wrappers only count or fail tool starts.
"""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.host_hardening import ExecutionAttemptModel
from lib.db.models.quality_probes import (
    QualityProbeInvocationModel,
    QualityProbeObservationModel,
    QualityProbeResultModel,
)
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from lib.db.repositories.quality_probes import QualityProbeRepository
from r2.quality.digests import compute_digest
from r2.quality.errors import (
    CommandReplayConflictError,
    ProbeFailedError,
    ProfileStaleError,
    RequiredEvidenceMissingError,
    SubjectStaleError,
)
from r2.quality.ports import ProbeRequest, validate_probe_result_binding
from r2.quality.probes import ProbeCatalog, config_digest, policy_digest
from server import auth
from server.services import quality_probe_runtime as runtime
from server.services.format_render import file_digest
from server.services.master_authority import master_authority_unit
from server.services.quality_probes import QualityProbeService
from tests.integration.lib.db.repositories.test_quality_profiles_repository import append, quality_factory
from tests.integration.server.services.test_quality_probe_recipes import FIXTURES, config_for, host
from tests.integration.server.services.test_quality_profile_custodian import SECRET
from tests.unit.r2.quality.test_quality_ports import probe_data
from tests.unit.r2.quality.test_quality_profiles import publication_request

__all__ = ["quality_factory"]

type Factory = async_sessionmaker[AsyncSession]
USER = "default"
PROJECT = "project"
ACTOR = "actor"
MIGRATION = Path(__file__).resolve().parents[4] / "alembic/versions/07fd34535384_quality_probe_evidence.py"


class CountingRuntime:
    """Delegates to the real isolated runtime and counts tool starts; optional injected outcomes."""

    def __init__(self, real: runtime.QualityProbeRuntime, *, fail: BaseException | None = None, delay: float = 0):
        self.real = real
        self.fail = fail
        self.delay = delay
        self.starts = 0

    @property
    def host(self) -> runtime.ProbeHost:
        return self.real.host

    def preflight(self, config) -> None:
        self.real.preflight(config)

    async def run(self, request, inputs, config):
        self.starts += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        return await self.real.run(request, inputs, config)


@pytest.fixture
async def probe_host(quality_factory: Factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", SECRET)
    spec = importlib.util.spec_from_file_location("m10_probe_migration_fixture", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    async with quality_factory() as session, session.begin():
        connection = await session.connection()
        await connection.run_sync(module.install_immutability)
    project = tmp_path / "project"
    project.mkdir(mode=0o700)
    (tmp_path / "work").mkdir(mode=0o700)
    config = config_for("DECODE")
    profile = await publish(quality_factory, config)
    root = await promote(quality_factory, project, FIXTURES / "av.mp4", "1")
    real = runtime.QualityProbeRuntime(
        runtime.ProbeHost(tools=host().tools, vmaf_model=host().vmaf_model, work_root=tmp_path / "work")
    )
    catalog = ProbeCatalog(schema_id="m10.probe-catalog.v1", configs=(config,))
    return {
        "factory": quality_factory,
        "project": project,
        "config": config,
        "profile": profile,
        "root": root,
        "runtime": real,
        "catalog": catalog,
    }


def bound_policy(config) -> dict[str, Any]:
    from tests.unit.r2.quality.test_probes import probe_request_data

    policy = probe_request_data(config)["profile"]["policy"]
    primary = config.primary_tool()
    policy["probe_rules"][0].update(
        tool_identity=primary.name,
        tool_version_constraint="==" + primary.version,
        max_runtime_ms=config.max_runtime_ms,
        max_output_bytes=config.max_output_bytes,
        config_digest=config_digest(config),
        applicability_policy_digest=policy_digest(config.applicability_policy),
        threshold_policy_digest=policy_digest(config.threshold_policy),
    )
    return policy


async def publish(factory: Factory, config):
    policy = bound_policy(config)
    return await append(factory, publication_request(user_id=USER, revision=1, parent_revision=None, policy=policy))


async def promote(factory: Factory, project: Path, media: Path, tag: str):
    from tests.unit.r2.contracts.test_quality import binding_data

    key = binding_data()["root"]["artifact_key"]
    source = project / f"render-{tag}.mp4"
    shutil.copyfile(media, source)
    async with factory() as session:
        await master_authority_unit(session).promote_staged(
            user_id=USER,
            project_name=PROJECT,
            project_dir=project,
            artifact_key=key,
            generation_candidate_id=f"candidate-{tag}",
            version_file=source,
            expected_content_digest=file_digest(source),
            approval_record=f"APR-{tag}",
            command_id=f"seed-{tag}",
        )
    async with factory() as session:
        current = await MasterAuthorityRepository(session).get_current(
            user_id=USER, project_name=PROJECT, artifact_key=key
        )
    assert current is not None
    return current


def probe_request(profile, root, *, actor: str = ACTOR, execution_ref: str = "probe-1", slot_id: str = "technical"):
    from tests.unit.r2.quality.test_quality_digests import valid_subject

    data: dict[str, Any] = probe_data()
    subject = valid_subject().model_dump(mode="json")
    binding = subject["master_binding"]
    binding.update(user_id=USER, project_name=PROJECT)
    binding["root"].update(root.model_dump(mode="json"))
    for snapshot in binding["metadata_snapshots"]:
        if snapshot["artifact_key"] == root.artifact_key:
            snapshot["body"]["approved_master"].update(
                approval_record=root.approval_record, selected_candidate_id=root.candidate_id
            )
        snapshot["metadata_digest"] = compute_digest("m10.artifact-metadata.v1", snapshot)
    subject["master_binding_digest"] = compute_digest("m10.master-binding.v1", binding)
    subject.update(
        artifact_ref=root.object_ref, artifact_digest="sha256:" + root.content_digest.removeprefix("sha256:")
    )
    profile_body = profile.model_dump(mode="json")
    data.update(
        user_id=USER,
        project_name=PROJECT,
        actor_id=actor,
        execution_ref=execution_ref,
        slot_id=slot_id,
        subject=subject,
        profile=profile_body,
        rule=profile_body["policy"]["probe_rules"][0],
    )
    return ProbeRequest.model_validate(data)


async def service(env, request, *, run=None, token: str | None = "default", **kwargs) -> QualityProbeService:
    return await QualityProbeService.for_request(
        request,
        env["factory"],
        interactive_token=auth.create_token(ACTOR) if token == "default" else token,
        project_root=env["project"],
        catalog=env["catalog"],
        runtime=run or env["runtime"],
        **kwargs,
    )


async def counts(factory: Factory) -> tuple[int, ...]:
    models = (QualityProbeInvocationModel, ExecutionAttemptModel, QualityProbeResultModel, QualityProbeObservationModel)
    async with factory() as session:
        return tuple(
            [(await session.execute(sa.select(sa.func.count()).select_from(model))).scalar_one() for model in models]
        )


async def test_observation_binds_real_measurement_to_m7_success_and_replays_after_media_loss(probe_host) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    counting = CountingRuntime(env["runtime"])
    observation = await (await service(env, request, run=counting)).observe(request)
    validate_probe_result_binding(request, observation)
    assert observation.status.value == "PASS"
    assert observation.observation_type.value == "TECHNICAL"
    assert counting.starts == 1
    assert await counts(env["factory"]) == (1, 1, 1, 1)
    async with env["factory"]() as session:
        attempt = (await session.execute(sa.select(ExecutionAttemptModel))).scalar_one()
        assert attempt.state == "SUCCEEDED"
        assert attempt.provider_job_id == f"{observation.probe_receipt_ref}:{observation.probe_receipt_digest}"
    for path in env["project"].iterdir():
        path.unlink()
    exploding = CountingRuntime(env["runtime"], fail=AssertionError("replay must not run tools"))
    replayed = await (await service(env, request, run=exploding)).observe(request)
    assert replayed == observation
    assert exploding.starts == 0


@pytest.mark.parametrize("token", [None, "arc-api-key", "wrong-actor"])
async def test_unauthenticated_api_key_or_other_actor_is_refused_before_any_record(probe_host, token) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    bad = auth.create_token("someone-else") if token == "wrong-actor" else token
    with pytest.raises(RequiredEvidenceMissingError):
        await service(env, request, token=bad)
    assert await counts(env["factory"]) == (0, 0, 0, 0)


async def test_auth_disabled_is_refused(probe_host, monkeypatch: pytest.MonkeyPatch) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    token = auth.create_token(ACTOR)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    with pytest.raises(RequiredEvidenceMissingError):
        await service(env, request, token=token)


async def test_changed_root_is_stale_and_writes_nothing(probe_host) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    await promote(env["factory"], env["project"], FIXTURES / "video_only.mp4", "2")
    with pytest.raises(SubjectStaleError):
        await (await service(env, request)).observe(request)
    assert await counts(env["factory"]) == (0, 0, 0, 0)


async def test_valid_but_unpublished_profile_is_stale_and_writes_nothing(probe_host) -> None:
    from r2.advanced_creative.exploration import uuid7
    from tests.unit.r2.quality.test_quality_profiles import publish as build_profile

    env = probe_host
    unpublished = build_profile(
        publication_request(
            user_id=USER, revision=1, parent_revision=None, policy=bound_policy(env["config"]), profile_id=uuid7()
        )
    )
    request = probe_request(unpublished, env["root"])
    with pytest.raises(ProfileStaleError):
        await (await service(env, request)).observe(request)
    assert await counts(env["factory"]) == (0, 0, 0, 0)


async def test_same_reference_with_a_different_body_conflicts(probe_host) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    await (await service(env, request)).observe(request)
    other = probe_request(env["profile"], env["root"], slot_id="other")
    with pytest.raises(CommandReplayConflictError):
        await (await service(env, other)).observe(other)


async def test_known_tool_failure_is_a_failed_attempt_without_observation_and_never_reruns(probe_host) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    failing = CountingRuntime(env["runtime"], fail=ProbeFailedError())
    with pytest.raises(ProbeFailedError):
        await (await service(env, request, run=failing)).observe(request)
    assert await counts(env["factory"]) == (1, 1, 0, 0)
    async with env["factory"]() as session:
        assert (
            await session.execute(sa.select(ExecutionAttemptModel.state))
        ).scalar_one() == "FAILED_BEFORE_ACCEPTANCE"
    again = CountingRuntime(env["runtime"])
    with pytest.raises(ProbeFailedError):
        await (await service(env, request, run=again)).observe(request)
    assert again.starts == 0


async def test_unexpected_runtime_error_after_possible_start_is_unknown_and_never_reruns(probe_host) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    crashing = CountingRuntime(env["runtime"], fail=RuntimeError("worker vanished"))
    with pytest.raises(RequiredEvidenceMissingError):
        await (await service(env, request, run=crashing)).observe(request)
    async with env["factory"]() as session:
        assert (await session.execute(sa.select(ExecutionAttemptModel.state))).scalar_one() == "SUBMIT_OUTCOME_UNKNOWN"
    assert await counts(env["factory"]) == (1, 1, 0, 0)
    again = CountingRuntime(env["runtime"])
    with pytest.raises(RequiredEvidenceMissingError):
        await (await service(env, request, run=again)).observe(request)
    assert again.starts == 0


async def test_result_staging_failure_rolls_back_and_is_unknown(probe_host, monkeypatch: pytest.MonkeyPatch) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])

    async def broken(self, invocation, result) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(QualityProbeRepository, "stage_result", broken)
    with pytest.raises(RequiredEvidenceMissingError):
        await (await service(env, request)).observe(request)
    async with env["factory"]() as session:
        assert (await session.execute(sa.select(ExecutionAttemptModel.state))).scalar_one() == "SUBMIT_OUTCOME_UNKNOWN"
    assert await counts(env["factory"]) == (1, 1, 0, 0)


async def test_accepted_result_finalizes_after_a_crash_before_finalization(probe_host, monkeypatch) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    counting = CountingRuntime(env["runtime"])

    async def crash(self, invocation, observation):
        raise SystemExit("process lost before the finalization commit")

    original = QualityProbeRepository.finalize
    monkeypatch.setattr(QualityProbeRepository, "finalize", crash)
    with pytest.raises(SystemExit):
        await (await service(env, request, run=counting)).observe(request)
    assert await counts(env["factory"]) == (1, 1, 1, 0)
    async with env["factory"]() as session:
        assert (await session.execute(sa.select(ExecutionAttemptModel.state))).scalar_one() == "ACCEPTED"
    monkeypatch.setattr(QualityProbeRepository, "finalize", original)
    observation = await (await service(env, request, run=counting)).observe(request)
    assert counting.starts == 1
    assert observation.status.value == "PASS"
    assert await counts(env["factory"]) == (1, 1, 1, 1)


async def test_expired_session_after_tools_prevents_finalization_but_keeps_the_result(probe_host, monkeypatch) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    probe = await service(env, request)
    original = QualityProbeService.require_actor
    calls = 0

    async def expire(self, request):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RequiredEvidenceMissingError()
        await original(self, request)

    monkeypatch.setattr(QualityProbeService, "require_actor", expire)
    with pytest.raises(RequiredEvidenceMissingError):
        await probe.observe(request)
    assert await counts(env["factory"]) == (1, 1, 1, 0)
    async with env["factory"]() as session:
        assert (await session.execute(sa.select(ExecutionAttemptModel.state))).scalar_one() == "ACCEPTED"


async def test_concurrent_exact_calls_start_tools_once(probe_host) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    slow = CountingRuntime(env["runtime"], delay=1.0)
    first, second = await asyncio.gather(
        (await service(env, request, run=slow)).observe(request),
        (await service(env, request, run=slow)).observe(request),
        return_exceptions=True,
    )
    outcomes = [first, second]
    assert slow.starts == 1
    observations = [item for item in outcomes if not isinstance(item, BaseException)]
    assert observations
    assert all(isinstance(item, RequiredEvidenceMissingError) for item in outcomes if isinstance(item, BaseException))
    replayed = await (await service(env, request, run=slow)).observe(request)
    assert replayed == observations[0]
    assert slow.starts == 1


async def test_stored_body_or_cached_digest_corruption_refuses_replay(probe_host) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    await (await service(env, request)).observe(request)
    for statement in (
        "UPDATE m10_quality_probe_results SET result_digest = 'sha256:' || repeat('0', 64)",
        "UPDATE m10_quality_probe_observations SET observation_json = "
        "jsonb_set(observation_json::jsonb, '{status}', '\"FAIL\"')::json",
    ):
        async with env["factory"]() as session, session.begin():
            await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
            savepoint = await session.begin_nested()
            await session.execute(sa.text(statement))
            with pytest.raises(RequiredEvidenceMissingError):
                await QualityProbeRepository(session).replay(request)
            await savepoint.rollback()


@pytest.mark.parametrize(
    "table", ["m10_quality_probe_invocations", "m10_quality_probe_results", "m10_quality_probe_observations"]
)
async def test_raw_update_and_delete_are_refused_for_every_append_only_table(probe_host, table: str) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    await (await service(env, request)).observe(request)
    for statement in (f"UPDATE {table} SET user_id = user_id", f"DELETE FROM {table}"):
        with pytest.raises(sa.exc.DBAPIError, match="M10_IMMUTABLE_PROBE_ROW"):
            async with env["factory"]() as session, session.begin():
                await session.execute(sa.text(statement))


async def test_replay_survives_a_retired_catalog_entry(probe_host) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    observation = await (await service(env, request)).observe(request)
    retired = env | {"catalog": ProbeCatalog(schema_id="m10.probe-catalog.v1", configs=())}
    assert await (await service(retired, request)).observe(request) == observation


@pytest.mark.parametrize("column", ["request_digest", "route_json"])
async def test_replay_refuses_a_changed_m7_attempt_identity(probe_host, column: str) -> None:
    env = probe_host
    request = probe_request(env["profile"], env["root"])
    await (await service(env, request)).observe(request)
    value = "'sha256:' || repeat('0', 64)" if column == "request_digest" else '\'{"provider_id": "other"}\'::json'
    async with env["factory"]() as session, session.begin():
        await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await session.execute(sa.text(f"UPDATE execution_attempts SET {column} = {value}"))
    with pytest.raises(RequiredEvidenceMissingError):
        await (await service(env, request)).observe(request)


async def test_failure_building_the_acceptance_receipt_after_staging_is_unknown(probe_host, monkeypatch) -> None:
    from server.services import quality_probes as module

    env = probe_host
    request = probe_request(env["profile"], env["root"])

    def broken(**_: object):
        raise RuntimeError("receipt construction failed")

    monkeypatch.setattr(module, "ProviderSubmitReceipt", broken)
    with pytest.raises(RequiredEvidenceMissingError):
        await (await service(env, request)).observe(request)
    assert await counts(env["factory"]) == (1, 1, 0, 0)
    async with env["factory"]() as session:
        assert (await session.execute(sa.select(ExecutionAttemptModel.state))).scalar_one() == "SUBMIT_OUTCOME_UNKNOWN"
