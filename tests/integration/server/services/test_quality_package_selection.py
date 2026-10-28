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


async def preview(env, request=None) -> p.PackagePreview:
    service = PackagePreviewService(sessions=env["factory"], grant_reader=env["reader"], project_root=env["project"])
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
