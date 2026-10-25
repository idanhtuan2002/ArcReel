"""Exact local declarations compile without adopting legacy fallback policy."""

from __future__ import annotations

from typing import Literal, cast

import pytest

from lib.config.registry import PROVIDER_REGISTRY
from lib.pricing.price_compiler import compile_pricing
from lib.pricing.request_metering import Priced, PriceTable, Unpriced, UnpricedReason, Usage, price_requests
from lib.pricing.strategies import PricingParams, calculate_pricing
from lib.pricing.types import (
    PerCharacter,
    PerImageByResolution,
    PerImageFlat,
    PerImageOpenAIToken,
    PerSecondMatrix,
    PerSecondTiered,
    PerToken,
    PerTokenVideo,
    PerVideoBucket,
    Pricing,
    ViduDelegate,
)


def _usage_for(pricing: Pricing, model: str) -> tuple[PricingParams, Usage]:
    if isinstance(pricing, PerToken):
        return PricingParams("text", model=model, input_tokens=1000, output_tokens=500), Usage(
            quantities={"uncached_input_tokens": 1000, "output_tokens": 500}
        )
    if isinstance(pricing, PerImageFlat):
        return PricingParams("image", model=model, n=2), Usage(quantities={"output_images": 2})
    if isinstance(pricing, PerImageByResolution):
        resolution = next(iter(pricing.rates[model]))
        return PricingParams("image", model=model, resolution=resolution, n=2), Usage(
            quantities={"output_images": 2}, dimensions={"resolution": resolution}
        )
    if isinstance(pricing, PerImageOpenAIToken):
        return PricingParams(
            "image",
            model=model,
            image_input_tokens=100,
            image_output_tokens=200,
            text_input_tokens=300,
            text_output_tokens=400,
        ), Usage(
            quantities={
                "uncached_image_input_tokens": 100,
                "image_cache_read_tokens": 0,
                "image_output_tokens": 200,
                "uncached_input_tokens": 300,
                "cache_read_tokens": 0,
                "output_tokens": 400,
            }
        )
    if isinstance(pricing, PerSecondMatrix):
        resolution, audio = next(iter(pricing.rates[model]))
        dims: dict[str, object] = {}
        if pricing.dimensions != "flat":
            dims["resolution"] = resolution
        if pricing.dimensions == "resolution_audio":
            dims["audio"] = audio
        return PricingParams(
            "video",
            model=model,
            resolution=resolution,
            duration_seconds=8,
            generate_audio=audio if audio is not None else True,
        ), Usage(quantities={"output_seconds": 8}, dimensions=dims)
    if isinstance(pricing, PerSecondTiered):
        tier, audio = next(iter(pricing.rates[model]))
        return PricingParams(
            "video",
            model=model,
            resolution="4k" if tier == "4k" else "720p",
            service_tier=tier,
            generate_audio=audio,
            duration_seconds=5,
        ), Usage(quantities={"output_seconds": 5}, dimensions={"quality": tier, "audio": audio})
    if isinstance(pricing, PerVideoBucket):
        resolution, duration = next(iter(pricing.rates[model]))
        return PricingParams("video", model=model, resolution=resolution, duration_seconds=duration), Usage(
            quantities={"requests": 1}, dimensions={"resolution": resolution, "duration": duration}
        )
    if isinstance(pricing, PerTokenVideo):
        tier, audio = next(iter(pricing.rates[model]))
        return PricingParams("video", model=model, service_tier=tier, generate_audio=audio, usage_tokens=100000), Usage(
            quantities={"video_tokens": 100000},
            dimensions={"service_tier": "standard" if tier == "default" else tier, "audio": audio},
        )
    assert isinstance(pricing, PerCharacter)
    return PricingParams("audio", model=model, usage_tokens=100), Usage(quantities={"characters": 100})


def _assert_parity(pricing: Pricing, model: str) -> None:
    table = compile_pricing(pricing, model_id=model)
    assert isinstance(table, PriceTable)
    params, usage = _usage_for(pricing, model)
    amount, currency = calculate_pricing(pricing, params)
    result = price_requests(table, [usage])
    assert isinstance(result, Priced)
    assert result.amount == pytest.approx(amount, rel=1e-12, abs=1e-12)
    assert result.currency == currency
    assert all(not meter.defaults for meter in table.meters)


_REGISTRY = [(p, m, info.pricing) for p, meta in PROVIDER_REGISTRY.items() for m, info in meta.models.items()]


@pytest.mark.parametrize(("provider", "model", "pricing"), _REGISTRY, ids=[p + "/" + m for p, m, _ in _REGISTRY])
def test_every_registry_identity_preserves_declared_rate(provider: str, model: str, pricing: Pricing | None) -> None:
    assert provider in PROVIDER_REGISTRY
    if pricing is None:
        assert compile_pricing(pricing, model_id=model) == Unpriced(UnpricedReason.NO_PRICE_TABLE)
    elif isinstance(pricing, ViduDelegate):
        assert compile_pricing(pricing, model_id=model) == Unpriced(UnpricedReason.UNRECOGNIZED_TERMS)
    else:
        _assert_parity(pricing, model)


_SYNTHETIC: list[Pricing] = [
    PerToken({"f": {"input": 0.3, "output": 2.5}}, "f", "USD"),
    PerImageFlat({"f": 0.04}, "f", "USD"),
    PerImageByResolution({"f": {"2K": 0.08, "4K": 0}}, "f", "USD"),
    PerImageOpenAIToken(
        {"f": {"image_in": 2, "image_out": 8, "text_in": 1, "text_out": 4}},
        {"f": {("medium", "1024x1024"): 0.034}},
        "f",
        "USD",
    ),
    PerSecondMatrix({"f": {("720p", True): 0.5}}, "f", "resolution_audio", "USD"),
    PerSecondMatrix({"f": {("1080p", None): 0.2}}, "f", "resolution_only", "USD"),
    PerSecondMatrix({"f": {("", None): 0.7}}, "f", "flat", "USD"),
    PerSecondTiered({"f": {("4k", False): 0.8}}, "f", "CNY"),
    PerVideoBucket({"f": {("720p", 6): 2.1, ("720p", 10): 4}}, "f", "CNY"),
    PerTokenVideo({"f": {("default", True): 16, ("flex", False): 8}}, "f", "CNY"),
    PerCharacter({"f": 0.8}, "f", "CNY"),
]


@pytest.mark.parametrize("pricing", _SYNTHETIC, ids=lambda p: p.kind)
def test_synthetic_same_fixture_arithmetic(pricing: Pricing) -> None:
    _assert_parity(pricing, "f")


@pytest.mark.parametrize("pricing", _SYNTHETIC, ids=lambda p: p.kind)
def test_explicit_unknown_model_never_uses_default(pricing: Pricing) -> None:
    assert compile_pricing(pricing, model_id="unknown") == Unpriced(UnpricedReason.NO_ENTRY)


def test_registry_inventory_is_explicit() -> None:
    assert len(_REGISTRY) == 108
    assert sum(p is None for _, _, p in _REGISTRY) == 14
    assert sum(isinstance(p, ViduDelegate) for _, _, p in _REGISTRY) == 6


def test_slash_identity_is_exact_and_source_mutation_does_not_change_snapshot() -> None:
    pricing = PerImageByResolution({"route/a": {"1K": 0.1}, "route/b": {"1K": 0.9}}, "route/b", "USD")
    table = compile_pricing(pricing, model_id="route/a")
    assert isinstance(table, PriceTable)
    usage = Usage(quantities={"output_images": 1}, dimensions={"resolution": "1K"})
    assert price_requests(table, [usage]) == Priced(0.1, "USD")
    pricing.rates["route/a"]["1K"] = 0.5
    assert price_requests(table, [usage]) == Priced(0.1, "USD")
    updated = compile_pricing(pricing, model_id="route/a")
    assert isinstance(updated, PriceTable)
    assert price_requests(updated, [usage]) == Priced(0.5, "USD")
    with pytest.raises(TypeError, match="assignment"):
        cast(dict[str, object], table.meters[0].rows[0].when)["resolution"] = "2K"


def _image() -> PerImageOpenAIToken:
    return PerImageOpenAIToken(
        {
            "f": {
                "image_in": 2,
                "image_out": 8,
                "text_in": 1,
                "text_out": 4,
                "image_cached_in": 0.2,
                "text_cached_in": 0.1,
            }
        },
        {"f": {("medium", "1024x1024"): 0.034, ("high", "1536x1024"): 0.2}},
        "f",
        "USD",
    )


def test_cached_image_and_text_rates_are_not_discarded_or_inferred() -> None:
    table = compile_pricing(_image(), model_id="f")
    assert isinstance(table, PriceTable)
    assert {m.meter: m.rows[0].price for m in table.meters} == {
        "uncached_image_input_tokens": 2,
        "image_output_tokens": 8,
        "uncached_input_tokens": 1,
        "output_tokens": 4,
        "image_cache_read_tokens": 0.2,
        "cache_read_tokens": 0.1,
    }
    usage = Usage(
        quantities={
            "uncached_image_input_tokens": 90,
            "image_cache_read_tokens": 10,
            "image_output_tokens": 200,
            "uncached_input_tokens": 280,
            "cache_read_tokens": 20,
            "output_tokens": 400,
        }
    )
    result = price_requests(table, [usage])
    assert isinstance(result, Priced)
    assert result.amount == pytest.approx(0.003664)
    assert price_requests(table, [Usage(quantities={"output_images": 1})]) == Unpriced(UnpricedReason.MISSING_RATE)


@pytest.mark.parametrize("problem", ["missing", "unknown"])
def test_image_price_axes_must_be_explicit(problem: str) -> None:
    source = _image()
    if problem == "missing":
        source.token_rates["f"].pop("text_out")
    else:
        source.token_rates["f"]["future_rate"] = 1
    reason = UnpricedReason.MISSING_RATE if problem == "missing" else UnpricedReason.UNRECOGNIZED_TERMS
    assert compile_pricing(source, model_id="f") == Unpriced(reason)


def test_reference_image_table_requires_explicit_branch_and_exact_size() -> None:
    source = _image()
    table = compile_pricing(source, model_id="f", image_mode="reference")
    assert isinstance(table, PriceTable)
    assert price_requests(
        table, [Usage(quantities={"output_images": 2}, dimensions={"quality": "high", "resolution": "1536x1024"})]
    ) == Priced(0.4, "USD")
    assert price_requests(table, [Usage(quantities={"output_images": 1}, dimensions={"quality": "high"})]) == Unpriced(
        UnpricedReason.MISSING_RATE
    )
    assert calculate_pricing(source, PricingParams("image", model="f", quality="high", size="1536x1024", n=2)) == (
        0.4,
        "USD",
    )


@pytest.mark.parametrize("mode", ["reference", "invalid"])
def test_wrong_mode_cannot_silently_change_a_different_price_kind(mode: str) -> None:
    with pytest.raises(ValueError, match="mode"):
        compile_pricing(
            PerImageFlat({"f": 0.1}, "f", "USD"), model_id="f", image_mode=cast(Literal["tokens", "reference"], mode)
        )


@pytest.mark.parametrize(
    "pricing",
    [
        PerImageByResolution({"f": {"1K": 0.1, "1k": 0.2}}, "f", "USD"),
        PerSecondTiered({"f": {("std", True): 0.1, ("STD", True): 0.2}}, "f"),
        PerTokenVideo({"f": {("default", True): 16, ("standard", True): 8}}, "f"),
    ],
)
def test_equivalent_dimension_rows_do_not_choose_by_insertion_order(pricing: Pricing) -> None:
    assert compile_pricing(pricing, model_id="f") == Unpriced(UnpricedReason.UNRECOGNIZED_TERMS)


@pytest.mark.parametrize("rate", [True, -1, float("nan"), float("inf"), "1"])
def test_selected_invalid_rates_raise_before_returning_a_table(rate: object) -> None:
    with pytest.raises(ValueError, match="metering numbers"):
        compile_pricing(PerImageFlat({"f": cast(float, rate)}, "f", "USD"), model_id="f")


def test_zero_unknown_currency_and_empty_rates_are_distinct() -> None:
    table = compile_pricing(PerImageFlat({"f": 0}, "f", "CNY"), model_id="f")
    assert isinstance(table, PriceTable)
    assert price_requests(table, [Usage(quantities={"output_images": 3})]) == Priced(0, "CNY")
    assert compile_pricing(PerImageFlat({"f": 1}, "f", "LOCAL"), model_id="f") == Unpriced(
        UnpricedReason.UNRECOGNIZED_TERMS
    )
    assert compile_pricing(PerImageByResolution({"f": {}}, "f", "USD"), model_id="f") == Unpriced(
        UnpricedReason.MISSING_RATE
    )


def test_legacy_nearest_bucket_and_resolution_fallback_remain_separate() -> None:
    bucket = PerVideoBucket({"f": {("720p", 6): 2, ("720p", 10): 4}}, "f", "CNY")
    table = compile_pricing(bucket, model_id="f")
    assert isinstance(table, PriceTable)
    usage = Usage(quantities={"requests": 1}, dimensions={"resolution": "720p", "duration": 8})
    assert price_requests(table, [usage]) == Unpriced(UnpricedReason.MISSING_RATE)
    assert calculate_pricing(bucket, PricingParams("video", model="f", resolution="720p", duration_seconds=8)) == (
        2,
        "CNY",
    )
    resolution = PerImageByResolution({"f": {"1K": 0.1}}, "f", "USD")
    rt = compile_pricing(resolution, model_id="f")
    assert isinstance(rt, PriceTable)
    assert price_requests(rt, [Usage(quantities={"output_images": 1}, dimensions={"resolution": "8K"})]) == Unpriced(
        UnpricedReason.MISSING_RATE
    )
    assert calculate_pricing(resolution, PricingParams("image", model="f", resolution="8K")) == (0.1, "USD")


@pytest.mark.parametrize("model", ["", None, True])
def test_invalid_identity_is_not_normalized_to_a_default(model: object) -> None:
    with pytest.raises(ValueError, match="identity"):
        compile_pricing(PerImageFlat({"f": 0.1}, "f", "USD"), model_id=cast(str, model))


def test_invalid_mapping_and_dimension_key_shapes_fail_explicitly() -> None:
    bad = PerImageByResolution({"f": cast(dict[str, float], None)}, "f", "USD")
    with pytest.raises(ValueError, match="mappings"):
        compile_pricing(bad, model_id="f")
    bucket = PerVideoBucket({"f": cast(dict[tuple[str, int], float], {"720p": 2})}, "f", "USD")
    with pytest.raises(ValueError, match="pairs"):
        compile_pricing(bucket, model_id="f")


@pytest.mark.parametrize(
    ("pricing", "params", "usage", "expected"),
    [
        (
            PerSecondMatrix({"f": {("720p", True): 0.5}}, "f", "resolution_audio", "USD"),
            PricingParams("video", model="f", resolution="8k", duration_seconds=8),
            Usage(quantities={"output_seconds": 8}, dimensions={"resolution": "8k", "audio": True}),
            4,
        ),
        (
            PerSecondTiered({"f": {("std", False): 0.1}}, "f", "CNY"),
            PricingParams("video", model="f", service_tier="future", generate_audio=False, duration_seconds=5),
            Usage(quantities={"output_seconds": 5}, dimensions={"quality": "future", "audio": False}),
            0.5,
        ),
        (
            PerTokenVideo({"f": {("default", True): 16}}, "f", "CNY"),
            PricingParams("video", model="f", service_tier="fast", usage_tokens=100000),
            Usage(quantities={"video_tokens": 100000}, dimensions={"service_tier": "fast", "audio": True}),
            1.6,
        ),
    ],
)
def test_legacy_matrix_and_tier_fallback_are_not_compiled(
    pricing: Pricing, params: PricingParams, usage: Usage, expected: float
) -> None:
    table = compile_pricing(pricing, model_id="f")
    assert isinstance(table, PriceTable)
    assert price_requests(table, [usage]) == Unpriced(UnpricedReason.MISSING_RATE)
    amount, _ = calculate_pricing(pricing, params)
    assert amount == pytest.approx(expected)
