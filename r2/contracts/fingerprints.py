from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from .common import JSONValue, ensure_json_value
from .preparation import ProductionBinding
from .production import AnyShotSpec


def canonical_json_bytes(value: JSONValue) -> bytes:
    normalized = ensure_json_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: JSONValue) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def compute_content_fingerprint(
    *,
    shot_spec: AnyShotSpec,
    bindings: Sequence[ProductionBinding],
    visual_identity_refs: Sequence[str],
    approved_source_asset_refs: Sequence[str],
) -> str:
    binding_payload: list[JSONValue] = [
        ensure_json_value(binding.model_dump(mode="json"))
        for binding in sorted(bindings, key=lambda item: (item.id, item.version))
    ]
    payload = ensure_json_value(
        {
            "shot_spec": shot_spec.model_dump(mode="json"),
            "bindings": binding_payload,
            "visual_identity_refs": sorted(set(visual_identity_refs)),
            "approved_source_asset_refs": sorted(set(approved_source_asset_refs)),
        }
    )
    return _sha256(payload)


CONTENT_FINGERPRINT_V2_DOMAIN = "r2.content_fingerprint.v2"


def compute_content_fingerprint_v2(
    *,
    shot_spec: AnyShotSpec,
    bindings: Sequence[ProductionBinding],
    visual_identity_refs: Sequence[str],
    approved_source_asset_refs: Sequence[str],
    binding_snapshot_digest: str,
    spatial_set_digests: Sequence[str],
) -> str:
    """The v1 inputs plus the exact binding snapshot and the spatial sets it carries.

    A spatial-only change, with every v1 input held fixed, changes this fingerprint.
    """
    payload = ensure_json_value(
        {
            "domain": CONTENT_FINGERPRINT_V2_DOMAIN,
            "canonical_version": "1",
            "body": {
                "content_v1": compute_content_fingerprint(
                    shot_spec=shot_spec,
                    bindings=bindings,
                    visual_identity_refs=visual_identity_refs,
                    approved_source_asset_refs=approved_source_asset_refs,
                ),
                "binding_snapshot_digest": binding_snapshot_digest,
                "spatial_set_digests": list(spatial_set_digests),
            },
        }
    )
    return _sha256(payload)


def compute_execution_fingerprint(
    *,
    provider: str,
    model: str,
    endpoint: str,
    seed: int | None,
    resolution: str | None,
    generation_settings: Mapping[str, JSONValue],
    prompt_compiler_version: str,
    provider_adapter_version: str,
) -> str:
    settings = ensure_json_value(dict(generation_settings))
    if not isinstance(settings, dict):
        raise ValueError("generation_settings must be a JSON-compatible mapping")
    payload: dict[str, JSONValue] = {
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "seed": seed,
        "resolution": resolution,
        "generation_settings": settings,
        "prompt_compiler_version": prompt_compiler_version,
        "provider_adapter_version": provider_adapter_version,
    }
    return _sha256(payload)
