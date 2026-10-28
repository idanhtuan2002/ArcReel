"""M10-B package preview and Human selection into PACKAGING_SLOT on real PostgreSQL."""

from __future__ import annotations

import os
from typing import Any

import pytest
import sqlalchemy as sa

from lib.db.models.quality_packaging import PackageSelectionModel, PackagingHeadModel
from r2.contracts import packaging as p
from r2.quality.digests import compute_digest
from r2.quality.errors import (
    CommandReplayConflictError,
    DispositionStaleError,
    DispositionUnauthorizedError,
    StaleHeadError,
    SubjectStaleError,
    WaiverForbiddenError,
)
from server import auth
from server.services.quality_package_selection import (
    PackagePreviewService,
    PackageSelectionCustodian,
    PackageSelectionService,
)
from tests.integration.server.services.test_quality_dispositions import issue
from tests.integration.server.services.test_quality_dispositions import request_for as disposition_request
from tests.integration.server.services.test_quality_packaging import (
    append_candidate,
    candidate_for,
    check_request,
    service,
)
from tests.integration.server.services.test_quality_packaging import (
    packaging_host as packaging_host,
)
from tests.integration.server.services.test_quality_probes import ACTOR


@pytest.fixture
async def ready_host(packaging_host):
    env = packaging_host
    env["disposition"] = await issue(env, disposition_request(env["run"]))
    candidate = await append_candidate(env, candidate_for(env))
    env["candidate"] = candidate
    env["observation"] = await service(env).check(check_request(env, candidate))
    return env


def slot(env) -> dict[str, Any]:
    profile = env["profile"]
    return {
        "user_id": "default",
        "project_name": "project",
        "source_artifact_key": env["run"].subject.master_binding.root.artifact_key,
        "cohort_id": profile.cohort_id,
        "product_surface": profile.product_surface,
    }


def preview_request(env, *, command_id: str = "preview-1", **subject_changes: Any) -> p.PackagePreviewRequest:
    candidate = env["candidate"]
    body: dict[str, Any] = {
        "command": {
            "user_id": "default",
            "project_name": "project",
            "actor_id": ACTOR,
            "operation": "PREVIEW_PACKAGE",
            "command_id": command_id,
            "request_digest": "sha256:" + "0" * 64,
        },
        "subject": {
            "user_id": "default",
            "project_name": "project",
            "actor_id": ACTOR,
            "slot": slot(env),
            "candidate_id": candidate.candidate_id,
            "candidate_revision": candidate.revision,
            "candidate_payload_digest": candidate.payload_digest,
            "packaging_observation_id": env["observation"].observation_id,
            "selected_variant_ids": [],
            "waivers": [],
        }
        | subject_changes,
    }
    body["command"]["request_digest"] = compute_digest("m10.package-preview-request.v1", body)
    return p.PackagePreviewRequest.model_validate(body)


async def preview(env, request=None, *, seconds: int | None = None) -> p.PackagePreview:
    service = PackagePreviewService(
        sessions=env["factory"],
        grant_reader=env["reader"],
        project_root=env["project"],
        **({} if seconds is None else {"preview_seconds": seconds}),
    )
    return await service.preview(request or preview_request(env))


def selection_request(env, shown: p.PackagePreview, *, command_id: str = "select-1", version: int | None = None):
    body: dict[str, Any] = {
        "command": {
            "user_id": "default",
            "project_name": "project",
            "actor_id": ACTOR,
            "operation": "SELECT_PACKAGE",
            "command_id": command_id,
            "request_digest": "sha256:" + "0" * 64,
        },
        "subject": {
            "user_id": "default",
            "project_name": "project",
            "actor_id": ACTOR,
            "preview_id": shown.preview_id,
            "preview_digest": compute_digest("m10.package-preview.v1", shown),
            "expected_head_version": shown.expected_head_version if version is None else version,
        },
    }
    body["command"]["request_digest"] = compute_digest("m10.package-selection-request.v1", body)
    return p.PackageSelectionRequest.model_validate(body)


def custodian(env, request, *, token: str | None = "default") -> PackageSelectionCustodian:
    root_dir, socket_dir = env["governance"]
    return PackageSelectionCustodian(
        request,
        env["factory"],
        interactive_token=auth.create_token(ACTOR) if token == "default" else token,
        read_directory=root_dir / "read",
        socket_directory=socket_dir,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )


async def select(env, request, *, token: str | None = "default") -> p.PackageSelection:
    guard = custodian(env, request, token=token)
    lease = await guard.authorize_selection(request)
    return await PackageSelectionService(sessions=env["factory"], custodian=guard, project_root=env["project"]).select(
        request, lease
    )


async def test_a_human_selects_a_previewed_package_and_the_slot_head_advances(ready_host) -> None:
    env = ready_host
    shown = await preview(env)
    assert shown.disposition_id == env["disposition"].disposition_id
    assert shown.expected_head_version == 0
    assert await preview(env) == shown
    request = selection_request(env, shown)
    selection = await select(env, request)
    assert (selection.head_version, selection.selector_id) == (1, ACTOR)
    async with env["factory"]() as session:
        head = (await session.execute(sa.select(PackagingHeadModel))).scalar_one()
    assert (head.current_selection_id, head.head_version) == (selection.selection_id, 1)
    replay_guard = custodian(env, request)
    replay_lease = await replay_guard.authorize_selection(request)
    service_ = PackageSelectionService(sessions=env["factory"], custodian=replay_guard, project_root=env["project"])
    assert await service_.select(request, replay_lease) == selection


async def test_a_second_selection_needs_the_advanced_head_version(ready_host) -> None:
    env = ready_host
    first = await select(env, selection_request(env, await preview(env)))
    stale = await preview(env, preview_request(env, command_id="preview-2"))
    assert stale.expected_head_version == 1
    with pytest.raises(StaleHeadError):
        await select(env, selection_request(env, stale, command_id="select-2", version=0))
    second = await select(env, selection_request(env, stale, command_id="select-3"))
    assert (first.head_version, second.head_version) == (1, 2)


async def test_only_the_authenticated_showrunner_can_select(ready_host) -> None:
    env = ready_host
    request = selection_request(env, await preview(env))
    for token in (None, "not-a-token", auth.create_token("agent")):
        with pytest.raises(DispositionUnauthorizedError):
            await select(env, request, token=token)
    async with env["factory"]() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(PackageSelectionModel))).scalar_one() == 0


async def test_a_superseding_disposition_stales_an_unselected_preview(ready_host) -> None:
    env = ready_host
    shown = await preview(env)
    await issue(env, disposition_request(env["run"], "REWORK", command_id="decide-2", version=1))
    with pytest.raises(DispositionStaleError):
        await select(env, selection_request(env, shown))


async def test_unwaived_blocking_findings_and_stray_waivers_are_refused(ready_host) -> None:
    env = ready_host
    with pytest.raises(WaiverForbiddenError):
        await preview(
            env,
            preview_request(
                env,
                waivers=[{"rule_id": "title-length", "finding_id": env["observation"].observation_id, "reason": "x"}],
            ),
        )


async def test_a_reused_preview_command_with_another_request_conflicts(ready_host) -> None:
    env = ready_host
    await preview(env)
    with pytest.raises(CommandReplayConflictError):
        await preview(env, preview_request(env, selected_variant_ids=["t1"]))


async def test_two_selections_racing_for_one_slot_have_one_winner(ready_host) -> None:
    import asyncio

    env = ready_host
    first = selection_request(env, await preview(env), command_id="select-a")
    second = selection_request(
        env, await preview(env, preview_request(env, command_id="preview-b")), command_id="select-b"
    )
    guards = [custodian(env, first), custodian(env, second)]
    leases = [await guards[0].authorize_selection(first), await guards[1].authorize_selection(second)]
    services = [
        PackageSelectionService(sessions=env["factory"], custodian=guard, project_root=env["project"])
        for guard in guards
    ]
    results = await asyncio.gather(
        services[0].select(first, leases[0]), services[1].select(second, leases[1]), return_exceptions=True
    )
    winners = [r for r in results if isinstance(r, p.PackageSelection)]
    losers = [r for r in results if not isinstance(r, p.PackageSelection)]
    assert len(winners) == 1
    assert [type(r) for r in losers] == [StaleHeadError]


async def test_selection_racing_a_superseding_disposition_never_deadlocks(ready_host) -> None:
    import asyncio

    env = ready_host
    request = selection_request(env, await preview(env))
    guard = custodian(env, request)
    lease = await guard.authorize_selection(request)
    selecting = PackageSelectionService(sessions=env["factory"], custodian=guard, project_root=env["project"])
    results = await asyncio.wait_for(
        asyncio.gather(
            selecting.select(request, lease),
            issue(env, disposition_request(env["run"], "REWORK", command_id="decide-2", version=1)),
            return_exceptions=True,
        ),
        timeout=60,
    )
    selection, disposition = results
    assert not isinstance(disposition, BaseException), disposition
    assert isinstance(selection, (p.PackageSelection, DispositionStaleError)), selection


# --- refusal paths (no selection and no head advancement on any refusal) ---


async def _counts(env) -> tuple[int, int]:
    async with env["factory"]() as session:
        selections = (await session.execute(sa.select(sa.func.count()).select_from(PackageSelectionModel))).scalar_one()
        heads = (await session.execute(sa.select(sa.func.count()).select_from(PackagingHeadModel))).scalar_one()
    return selections, heads


async def _failing_host(env, *, title: str, revision: int = 2):
    payload = candidate_for(env, title=title)
    candidate = await append_candidate(env, payload, revision=revision)
    env["candidate"] = candidate
    env["observation"] = await service(env).check(check_request(env, candidate, command_id=f"check-{revision}"))
    return env["observation"]


def _waiver(finding, *, rule_id: str | None = None) -> dict[str, str]:
    return {"rule_id": rule_id or finding.rule_id, "finding_id": finding.finding_id, "reason": "brand title"}


async def test_an_exactly_waived_waivable_failure_is_selectable(ready_host) -> None:
    env = ready_host
    observation = await _failing_host(env, title="A history of the river " * 6)
    assert observation.status.value == "FAIL"
    assert {f.rule_id for f in observation.findings} == {"title-length"}
    shown = await preview(env, preview_request(env, waivers=[_waiver(f) for f in observation.findings]))
    selection = await select(env, selection_request(env, shown))
    assert [w.finding_id for w in selection.preview.waivers] == sorted(f.finding_id for f in observation.findings)


@pytest.mark.parametrize("coverage", ["none", "wrong_rule"])
async def test_incomplete_or_mislabelled_waivers_are_forbidden(ready_host, coverage: str) -> None:
    env = ready_host
    observation = await _failing_host(env, title="A history of the river " * 6)
    waivers = [] if coverage == "none" else [_waiver(f, rule_id="duration") for f in observation.findings]
    with pytest.raises(WaiverForbiddenError):
        await preview(env, preview_request(env, waivers=waivers))
    assert await _counts(env) == (0, 0)


async def test_an_unwaivable_blocking_failure_can_never_be_selected(ready_host) -> None:
    env = ready_host
    payload = candidate_for(env)
    asset = payload.assets[0].model_dump(mode="python") | {"byte_size": payload.assets[0].byte_size + 1}
    candidate = await append_candidate(env, candidate_for(env, assets=[asset]), revision=2)
    env["candidate"] = candidate
    observation = await service(env).check(check_request(env, candidate, command_id="check-2"))
    env["observation"] = observation
    with pytest.raises(WaiverForbiddenError):
        await preview(env, preview_request(env, waivers=[_waiver(f) for f in observation.findings]))


async def test_a_lease_for_another_request_cannot_authorize_this_one(ready_host) -> None:
    env = ready_host
    shown = await preview(env)
    issued = selection_request(env, shown, command_id="select-a")
    other = selection_request(env, shown, command_id="select-b")
    lease = await custodian(env, issued).authorize_selection(issued)
    guard = custodian(env, other)
    await guard.authorize_selection(other)
    with pytest.raises(DispositionUnauthorizedError):
        await PackageSelectionService(sessions=env["factory"], custodian=guard, project_root=env["project"]).select(
            other, lease
        )
    assert await _counts(env) == (0, 0)


async def test_a_lease_admitted_after_its_window_is_refused(ready_host, monkeypatch) -> None:
    from datetime import timedelta

    from lib.db.repositories.quality_packaging import PackageSelectionRepository

    env = ready_host
    request = selection_request(env, await preview(env))
    guard = custodian(env, request)
    lease = await guard.authorize_selection(request)
    original = PackageSelectionRepository.database_now

    async def later(self):
        return (await original(self)) + timedelta(seconds=31)

    monkeypatch.setattr(PackageSelectionRepository, "database_now", later)
    with pytest.raises(DispositionUnauthorizedError):
        await PackageSelectionService(sessions=env["factory"], custodian=guard, project_root=env["project"]).select(
            request, lease
        )
    assert await _counts(env) == (0, 0)


async def test_a_newer_run_stales_the_preview(ready_host) -> None:
    from tests.integration.server.services.test_quality_runs import completion, human, human_request, seal, technical

    env = ready_host
    shown = await preview(env)
    probe = await technical(env)
    review = await human(env, human_request(env, command_id="human-2"))
    await seal(env, completion(env, [probe, review], command_id="seal-2"))
    with pytest.raises(DispositionStaleError):
        await select(env, selection_request(env, shown))
    assert await _counts(env) == (0, 0)


@pytest.mark.parametrize("choice", [[], ["t1", "t2"], ["unknown"]])
async def test_exactly_one_known_alternative_per_group_is_required(ready_host, choice: list[str]) -> None:
    from tests.unit.r2.contracts.test_packaging import candidate_body

    env = ready_host
    groups = candidate_body()["variant_groups"]
    candidate = await append_candidate(env, candidate_for(env, variant_groups=groups), revision=2)
    env["candidate"] = candidate
    env["observation"] = await service(env).check(check_request(env, candidate, command_id="check-2"))
    from r2.quality.errors import RequiredEvidenceMissingError

    with pytest.raises(RequiredEvidenceMissingError):
        await preview(env, preview_request(env, selected_variant_ids=choice))
    assert (
        await preview(env, preview_request(env, command_id="preview-ok", selected_variant_ids=["t2"]))
    ).selected_variant_ids == ("t2",)


async def test_a_reused_selection_command_for_another_preview_conflicts(ready_host) -> None:
    env = ready_host
    await select(env, selection_request(env, await preview(env)))
    other = await preview(env, preview_request(env, command_id="preview-2"))
    with pytest.raises(CommandReplayConflictError):
        await select(env, selection_request(env, other))


async def test_concurrent_identical_selections_record_one(ready_host) -> None:
    import asyncio

    env = ready_host
    request = selection_request(env, await preview(env))
    guards = [custodian(env, request), custodian(env, request)]
    leases = [await guard.authorize_selection(request) for guard in guards]
    services = [
        PackageSelectionService(sessions=env["factory"], custodian=guard, project_root=env["project"])
        for guard in guards
    ]
    first, second = await asyncio.gather(
        *(svc.select(request, lease) for svc, lease in zip(services, leases, strict=True))
    )
    assert first == second
    assert await _counts(env) == (1, 1)


# --- writer pairs with an observed blocked waiter (design §4) ---


class Gate:
    """Pauses one writer after it holds its locks; only the first call through the patched seam waits."""

    def __init__(self) -> None:
        import asyncio

        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.used = False
        self.pid: int | None = None

    def wrap(self, real):
        async def paused(session, *args, **kwargs):
            if not self.used:
                self.used = True
                self.pid = (await session.execute(sa.text("SELECT pg_backend_pid()"))).scalar_one()
                self.entered.set()
                await self.release.wait()
            return await real(session, *args, **kwargs)

        return paused


async def blocked_by(env, gate: Gate, attempts: int = 400) -> str:
    """The statement of the backend the paused writer blocks (polled, bounded); proves who waits on what."""
    import asyncio

    assert gate.pid is not None
    for _ in range(attempts):
        async with env["factory"]() as session:
            query = (
                await session.execute(
                    sa.text(
                        "SELECT query FROM pg_stat_activity WHERE datname = current_database() "
                        "AND :holder = ANY(pg_blocking_pids(pid))"
                    ),
                    {"holder": gate.pid},
                )
            ).scalar_one_or_none()
        if query is not None:
            return query
        await asyncio.sleep(0.05)
    async with env["factory"]() as session:
        seen = (
            await session.execute(
                sa.text(
                    "SELECT pid, wait_event_type, pg_blocking_pids(pid), left(query, 120) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                )
            )
        ).all()
    gate.release.set()
    raise AssertionError(f"no writer blocked on paused pid {gate.pid}: {seen}")


async def assert_blocked(env, gate: Gate, *tables: str) -> None:
    """The paused writer blocks a contender on one of ``tables``; the gate is released on any failure."""
    try:
        query = await blocked_by(env, gate)
        if not any(table in query for table in tables):
            raise AssertionError(f"blocked on an unexpected lock: {query}")
    except BaseException:
        gate.release.set()
        raise


async def _paused_selection(env, monkeypatch, request):
    import asyncio

    from server.services import quality_package_selection as module

    guard = custodian(env, request)
    lease = await guard.authorize_selection(request)
    gate = Gate()
    monkeypatch.setattr(module, "readiness_in", gate.wrap(module.readiness_in))
    task = asyncio.create_task(
        PackageSelectionService(sessions=env["factory"], custodian=guard, project_root=env["project"]).select(
            request, lease
        )
    )
    await asyncio.wait_for(gate.entered.wait(), 20)
    return gate, task


async def test_a_disposition_issued_during_a_selection_waits_then_supersedes(ready_host, monkeypatch) -> None:
    import asyncio

    env = ready_host
    gate, selecting = await _paused_selection(env, monkeypatch, selection_request(env, await preview(env)))
    issuing = asyncio.create_task(
        issue(env, disposition_request(env["run"], "REWORK", command_id="decide-2", version=1))
    )
    # The issuer's lease transaction already needs the selector's locked grant head.
    await assert_blocked(env, gate, "r2_showrunner_grant_heads")
    assert not issuing.done()
    gate.release.set()
    selection = await asyncio.wait_for(selecting, 60)
    disposition = await asyncio.wait_for(issuing, 60)
    assert selection.head_version == 1
    assert disposition.supersedes_disposition_id == env["disposition"].disposition_id


async def test_a_selection_during_a_disposition_waits_then_sees_it_stale(ready_host, monkeypatch) -> None:
    import asyncio

    from server.services import quality_dispositions as dispositions

    env = ready_host
    request = selection_request(env, await preview(env))
    guard = custodian(env, request)
    lease = await guard.authorize_selection(request)
    gate = Gate()
    monkeypatch.setattr(dispositions, "load_run_observations", gate.wrap(dispositions.load_run_observations))
    issuing = asyncio.create_task(
        issue(env, disposition_request(env["run"], "REWORK", command_id="decide-2", version=1))
    )
    await asyncio.wait_for(gate.entered.wait(), 20)
    selecting = asyncio.create_task(
        PackageSelectionService(sessions=env["factory"], custodian=guard, project_root=env["project"]).select(
            request, lease
        )
    )
    await assert_blocked(env, gate, "master_authorities")
    gate.release.set()
    await asyncio.wait_for(issuing, 60)
    with pytest.raises(DispositionStaleError):
        await asyncio.wait_for(selecting, 60)
    assert await _counts(env) == (0, 0)


async def test_a_run_sealed_during_a_selection_waits_and_then_supersedes(ready_host, monkeypatch) -> None:
    import asyncio

    from tests.integration.server.services.test_quality_runs import completion, human, human_request, seal, technical

    env = ready_host
    probe = await technical(env)
    review = await human(env, human_request(env, command_id="human-2"))
    gate, selecting = await _paused_selection(env, monkeypatch, selection_request(env, await preview(env)))
    sealing = asyncio.create_task(seal(env, completion(env, [probe, review], command_id="seal-2")))
    # The seal reads its Human grant under lock first; it serializes on the selection there.
    await assert_blocked(env, gate, "r2_showrunner_grant_heads", "master_authorities")
    assert not sealing.done()
    gate.release.set()
    assert (await asyncio.wait_for(selecting, 60)).head_version == 1
    newer = await asyncio.wait_for(sealing, 60)
    assert newer.run_id != env["run"].run_id


async def test_a_profile_published_during_a_selection_waits_for_it(ready_host, monkeypatch) -> None:
    import asyncio

    from tests.integration.lib.db.repositories.test_quality_profiles_repository import append, request_for
    from tests.integration.server.services.test_quality_packaging import v2_policy

    env = ready_host
    gate, selecting = await _paused_selection(env, monkeypatch, selection_request(env, await preview(env)))
    publishing = asyncio.create_task(
        append(env["factory"], request_for(2, "publish-2", policy=v2_policy(env["config"])))
    )
    # Publication does not touch masters: it waits on the profile head the selection holds FOR SHARE.
    await assert_blocked(env, gate, "m10_quality_profile_heads")
    assert not publishing.done()
    gate.release.set()
    assert (await asyncio.wait_for(selecting, 60)).head_version == 1
    assert (await asyncio.wait_for(publishing, 60)).revision == 2


async def test_a_second_selection_waits_on_the_subject_masters_and_then_is_stale(ready_host, monkeypatch) -> None:
    import asyncio

    env = ready_host
    first = selection_request(env, await preview(env), command_id="select-a")
    second = selection_request(
        env, await preview(env, preview_request(env, command_id="preview-b")), command_id="select-b"
    )
    second_guard = custodian(env, second)
    second_lease = await second_guard.authorize_selection(second)
    gate, selecting = await _paused_selection(env, monkeypatch, first)
    racing = asyncio.create_task(
        PackageSelectionService(sessions=env["factory"], custodian=second_guard, project_root=env["project"]).select(
            second, second_lease
        )
    )
    # Same subject: the second selection serializes on the subject's master rows before any head.
    await assert_blocked(env, gate, "master_authorities")
    gate.release.set()
    assert (await asyncio.wait_for(selecting, 60)).head_version == 1
    with pytest.raises(StaleHeadError):
        await asyncio.wait_for(racing, 60)


async def test_selection_locks_one_sorted_grant_set_with_the_selector_before_readiness(ready_host, monkeypatch) -> None:
    from server.services import quality_package_selection as module

    env = ready_host
    request = selection_request(env, await preview(env))
    calls: list[str] = []
    real_lock, real_readiness = module.lock_grant_heads, module.readiness_in

    async def lock(session, *, user_id, project_name, principals):
        calls.append("grants:" + ",".join(sorted(principals)))
        return await real_lock(session, user_id=user_id, project_name=project_name, principals=principals)

    async def readiness(*args, **kwargs):
        calls.append("readiness")
        return await real_readiness(*args, **kwargs)

    monkeypatch.setattr(module, "lock_grant_heads", lock)
    monkeypatch.setattr(module, "readiness_in", readiness)
    await select(env, request)
    assert calls[:2] == [f"grants:{ACTOR}", "readiness"]


async def test_a_preview_never_outlives_its_disposition(packaging_host) -> None:
    from datetime import UTC, datetime, timedelta

    env = packaging_host
    expires = (datetime.now(UTC) + timedelta(seconds=120)).isoformat()
    env["disposition"] = await issue(env, disposition_request(env["run"], requested_expires_at=expires))
    env["candidate"] = await append_candidate(env, candidate_for(env))
    env["observation"] = await service(env).check(check_request(env, env["candidate"]))
    shown = await preview(env)
    assert shown.expires_at == env["disposition"].expires_at


async def test_an_expired_preview_is_refused(ready_host) -> None:
    import asyncio

    env = ready_host
    shown = await preview(env, seconds=1)
    await asyncio.sleep(1.2)
    with pytest.raises(DispositionStaleError):
        await select(env, selection_request(env, shown))
    assert await _counts(env) == (0, 0)


async def test_a_master_promoted_after_the_preview_stales_it(ready_host) -> None:
    from tests.integration.server.services.test_quality_probe_recipes import FIXTURES
    from tests.integration.server.services.test_quality_probes import promote

    env = ready_host
    shown = await preview(env)
    await promote(env["factory"], env["project"], FIXTURES / "av.mp4", "2")
    with pytest.raises((DispositionStaleError, SubjectStaleError)):
        await select(env, selection_request(env, shown))
    assert await _counts(env) == (0, 0)


@pytest.mark.parametrize("field", ["source_artifact_key", "cohort_id", "product_surface", "project_name"])
async def test_a_preview_for_another_slot_is_refused(ready_host, field: str) -> None:
    env = ready_host
    other = slot(env) | {field: "elsewhere"}
    with pytest.raises((SubjectStaleError, ValueError)):
        await preview(env, preview_request(env, slot=other))


async def test_a_reevaluating_profile_published_first_stales_the_selection(ready_host) -> None:
    from tests.integration.lib.db.repositories.test_quality_profiles_repository import append, request_for
    from tests.integration.server.services.test_quality_packaging import v2_policy

    env = ready_host
    shown = await preview(env)
    await append(
        env["factory"],
        request_for(2, "publish-2", policy=v2_policy(env["config"]), supersession_effect="REEVALUATE_CURRENT"),
    )
    with pytest.raises(DispositionStaleError):
        await select(env, selection_request(env, shown))
    assert await _counts(env) == (0, 0)


async def test_a_lease_for_one_preview_cannot_select_another(ready_host) -> None:
    env = ready_host
    first = selection_request(env, await preview(env), command_id="select-a")
    other = selection_request(
        env, await preview(env, preview_request(env, command_id="preview-b")), command_id="select-a"
    )
    lease = await custodian(env, first).authorize_selection(first)
    guard = custodian(env, other)
    await guard.authorize_selection(other)
    with pytest.raises(DispositionUnauthorizedError):
        await PackageSelectionService(sessions=env["factory"], custodian=guard, project_root=env["project"]).select(
            other, lease
        )
    assert await _counts(env) == (0, 0)


async def test_packaging_evidence_tampered_after_the_preview_is_refused(ready_host) -> None:
    from r2.quality.errors import RequiredEvidenceMissingError

    env = ready_host
    shown = await preview(env)
    async with env["factory"]() as session, session.begin():
        await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            sa.text("UPDATE m10_packaging_observations SET observation_digest = 'sha256:' || repeat('0', 64)")
        )
    with pytest.raises(RequiredEvidenceMissingError):
        await select(env, selection_request(env, shown))
    assert await _counts(env) == (0, 0)


async def test_one_alternative_per_group_across_several_groups_is_selected(ready_host) -> None:
    env = ready_host
    groups = [
        {
            "group_id": field,
            "field": field,
            "variants": [
                {
                    "variant_id": f"{field}-{n}",
                    "value": {"text": text},
                    "asset_role": None,
                    "provenance": {"author_kind": "AGENT", "actor_id": "agent"},
                }
                for n, text in enumerate(texts)
            ],
        }
        for field, texts in (
            ("title", ["A history of the river", "The river that made a valley"]),
            (
                "description",
                [
                    "How the river shaped the valley over ten thousand years.",
                    "A valley shaped by water over ten millennia.",
                ],
            ),
        )
    ]
    candidate = await append_candidate(env, candidate_for(env, variant_groups=groups), revision=2)
    env["candidate"] = candidate
    env["observation"] = await service(env).check(check_request(env, candidate, command_id="check-2"))
    assert env["observation"].status.value == "PASS", env["observation"].findings
    shown = await preview(env, preview_request(env, selected_variant_ids=["title-1", "description-0"]))
    selection = await select(env, selection_request(env, shown))
    assert selection.preview.selected_variant_ids == ("description-0", "title-1")


async def test_a_grant_revoked_after_the_lease_refuses_the_selection(ready_host) -> None:
    from r2.governance.grant_transition import GrantScopeV1
    from tests.integration.r2.governance.test_grant_importer import _event, _signed

    env = ready_host
    request = selection_request(env, await preview(env))
    guard = custodian(env, request)
    lease = await guard.authorize_selection(request)
    importer, key, event = env["grant"]
    body = _event("REVOKE", 2, event.event_digest, "2026-10-27T00:00:00Z", project_name="project")
    body.update(user_id="default", principal=ACTOR, signer_key_id="grant-key-a")
    await importer.import_event(_signed(body, key), scope=GrantScopeV1("default", "project", ACTOR))
    # Revocation also invalidates the run's Human evidence, so readiness may refuse before lease admission.
    with pytest.raises((DispositionUnauthorizedError, DispositionStaleError)):
        await PackageSelectionService(sessions=env["factory"], custodian=guard, project_root=env["project"]).select(
            request, lease
        )
    assert await _counts(env) == (0, 0)


async def test_a_lease_whose_selection_crashed_leaves_nothing_and_a_retry_selects(ready_host, monkeypatch) -> None:
    from lib.db.repositories.quality_packaging import PackageSelectionRepository

    env = ready_host
    request = selection_request(env, await preview(env))
    guard = custodian(env, request)
    lease = await guard.authorize_selection(request)
    real = PackageSelectionRepository.append_selection
    failed = {"once": True}

    async def crash_once(self, *args, **kwargs):
        if failed.pop("once", False):
            raise RuntimeError("crash after the lease, inside the selection write")
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(PackageSelectionRepository, "append_selection", crash_once)
    service = PackageSelectionService(sessions=env["factory"], custodian=guard, project_root=env["project"])
    with pytest.raises(RuntimeError):
        await service.select(request, lease)
    assert await _counts(env) == (0, 0)
    retry_guard = custodian(env, request)
    retry_lease = await retry_guard.authorize_selection(request)
    selection = await PackageSelectionService(
        sessions=env["factory"], custodian=retry_guard, project_root=env["project"]
    ).select(request, retry_lease)
    assert selection.head_version == 1
    assert await _counts(env) == (1, 1)
