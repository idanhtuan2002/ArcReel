"""The host preflight reads the project's current launch qualification, published profile and GPU capacity."""

from __future__ import annotations

import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa

from lib.db.models.production_run import LaunchQualificationModel
from lib.db.repositories.launch_qualifications import LaunchQualificationRepository
from lib.generation_resources import configure_device_admission
from lib.project_manager import ProjectManager
from r2.contracts.automation import LaunchQualification
from server.production_run.composition import HostPreflightReader, gpu_schedulable_bytes
from tests.integration.server.production_run.test_preflight import policy


def _record(**overrides) -> LaunchQualification:
    fields = {
        "owner": "launch-qualification",
        "receipt_ref": "qualification-run.json",
        "digest": "sha256:" + "e" * 64,
        "user_id": "default",
        "project_name": "project",
        "launch_profile_id": "fiction_narration_vi_v1",
        "profile_digest": "sha256:" + "a" * 64,
        "route_digests": ("sha256:" + "b" * 64,),
        "required_disk_bytes": 2 * 1024**3,
        "required_gpu_bytes": 7 * 1024**3,
        **overrides,
    }
    return LaunchQualification(**fields)


async def test_the_newest_intact_record_of_the_scope_is_current(session_factory) -> None:
    older, newer = _record(), _record(required_gpu_bytes=6 * 1024**3)
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        repository = LaunchQualificationRepository(session)
        await repository.record(older, at=now - timedelta(hours=1))
        digest = await repository.record(newer, at=now)
        assert await repository.record(newer, at=now) == digest
        await repository.record(_record(project_name="other"), at=now + timedelta(hours=1))

    async with session_factory() as session:
        repository = LaunchQualificationRepository(session)
        scope = {"user_id": "default", "project_name": "project", "launch_profile_id": "fiction_narration_vi_v1"}
        assert await repository.current(**scope) == newer
        assert await repository.current(**{**scope, "launch_profile_id": "fiction_drama_vi_v1"}) is None

    async with session_factory() as session, session.begin():
        await session.execute(
            sa.update(LaunchQualificationModel)
            .where(LaunchQualificationModel.qualification_digest == digest)
            .values(record_json=_record(required_gpu_bytes=1).model_dump_json())
        )
    async with session_factory() as session:
        assert await LaunchQualificationRepository(session).current(**scope) is None


class _Witness:
    async def digest(self, *, user_id: str, project_name: str) -> str:
        del user_id, project_name
        return "sha256:" + "c" * 64


class _Policies:
    async def routes(self, project_name: str):
        del project_name
        return ()


async def test_preflight_reads_the_launch_record_and_reports_an_unpublished_profile(session_factory, tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    projects.create_project("project", content_mode="narration")
    record = _record()
    async with session_factory() as session, session.begin():
        await LaunchQualificationRepository(session).record(record)

    snapshot = await HostPreflightReader(
        session_factory,
        projects=projects,
        policies=_Policies(),
        witness=_Witness(),
        gpu_free_bytes=lambda: 8 * 1024**3,
    ).read(user_id="default", project_name="project", policy=policy())

    assert snapshot.launch_qualification == record
    assert snapshot.profile is None
    assert snapshot.gpu_free_bytes == 8 * 1024**3


def _fake_smi(tmp_path: Path, body: str) -> str:
    script = tmp_path / "nvidia-smi"
    script.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


@pytest.mark.parametrize(("managed", "expected_mib"), [(True, 8192), (False, 1024)])
def test_gpu_capacity_counts_the_whole_device_only_under_managed_admission(tmp_path, managed, expected_mib) -> None:
    smi = _fake_smi(tmp_path, 'case "$1" in *memory.total*) echo 8192;; *memory.free*) echo 1024;; *) exit 1;; esac')
    configure_device_admission(object() if managed else None)
    try:
        assert gpu_schedulable_bytes(nvidia_smi=smi) == expected_mib * 1024 * 1024
    finally:
        configure_device_admission(None)


def test_an_unreadable_gpu_reports_no_capacity(tmp_path) -> None:
    assert gpu_schedulable_bytes(nvidia_smi=_fake_smi(tmp_path, "exit 9")) == 0
    assert gpu_schedulable_bytes(nvidia_smi=str(tmp_path / "missing")) == 0
