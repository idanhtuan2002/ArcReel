from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from r2.host_hardening.paid_routes import (
    PaidRoute,
    PaidRouteUnqualifiedError,
    media_route,
    require_paid_route,
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


@pytest.fixture(autouse=True)
def reset_lookup():
    yield
    set_qualification_lookup(None)


def _record(root: Path, route: PaidRoute, model: str = "m1", *, expires_in: timedelta = timedelta(days=30)):
    return record_qualification(
        route=route,
        model_id=model,
        evidence=EVIDENCE,
        expires_at=NOW + expires_in,
        cost_record_ref="api_call:7",
        recorded_by="operator",
        now=NOW,
        root=root,
    )


def test_a_recorded_canary_qualifies_exactly_its_route_and_model(tmp_path: Path) -> None:
    route = media_route("openai", "image")
    _record(tmp_path, route)

    assert is_route_qualified(route, "m1", now=NOW, root=tmp_path)
    assert not is_route_qualified(route, "m2", now=NOW, root=tmp_path)
    assert not is_route_qualified(media_route("openai", "text"), "m1", now=NOW, root=tmp_path)


def test_requalifying_replaces_the_earlier_record(tmp_path: Path) -> None:
    route = media_route("openai", "image")
    _record(tmp_path, route)
    _record(tmp_path, route, expires_in=timedelta(days=60))
    records = load_qualifications(tmp_path)
    assert [(r.route_ref, r.model_id) for r in records] == [("media:openai:image", "m1")]


def test_an_expired_qualification_no_longer_counts(tmp_path: Path) -> None:
    route = media_route("openai", "image")
    _record(tmp_path, route, expires_in=timedelta(days=1))
    assert not is_route_qualified(route, "m1", now=NOW + timedelta(days=2), root=tmp_path)


def test_an_adapter_version_change_invalidates_the_qualification(tmp_path: Path, monkeypatch) -> None:
    route = media_route("openai", "image")
    _record(tmp_path, route)
    monkeypatch.setitem(ROUTE_ADAPTER_VERSIONS, "media:image", "host-media-v2")
    assert not is_route_qualified(route, "m1", now=NOW, root=tmp_path)


def test_tampered_evidence_invalidates_the_qualification(tmp_path: Path) -> None:
    route = media_route("openai", "image")
    record = _record(tmp_path, route)
    (qualifications_dir(tmp_path) / record.evidence_path).write_text('{"result": "FAIL"}')
    assert not is_route_qualified(route, "m1", now=NOW, root=tmp_path)


@pytest.mark.parametrize("route", [media_route("openai", "video"), media_route("custom-3", "video")])
def test_an_async_video_route_also_needs_its_adapter_verified_offline(tmp_path: Path, route: PaidRoute) -> None:
    """The shipped video adapter profiles are UNQUALIFIED, so a canary alone does not qualify the route."""
    _record(tmp_path, route)
    assert not is_route_qualified(route, "m1", now=NOW, root=tmp_path)


def test_the_installed_lookup_opens_the_release_gate(tmp_path: Path) -> None:
    route = media_route("openai", "image")
    # 安装的 lookup 按真实时钟判时效：给足有效期，用例不随日期漂移。
    _record(tmp_path, route, expires_in=timedelta(days=36500))
    install_runtime_qualification_lookup(root=tmp_path)

    assert require_paid_route(route, model_id="m1", release_mode=ReleaseMode.PRODUCTION_CANDIDATE) is None
    with pytest.raises(PaidRouteUnqualifiedError):
        require_paid_route(route, model_id="m2", release_mode=ReleaseMode.PRODUCTION_CANDIDATE)
