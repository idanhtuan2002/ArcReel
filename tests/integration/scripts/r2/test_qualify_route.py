"""The route-qualification canary through real backend assembly, the release gate, the ledger and budget."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from lib.backend_assembly.assembler import paid_route_binding
from lib.budget_guard import budget_scope_ref
from lib.config.resolver import ConfigResolver
from lib.config.service import ConfigService
from lib.db.models.api_call import ApiCall
from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository
from lib.image_backends import registry as image_registry
from lib.image_backends.base import ImageGenerationResult
from r2.host_hardening.paid_routes import RELEASE_MODE_ENV, PaidRouteUnqualifiedError, media_route, require_paid_route
from r2.host_hardening.route_qualifications import is_route_qualified, load_qualifications
from scripts.r2 import qualify_route


class _FakeImageBackend:
    def __init__(self, *, fail: bool = False, **_kwargs) -> None:
        self._fail = fail

    async def generate(self, request):
        if self._fail:
            return ImageGenerationResult(image_path=request.output_path, provider="ark", model="doubao-x")
        request.output_path.write_bytes(b"\x89PNG canary")
        return ImageGenerationResult(image_path=request.output_path, provider="ark", model="doubao-x")


def _args(**overrides) -> argparse.Namespace:
    values = {
        "agent": False,
        "provider": "ark",
        "media": "image",
        "model": "doubao-x",
        "duration": 5,
        "voice": None,
        "ttl_days": 30,
        "recorded_by": "operator",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture
async def release_deployment(db_factory, tmp_path: Path, monkeypatch):
    from lib import app_data_dir as data_dir

    monkeypatch.setenv(RELEASE_MODE_ENV, "PRODUCTION_CANDIDATE")
    monkeypatch.setenv("ARCREEL_DATA_DIR", str(tmp_path / "data"))
    data_dir.reset_for_tests()
    async with db_factory() as session:
        await ConfigService(session).set_provider_config("ark", "api_key", "ark-secret")
        await session.commit()
    async with db_factory() as session:
        await BudgetReservationRepository(session).create_scope(
            budget_scope_ref=budget_scope_ref("CNY"),
            currency="CNY",
            authorized_limit=Decimal("10"),
            now=datetime.now(UTC),
        )
    yield tmp_path / "data"
    data_dir.reset_for_tests()


async def test_the_canary_is_the_one_call_an_unqualified_route_may_make(
    db_factory, release_deployment: Path, monkeypatch
) -> None:
    monkeypatch.setitem(image_registry._BACKEND_FACTORIES, "ark", lambda **kw: _FakeImageBackend(**kw))
    route = media_route("ark", "image")
    with pytest.raises(PaidRouteUnqualifiedError):
        require_paid_route(route, model_id="doubao-x")

    result = await qualify_route.run_media_canary(_args(), session_factory=db_factory)

    assert result["qualified"] == "media:ark:image"
    binding = await paid_route_binding(provider_id="ark", media_type="image", resolver=ConfigResolver(db_factory))
    assert is_route_qualified(route, "doubao-x", binding, now=datetime.now(UTC), root=release_deployment)
    async with db_factory() as session:
        call = (await session.execute(select(ApiCall))).scalar_one()
    assert (call.status, call.project_name) == ("success", qualify_route.CANARY_PROJECT)
    [record] = load_qualifications(release_deployment)
    assert record.cost_record_ref == f"api_call:{call.id}"


async def test_a_canary_without_usable_output_records_nothing(
    db_factory, release_deployment: Path, monkeypatch
) -> None:
    monkeypatch.setitem(image_registry._BACKEND_FACTORIES, "ark", lambda **kw: _FakeImageBackend(fail=True, **kw))

    with pytest.raises(qualify_route.CanaryFailedError):
        await qualify_route.run_media_canary(_args(), session_factory=db_factory)

    assert load_qualifications(release_deployment) == []


async def test_a_new_api_key_needs_a_new_canary(db_factory, release_deployment: Path, monkeypatch) -> None:
    """资质绑定到供应商当下的配置：换了凭证即不再有效，旧 canary 不能带到新账户上。"""
    monkeypatch.setitem(image_registry._BACKEND_FACTORIES, "ark", lambda **kw: _FakeImageBackend(**kw))
    await qualify_route.run_media_canary(_args(), session_factory=db_factory)
    resolver = ConfigResolver(db_factory)

    async with db_factory() as session:
        await ConfigService(session).set_provider_config("ark", "api_key", "another-account-key")
        await session.commit()
    binding = await paid_route_binding(provider_id="ark", media_type="image", resolver=resolver)

    assert not is_route_qualified(
        media_route("ark", "image"), "doubao-x", binding, now=datetime.now(UTC), root=release_deployment
    )
