from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from r2.host_hardening.paid_routes import (
    PaidRoute,
    PaidRouteUnqualifiedError,
    media_route,
    require_paid_route,
    route_binding,
    set_qualification_lookup,
)
from r2.host_hardening.provider_capabilities import ReleaseMode
from r2.host_hardening.route_qualifications import (
    ROUTE_ADAPTER_VERSIONS,
    install_runtime_qualification_lookup,
    is_route_qualified,
    load_qualifications,
    qualifications_dir,
    record_qualification,
)

NOW = datetime(2026, 9, 28, tzinfo=UTC)
EVIDENCE = {"schema_version": 1, "result": "PASS"}
BINDING = route_binding(provider_id="openai", media_type="image", api_key="sk-1", base_url=None)


@pytest.fixture(autouse=True)
def reset_lookup():
    yield
    set_qualification_lookup(None)


def _record(
    root: Path,
    route: PaidRoute,
    model: str = "m1",
    *,
    binding: str = BINDING,
    expires_in: timedelta = timedelta(days=30),
):
    return record_qualification(
        route=route,
        model_id=model,
        binding=binding,
        evidence=EVIDENCE,
        expires_at=NOW + expires_in,
        cost_record_ref="api_call:7",
        recorded_by="operator",
        now=NOW,
        root=root,
    )


def _qualified(route: PaidRoute, root: Path, *, model: str = "m1", binding: str = BINDING, now: datetime = NOW) -> bool:
    return is_route_qualified(route, model, binding, now=now, root=root)


def test_a_recorded_canary_qualifies_exactly_its_route_model_and_configuration(tmp_path: Path) -> None:
    route = media_route("openai", "image")
    _record(tmp_path, route)

    assert _qualified(route, tmp_path)
    assert not _qualified(route, tmp_path, model="m2")
    assert not _qualified(media_route("openai", "text"), tmp_path)
    assert not _qualified(route, tmp_path, binding=route_binding(provider_id="openai", api_key="sk-2"))
    assert not is_route_qualified(route, "m1", None, now=NOW, root=tmp_path)


def test_a_custom_provider_qualification_does_not_cover_another_custom_provider(tmp_path: Path) -> None:
    _record(tmp_path, media_route("custom-7", "image"))
    assert _qualified(media_route("custom-7", "image"), tmp_path)
    assert not _qualified(media_route("custom-9", "image"), tmp_path)


def test_requalifying_replaces_the_earlier_record(tmp_path: Path) -> None:
    route = media_route("openai", "image")
    _record(tmp_path, route)
    _record(tmp_path, route, expires_in=timedelta(days=60))
    records = load_qualifications(tmp_path)
    assert [(r.route_ref, r.model_id) for r in records] == [("media:openai:image", "m1")]


def test_an_expired_qualification_no_longer_counts(tmp_path: Path) -> None:
    route = media_route("openai", "image")
    _record(tmp_path, route, expires_in=timedelta(days=1))
    assert not _qualified(route, tmp_path, now=NOW + timedelta(days=2))


def test_an_adapter_version_change_invalidates_the_qualification(tmp_path: Path, monkeypatch) -> None:
    route = media_route("openai", "image")
    _record(tmp_path, route)
    monkeypatch.setitem(ROUTE_ADAPTER_VERSIONS, "media:image", "host-media-v2")
    assert not _qualified(route, tmp_path)


def test_tampered_evidence_invalidates_the_qualification(tmp_path: Path) -> None:
    route = media_route("openai", "image")
    record = _record(tmp_path, route)
    (qualifications_dir(tmp_path) / record.evidence_path).write_text('{"result": "FAIL"}')
    assert not _qualified(route, tmp_path)


def test_a_malformed_records_file_fails_closed(tmp_path: Path) -> None:
    route = media_route("openai", "image")
    _record(tmp_path, route)
    (qualifications_dir(tmp_path) / "qualifications.json").write_text("{not json")
    assert load_qualifications(tmp_path) == []
    assert not _qualified(route, tmp_path)


@pytest.mark.parametrize("route", [media_route("openai", "video"), media_route("custom-3", "video")])
def test_an_async_video_route_also_needs_its_adapter_verified_offline(tmp_path: Path, route: PaidRoute) -> None:
    """The shipped video adapter profiles are UNQUALIFIED, so a canary alone does not qualify the route."""
    _record(tmp_path, route)
    assert not _qualified(route, tmp_path)


@pytest.mark.parametrize("route", [PaidRoute("agent", provider_id="anthropic-official"), PaidRoute("trial_run")])
def test_the_agent_and_trial_runs_cannot_be_qualified(tmp_path: Path, route: PaidRoute) -> None:
    with pytest.raises(ValueError, match="cannot be qualified"):
        _record(tmp_path, route)
    assert not _qualified(route, tmp_path)


def test_the_installed_lookup_opens_the_release_gate(tmp_path: Path) -> None:
    route = media_route("openai", "image")
    # 安装的 lookup 按真实时钟判时效：给足有效期，用例不随日期漂移。
    _record(tmp_path, route, expires_in=timedelta(days=36500))
    install_runtime_qualification_lookup(root=tmp_path)

    gate = ReleaseMode.PRODUCTION_CANDIDATE
    assert require_paid_route(route, model_id="m1", binding=BINDING, release_mode=gate) is None
    with pytest.raises(PaidRouteUnqualifiedError):
        require_paid_route(route, model_id="m1", binding="sha256:other", release_mode=gate)


def test_a_stale_lock_from_a_killed_writer_is_cleared(tmp_path: Path) -> None:
    import os
    import time

    route = media_route("openai", "image")
    directory = qualifications_dir(tmp_path)
    directory.mkdir(parents=True)
    lock = directory / ".lock"
    lock.write_text("")
    old = time.time() - 3600
    os.utime(lock, (old, old))

    _record(tmp_path, route)

    assert _qualified(route, tmp_path)
    assert not lock.exists()
