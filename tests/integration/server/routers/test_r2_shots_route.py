"""POST /r2/shots/{target}/generate queues one admitted spatial shot with its exact evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.task import Task
from lib.generation_queue import R2_SHOT_GENERATION_TASK_TYPE
from r2.contracts.shot_generation import R2ShotGenerationTaskV1
from r2.production_intelligence.shot_identity import verify_task_evidence
from r2.production_intelligence.shot_profiles import WAN27_TWO_VIEW_PROFILE
from tests.integration.server.routers.test_gates_export import PROJECT
from tests.integration.server.routers.test_r2_shot_admission import _admissible_shot

type Factory = async_sessionmaker[AsyncSession]


def _body(command, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "command_id": command.command_id,
        "expected_target_registry_version": command.expected_target_registry_version,
        "expected_binding_snapshot_digest": command.expected_binding_snapshot_digest,
        "execution_profile_ref": WAN27_TWO_VIEW_PROFILE.profile_ref,
    }
    body.update(overrides)
    return body


async def test_an_admitted_shot_is_queued_once_with_its_evidence(
    gate_export_client: AsyncClient,
    shots_client: AsyncClient,
    project_dir: Path,
    session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = await _admissible_shot(gate_export_client, project_dir, session_factory, monkeypatch)
    url = f"/api/v1/projects/{PROJECT}/r2/shots/{command.target_id}/generate"

    first = await shots_client.post(url, json=_body(command))
    replay = await shots_client.post(url, json=_body(command))
    changed = await shots_client.post(url, json=_body(command, expected_binding_snapshot_digest="sha256:" + "0" * 64))

    assert first.status_code == 200, first.text
    assert replay.json() == first.json()
    assert changed.status_code == 409
    async with session_factory() as session:
        tasks = list((await session.execute(select(Task))).scalars())
    assert [(t.task_id, t.task_type, t.resource_id) for t in tasks] == [
        (first.json()["task_id"], R2_SHOT_GENERATION_TASK_TYPE, command.target_id)
    ]
    evidence = R2ShotGenerationTaskV1.model_validate(json.loads(tasks[0].payload_json))
    verify_task_evidence(evidence, WAN27_TWO_VIEW_PROFILE)
    assert first.json()["host_request_digest"] == evidence.host_request_digest


async def test_a_refused_or_stale_shot_queues_nothing(
    gate_export_client: AsyncClient,
    shots_client: AsyncClient,
    project_dir: Path,
    session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = await _admissible_shot(gate_export_client, project_dir, session_factory, monkeypatch, duration=30.0)
    url = f"/api/v1/projects/{PROJECT}/r2/shots/{command.target_id}/generate"

    refused = await shots_client.post(url, json=_body(command))
    stale = await shots_client.post(
        url, json=_body(command, command_id="shot-2", expected_binding_snapshot_digest="sha256:" + "0" * 64)
    )
    unknown = await shots_client.post(url, json=_body(command, command_id="shot-3", execution_profile_ref="nope@1"))

    assert refused.status_code == 409
    assert stale.status_code == 409
    assert unknown.status_code == 409
    async with session_factory() as session:
        assert list((await session.execute(select(Task))).scalars()) == []
