"""Model facts preserve identity and declarations without constructing providers."""

from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from lib.catalog import builtin_model
from lib.config.registry import PROVIDER_REGISTRY, ModelInfo, ProviderMeta
from lib.pricing.types import PerToken


@pytest.mark.parametrize(("provider", "model"), [("missing", "x"), ("gemini-aistudio", "missing"), ("custom-1", "x")])
def test_unknown_identity_does_not_resolve_a_default(provider, model):
    assert builtin_model(provider, model) is None


def test_every_builtin_retains_its_identity_and_model_facts():
    identities = set()
    kinds = set()
    for provider, meta in PROVIDER_REGISTRY.items():
        for model, info in meta.models.items():
            view = builtin_model(provider, model)
            assert view is not None
            assert (view.provider_id, view.model_id) == (provider, model)
            assert view.api_model_name == info.api_model_name
            assert (view.media_type, view.display_name) == (info.media_type, info.display_name)
            assert (view.enabled, view.hidden, view.default) == (True, info.hidden, info.default)
            assert view.capabilities == tuple(info.capabilities)
            assert view.endpoint is None
            assert view.source == "builtin_registry"
            assert view.source_version
            assert view.supported_durations == tuple(info.supported_durations)
            assert view.resolutions == tuple(info.resolutions)
            assert dict(view.duration_resolution_constraints) == {
                k: tuple(v) for k, v in info.duration_resolution_constraints.items()
            }
            assert view.reference_image_durations == tuple(info.reference_image_durations)
            if info.pricing is None:
                assert view.pricing is None
            else:
                assert view.pricing is not None
                assert (view.pricing.kind, view.pricing.currency) == (info.pricing.kind, info.pricing.currency)
                kinds.add(view.pricing.kind)
            identities.add((view.provider_id, view.model_id))
    assert len(identities) == sum(len(p.models) for p in PROVIDER_REGISTRY.values())
    assert kinds == {
        "per_token",
        "per_image_flat",
        "per_image_by_resolution",
        "per_image_openai_token",
        "per_second_matrix",
        "per_second_tiered",
        "per_video_bucket",
        "per_token_video",
        "per_character",
        "vidu_delegate",
    }


def test_api_model_name_and_slash_identity_are_not_rewritten():
    view = builtin_model("kling", "kling-v3-omni-image")
    assert view is not None
    assert (view.model_id, view.api_model_name, view.media_type) == ("kling-v3-omni-image", "kling-v3-omni", "image")
    slash = builtin_model("minimax", "proxy/minimax-h3")
    assert slash is None


def test_text_only_declaration_does_not_acquire_vision_or_structured_support():
    view = builtin_model("gemini-aistudio", "gemma-4-26b-a4b-it")
    assert view is not None
    assert view.capabilities == ("text_generation",)


def test_hidden_model_and_nested_prices_are_immutable_snapshots(monkeypatch):
    info = ModelInfo(
        display_name="Named",
        media_type="text",
        capabilities=["text_generation"],
        hidden=True,
        pricing=PerToken(
            rates={"publisher/name": {"input": 0.45, "output": 1.25}}, default_model="publisher/name", currency="CNY"
        ),
        api_model_name="publisher/name",
        duration_resolution_constraints={"1K": [5, 8]},
    )
    monkeypatch.setitem(
        PROVIDER_REGISTRY,
        "catalog-fixture",
        ProviderMeta(display_name="Fixture", description="", required_keys=[], models={"alias/with/slash": info}),
    )
    view = builtin_model("catalog-fixture", "alias/with/slash")
    assert view is not None
    assert view.pricing is not None
    assert view.hidden
    assert view.enabled
    assert view.model_id == "alias/with/slash"
    with pytest.raises(FrozenInstanceError):
        view.display_name = "changed"
    with pytest.raises(TypeError):
        view.pricing.details["rates"]["publisher/name"]["input"] = 9
    with pytest.raises(TypeError):
        cast(dict[str, tuple[int, ...]], view.duration_resolution_constraints)["1K"] = (20,)
    info.capabilities.append("vision")
    assert isinstance(info.pricing, PerToken)
    info.pricing.rates["publisher/name"]["input"] = 5
    info.duration_resolution_constraints["1K"].append(12)
    assert view.capabilities == ("text_generation",)
    assert view.pricing.details["rates"]["publisher/name"]["input"] == 0.45
    assert view.duration_resolution_constraints["1K"] == (5, 8)
    fresh = builtin_model("catalog-fixture", "alias/with/slash")
    assert fresh is not None
    assert fresh.pricing is not None
    assert fresh.pricing.details["rates"]["publisher/name"]["input"] == 5


def test_video_price_tuple_keys_and_zero_rates_survive_projection():
    view = builtin_model("gemini-aistudio", "veo-3.1-lite-generate-preview")
    assert view is not None
    assert view.pricing is not None
    original = PROVIDER_REGISTRY["gemini-aistudio"].models[view.model_id].pricing
    assert original is not None
    assert view.pricing.details["rates"][view.model_id] == original.rates[view.model_id]
    free = builtin_model("gemini-aistudio", "gemma-4-31b-it")
    assert free is not None
    assert free.pricing is not None
    assert free.pricing.details["rates"][free.model_id] == {"input": 0.0, "output": 0.0}
