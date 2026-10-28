"""Human dispositions on real PostgreSQL over runs sealed from real receipts and qualified observations."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa

import r2.contracts.quality as q
from lib.db.models.quality_dispositions import DispositionAuthorizationModel, QualityDispositionModel
from lib.db.repositories.quality_dispositions import QualityDispositionRepository
from r2.quality.digests import compute_digest
from r2.quality.errors import (
    CommandReplayConflictError,
    DispositionStaleError,
    DispositionUnauthorizedError,
    StaleHeadError,
    WaiverForbiddenError,
)
from r2.quality.runs import run_digest
from server import auth
from server.services.quality_dispositions import DispositionCustodian, DispositionService, quality_readiness
from tests.integration.server.services.test_quality_probe_recipes import FIXTURES
from tests.integration.server.services.test_quality_probes import ACTOR, promote
from tests.integration.server.services.test_quality_runs import (
    closure_host,
    completion,
    human,
    human_request,
    install,
    seal,
    sealed,
    technical,
)

__all__ = ["closure_host"]


@pytest.fixture
async def decision_host(closure_host):
    async with closure_host["factory"]() as session, session.begin():
        connection = await session.connection()
        await connection.run_sync(install("bed415be3608_quality_disposition.py"))
    return closure_host


def request_for(
    run: q.QualityRun, decision: str = "PASS", *, command_id: str = "decide-1", version: int = 0, **changes: Any
):
    body: dict[str, Any] = {
        "command": {
            "user_id": "default",
            "project_name": "project",
            "actor_id": ACTOR,
            "operation": "ISSUE_DISPOSITION",
            "command_id": command_id,
            "request_digest": "sha256:" + "0" * 64,
        },
        "subject": {
            "user_id": "default",
            "project_name": "project",
            "actor_id": ACTOR,
            "subject_digest": run.subject_digest,
            "quality_run_id": run.run_id,
            "quality_run_digest": run_digest(run),
            "profile_id": run.profile_id,
            "profile_revision": run.profile_revision,
            "profile_digest": run.profile_digest,
            "decision": decision,
            "waiver_bindings": [],
            "reason": "reviewed by the showrunner",
            "requested_expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "expected_disposition_version": version,
        }
        | changes,
    }
    body["command"]["request_digest"] = compute_digest("m10.disposition-request.v1", body)
    return q.DispositionAuthorizationRequest.model_validate(body)


async def issue(env, request, *, token: str | None = "default"):
    root_dir, socket_dir = env["governance"]
    custodian = await DispositionCustodian.for_request(
        request,
        env["factory"],
        interactive_token=auth.create_token(ACTOR) if token == "default" else token,
        read_directory=root_dir / "read",
        socket_directory=socket_dir,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    return await DispositionService(env["factory"], custodian=custodian, project_root=env["project"]).issue(request)


async def readiness(env, run: q.QualityRun):
    return await quality_readiness(
        env["factory"],
        env["reader"],
        project_root=env["project"],
        user_id="default",
        project_name="project",
        subject_digest=run.subject_digest,
        profile_id=run.profile_id,
    )


async def test_pass_over_a_current_run_is_ready_and_replays(decision_host) -> None:
    env = decision_host
    run = await sealed(env)
    assert (await readiness(env, run)).reasons == ("NO_DISPOSITION",)
    request = request_for(run)
    disposition = await issue(env, request)
    assert disposition.decision == q.DispositionDecision.PASS
    assert disposition.issuer_id == ACTOR
    assert disposition.supersedes_disposition_id is None
    assert await issue(env, request) == disposition
    assert (await readiness(env, run)).state == "READY"
    with pytest.raises(CommandReplayConflictError):
        await issue(env, request_for(run, "REWORK"))


@pytest.mark.parametrize("token", [None, "arc-key", "other"])
async def test_only_the_authenticated_showrunner_can_issue(decision_host, token) -> None:
    env = decision_host
    run = await sealed(env)
    bad = auth.create_token("someone-else") if token == "other" else token
    with pytest.raises(DispositionUnauthorizedError):
        await issue(env, request_for(run), token=bad)


async def test_rework_routes_repair_and_is_not_ready(decision_host) -> None:
    env = decision_host
    run = await sealed(env)
    await issue(env, request_for(run, "REWORK"))
    projected = await readiness(env, run)
    assert (projected.state, projected.reasons) == ("NOT_READY", ("REWORK",))


async def test_waiving_a_clean_run_is_forbidden_and_writes_no_disposition(decision_host) -> None:
    env = decision_host
    run = await sealed(env)
    waiver = {"rule_id": "review", "finding_id": None, "scope": "review-required:human", "justification": "x"}
    with pytest.raises(WaiverForbiddenError):
        await issue(env, request_for(run, "WAIVE", waiver_bindings=[waiver]))
    async with env["factory"]() as session:
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(QualityDispositionModel))
        ).scalar_one() == 0


async def test_a_superseded_or_stale_run_cannot_be_disposed(decision_host) -> None:
    env = decision_host
    first = await sealed(env, "seal-a")
    probe = await technical(env)
    review = await human(env, human_request(env, command_id="human-b"))
    second = await seal(env, completion(env, [probe, review], command_id="seal-b"))
    with pytest.raises(DispositionStaleError):
        await issue(env, request_for(first))
    await promote(env["factory"], env["project"], FIXTURES / "video_only.mp4", "2")
    with pytest.raises(DispositionStaleError):
        await issue(env, request_for(second, command_id="decide-2"))


async def test_head_cas_supersedes_in_order_and_refuses_a_stale_version(decision_host) -> None:
    env = decision_host
    run = await sealed(env)
    first = await issue(env, request_for(run, "REWORK"))
    with pytest.raises(StaleHeadError):
        await issue(env, request_for(run, command_id="decide-2", version=0))
    second = await issue(env, request_for(run, command_id="decide-3", version=1))
    assert second.supersedes_disposition_id == first.disposition_id
    assert (await readiness(env, run)).state == "READY"


async def test_concurrent_first_issues_converge_on_one_head(decision_host) -> None:
    env = decision_host
    run = await sealed(env)
    outcomes = await asyncio.gather(
        issue(env, request_for(run, command_id="decide-a")),
        issue(env, request_for(run, command_id="decide-b")),
        return_exceptions=True,
    )
    winners = [item for item in outcomes if isinstance(item, q.QualityDisposition)]
    assert len(winners) == 1
    assert all(isinstance(item, StaleHeadError) for item in outcomes if not isinstance(item, q.QualityDisposition))


async def test_crash_after_the_lease_before_the_write_leaves_no_disposition_and_retry_succeeds(
    decision_host, monkeypatch
) -> None:
    env = decision_host
    run = await sealed(env)
    request = request_for(run)
    original = QualityDispositionRepository.append

    async def crash(self, *args, **kwargs):
        raise SystemExit("process lost before the disposition commit")

    monkeypatch.setattr(QualityDispositionRepository, "append", crash)
    with pytest.raises(SystemExit):
        await issue(env, request)
    async with env["factory"]() as session:
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(QualityDispositionModel))
        ).scalar_one() == 0
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(DispositionAuthorizationModel))
        ).scalar_one() == 1
    monkeypatch.setattr(QualityDispositionRepository, "append", original)
    assert (await issue(env, request)).decision == q.DispositionDecision.PASS


@pytest.mark.timeout(90)
async def test_disposition_expiry_is_checked_on_database_time(decision_host) -> None:
    env = decision_host
    run = await sealed(env)
    soon = (datetime.now(UTC) + timedelta(seconds=3)).isoformat()
    await issue(env, request_for(run, requested_expires_at=soon))
    await asyncio.sleep(4)
    assert "DISPOSITION_EXPIRED" in (await readiness(env, run)).reasons


@pytest.mark.parametrize(
    "table",
    [
        "m10_disposition_authorizations",
        "m10_quality_dispositions",
        "m10_disposition_commands",
        "m10_disposition_outbox",
    ],
)
async def test_raw_update_and_delete_are_refused(decision_host, table: str) -> None:
    env = decision_host
    run = await sealed(env)
    await issue(env, request_for(run))
    for statement in (f"UPDATE {table} SET user_id = user_id", f"DELETE FROM {table}"):
        with pytest.raises(sa.exc.DBAPIError, match="M10_IMMUTABLE_DISPOSITION_ROW"):
            async with env["factory"]() as session, session.begin():
                await session.execute(sa.text(statement))


async def failed_review_run(env):
    from r2.advanced_creative.exploration import uuid7

    finding = {
        "finding_id": uuid7(),
        "rule_id": "review",
        "severity": "BLOCKING",
        "subject_locator": "media",
        "evidence_digest": "sha256:" + "c" * 64,
    }
    probe = await technical(env)
    review = await human(env, human_request(env, status="FAIL", findings=[finding]))
    run = await seal(env, completion(env, [probe, review]))
    return run, finding


async def test_exact_finding_waiver_is_issued_and_ready(decision_host) -> None:
    env = decision_host
    run, finding = await failed_review_run(env)
    binding = {
        "rule_id": "review",
        "finding_id": finding["finding_id"],
        "scope": "review-required:human",
        "justification": "accepted for the export-only pilot",
    }
    soon = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    disposition = await issue(env, request_for(run, "WAIVE", waiver_bindings=[binding], requested_expires_at=soon))
    assert disposition.decision == q.DispositionDecision.WAIVE
    assert (await readiness(env, run)).state == "READY"


async def test_waiver_naming_another_finding_or_rule_is_forbidden(decision_host) -> None:
    env = decision_host
    run, _ = await failed_review_run(env)
    forged = {"rule_id": "review", "finding_id": None, "scope": "review-required:human", "justification": "x"}
    with pytest.raises(WaiverForbiddenError):
        await issue(env, request_for(run, "WAIVE", waiver_bindings=[forged]))


async def test_actor_without_a_grant_cannot_obtain_a_lease(decision_host) -> None:
    env = decision_host
    run = await sealed(env)
    request = request_for(run).model_dump(mode="json")
    request["command"]["actor_id"] = request["subject"]["actor_id"] = "intruder"
    request["command"]["request_digest"] = compute_digest("m10.disposition-request.v1", request)
    intruder = q.DispositionAuthorizationRequest.model_validate(request)
    root_dir, socket_dir = env["governance"]
    custodian = await DispositionCustodian.for_request(
        intruder,
        env["factory"],
        interactive_token=auth.create_token("intruder"),
        read_directory=root_dir / "read",
        socket_directory=socket_dir,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    with pytest.raises(DispositionUnauthorizedError):
        await DispositionService(env["factory"], custodian=custodian, project_root=env["project"]).issue(intruder)
    async with env["factory"]() as session:
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(DispositionAuthorizationModel))
        ).scalar_one() == 0


async def test_crash_before_the_lease_records_nothing(decision_host, monkeypatch) -> None:
    env = decision_host
    run = await sealed(env)

    async def crash(self, request):
        raise SystemExit("process lost before the lease")

    monkeypatch.setattr(DispositionCustodian, "authorize_disposition", crash)
    with pytest.raises(SystemExit):
        await issue(env, request_for(run))
    async with env["factory"]() as session:
        for model in (DispositionAuthorizationModel, QualityDispositionModel):
            assert (await session.execute(sa.select(sa.func.count()).select_from(model))).scalar_one() == 0


@pytest.mark.timeout(120)
async def test_a_lease_admitted_after_its_window_is_refused(decision_host, monkeypatch) -> None:
    env = decision_host
    run = await sealed(env)
    original = DispositionCustodian.admit

    async def late(self, session, request, lease):
        await asyncio.sleep(31)
        return await original(self, session, request, lease)

    monkeypatch.setattr(DispositionCustodian, "admit", late)
    with pytest.raises(DispositionUnauthorizedError):
        await issue(env, request_for(run))


async def test_concurrent_identical_commands_converge_on_one_disposition(decision_host) -> None:
    env = decision_host
    run = await sealed(env)
    request = request_for(run)
    first, second = await asyncio.gather(issue(env, request), issue(env, request))
    assert first == second
    async with env["factory"]() as session:
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(QualityDispositionModel))
        ).scalar_one() == 1
