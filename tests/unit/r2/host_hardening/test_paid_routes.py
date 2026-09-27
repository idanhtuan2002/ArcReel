from __future__ import annotations

import pytest

from r2.host_hardening.paid_routes import (
    RELEASE_MODE_ENV,
    PaidRoute,
    PaidRouteUnqualifiedError,
    ReleaseModeConfigError,
    current_release_mode,
    media_route,
    paid_route_inventory,
    require_paid_route,
    route_binding,
    set_qualification_lookup,
)
from r2.host_hardening.provider_capabilities import ReleaseMode


@pytest.fixture(autouse=True)
def no_installed_lookup():
    set_qualification_lookup(None)
    yield
    set_qualification_lookup(None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ReleaseMode.DEV),
        ("", ReleaseMode.DEV),
        ("dev", ReleaseMode.DEV),
        ("PRODUCTION_CANDIDATE", ReleaseMode.PRODUCTION_CANDIDATE),
        (" production_candidate ", ReleaseMode.PRODUCTION_CANDIDATE),
    ],
)
def test_release_mode_comes_from_the_environment(monkeypatch, raw, expected) -> None:
    if raw is None:
        monkeypatch.delenv(RELEASE_MODE_ENV, raising=False)
    else:
        monkeypatch.setenv(RELEASE_MODE_ENV, raw)
    assert current_release_mode() is expected


def test_an_unknown_release_mode_is_a_configuration_error(monkeypatch) -> None:
    monkeypatch.setenv(RELEASE_MODE_ENV, "production")
    with pytest.raises(ReleaseModeConfigError, match=RELEASE_MODE_ENV):
        current_release_mode()


def test_dev_keeps_every_paid_route_usable() -> None:
    route = PaidRoute("agent", provider_id="anthropic-official")
    assert require_paid_route(route, model_id="m", release_mode=ReleaseMode.DEV) is None


def test_a_release_deployment_refuses_an_unqualified_route() -> None:
    route = media_route("openai", "image")
    with pytest.raises(PaidRouteUnqualifiedError) as raised:
        require_paid_route(route, model_id="gpt-image-2", release_mode=ReleaseMode.PRODUCTION_CANDIDATE)
    assert raised.value.code == "paid_route_unqualified"
    assert raised.value.params == {"route": "media:openai:image", "model": "gpt-image-2"}


def test_a_release_deployment_allows_a_route_the_lookup_reports_qualified() -> None:
    qualified = {(media_route("openai", "image"), "gpt-image-2")}
    set_qualification_lookup(lambda route, model, _binding: (route, model) in qualified)

    require_paid_route(
        media_route("openai", "image"), model_id="gpt-image-2", release_mode=ReleaseMode.PRODUCTION_CANDIDATE
    )
    with pytest.raises(PaidRouteUnqualifiedError):
        require_paid_route(
            media_route("openai", "image"), model_id="other", release_mode=ReleaseMode.PRODUCTION_CANDIDATE
        )


def test_a_custom_route_names_its_provider() -> None:
    assert media_route("custom-7", "video") == PaidRoute("custom_media", provider_id="custom-7", media_type="video")
    assert media_route("custom-7", "video") != media_route("custom-42", "video")


def test_the_binding_digests_the_configuration_without_storing_it() -> None:
    first = route_binding(provider_id="openai", api_key="sk-secret", base_url="https://a.example")
    assert first.startswith("sha256:")
    assert "sk-secret" not in first
    assert first == route_binding(base_url="https://a.example", api_key="sk-secret", provider_id="openai")
    assert first != route_binding(provider_id="openai", api_key="sk-other", base_url="https://a.example")


def test_the_inventory_covers_every_backend_spec_and_the_fixed_classes() -> None:
    from lib.backend_assembly.specs import PROVIDER_SPEC_REGISTRY

    inventory = paid_route_inventory()
    assert {media_route(provider, media) for provider, media in PROVIDER_SPEC_REGISTRY} <= inventory
    assert {PaidRoute("agent"), PaidRoute("trial_run")} <= inventory
    assert {route.media_type for route in inventory if route.kind == "custom_media"} == {
        "image",
        "video",
        "text",
        "audio",
    }
