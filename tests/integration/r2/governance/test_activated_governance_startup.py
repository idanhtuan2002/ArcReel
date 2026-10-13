"""Activated startup needs current independent archive evidence, not public agreement alone."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.services.governance_attestation import serve_governance_attestor
from server.services.governance_startup import GovernanceStartupUnavailable, verify_governance_activated_startup
from tests.integration.r2.governance.test_operator_archive_reconcile import _ready_schema
from tests.unit.r2.governance.test_operator_archive_reader import _append_successor, _put, _tree


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["current", "coherent_old", "missing_attestor"])
async def test_pg_activated_startup_requires_independent_current_archive(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, state: str
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("activated startup requires PostgreSQL")
    await _ready_schema(engine)
    root, paths = _tree(tmp_path)
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    if state == "coherent_old":
        old_high = paths["public_high_water"].read_bytes()
        old_checkpoint = paths["public_checkpoint"].read_bytes()
        _append_successor(root, paths)
        _put(paths["public_high_water"], old_high, 0o644)
        _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    if state == "missing_attestor":
        with pytest.raises(GovernanceStartupUnavailable):
            await verify_governance_activated_startup(
                root / "read",
                runtime,
                session_factory=session_factory,
                expected_uid=os.getuid(),
                expected_gid=os.getgid(),
            )
        return
    async with serve_governance_attestor(
        root, runtime, session_factory=session_factory, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        if state == "current":
            reader = await verify_governance_activated_startup(
                root / "read",
                runtime,
                session_factory=session_factory,
                expected_uid=os.getuid(),
                expected_gid=os.getgid(),
            )
            assert reader is not None
        else:
            with pytest.raises(GovernanceStartupUnavailable):
                await verify_governance_activated_startup(
                    root / "read",
                    runtime,
                    session_factory=session_factory,
                    expected_uid=os.getuid(),
                    expected_gid=os.getgid(),
                )


def _configure_lifespan(session_factory, root: Path, runtime: Path, projects: Path, monkeypatch):
    from types import SimpleNamespace

    import server.app as app_module
    from lib.project_manager import ProjectManager
    from server.routers import assistant
    from tests.unit.server.test_app_module import _noop_async

    async def fixture_verify(read_directory: Path, socket_directory: Path, **_kwargs):
        return await verify_governance_activated_startup(
            read_directory,
            socket_directory,
            session_factory=session_factory,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )

    async def forbidden_init():
        raise AssertionError("activated startup called automatic migration")

    monkeypatch.setenv("ARCREEL_GOVERNANCE_READ_DIR", str(root / "read"))
    monkeypatch.setenv("ARCREEL_GOVERNANCE_ATTESTOR_DIR", str(runtime))
    monkeypatch.setenv("ARCREEL_DATA_DIR", str(projects))
    monkeypatch.setattr(app_module, "verify_governance_activated_startup", fixture_verify)
    monkeypatch.setattr(app_module, "async_session_factory", session_factory)
    monkeypatch.setattr(app_module, "app_data_dir", lambda: projects)
    monkeypatch.setattr(app_module, "PROJECT_ROOT", projects.parent)
    monkeypatch.setattr("lib.project_manager.get_project_manager", lambda: ProjectManager(projects))
    monkeypatch.setattr(app_module, "migrate_legacy_log_dir", lambda: None)
    monkeypatch.setattr(app_module, "attach_file_handler", lambda: None)
    monkeypatch.setattr(app_module, "ensure_auth_password", lambda: "test")
    monkeypatch.setattr(app_module, "init_db", forbidden_init)
    monkeypatch.setattr(assistant.assistant_service, "startup", _noop_async)
    monkeypatch.setattr(assistant.assistant_service.session_manager, "start_patrol", lambda: None)
    monkeypatch.setattr(app_module.app, "state", SimpleNamespace())


@pytest.mark.asyncio
async def test_pg_actual_activated_lifespan_starts_only_with_live_attestor(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import server.app as app_module

    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("activated lifespan requires PostgreSQL")
    await _ready_schema(engine)
    root, _paths = _tree(tmp_path)
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    projects = tmp_path / "projects"
    projects.mkdir()
    _configure_lifespan(session_factory, root, runtime, projects, monkeypatch)
    async with (
        serve_governance_attestor(
            root, runtime, session_factory=session_factory, expected_uid=os.getuid(), expected_gid=os.getgid()
        ),
        app_module.lifespan(app_module.app),
    ):
        assert app_module.app.state.generation_worker is not None
        assert app_module.app.state.governance_grants is not None
        assert app_module.app.state.spatial_review_sessions is not None
        assert app_module.app.state.spatial_pair_current_v2 is not None
        assert app_module.app.state.spatial_pair_decisions_v2 is not None
    assert not any(task.get_name() == "generation-worker" and not task.done() for task in asyncio.all_tasks())
