"""V2 digests of the typed spatial promotion wire."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from r2.contracts.common import ensure_json_value
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.spatial_promotion import SpatialPromotionPreviewV2, SpatialPromotionReceiptV2

PREVIEW_V2_DOMAIN = "r2.m8.spatial.preview.v2"
RECEIPT_V2_DOMAIN = "r2.m8.spatial.receipt.v2"


def _envelope(domain: str, body: Mapping[str, Any]) -> str:
    value = ensure_json_value({"domain": domain, "canonical_version": "1", "body": dict(body)})
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def spatial_preview_v2_digest(body: Mapping[str, Any]) -> str:
    preview = SpatialPromotionPreviewV2.model_validate(body)
    return _envelope(PREVIEW_V2_DOMAIN, preview.model_dump(mode="json"))


def spatial_receipt_v2_digest(body: Mapping[str, Any]) -> str:
    receipt = SpatialPromotionReceiptV2.model_validate(body)
    return _envelope(RECEIPT_V2_DOMAIN, receipt.model_dump(mode="json"))


__all__ = ["PREVIEW_V2_DOMAIN", "RECEIPT_V2_DOMAIN", "spatial_preview_v2_digest", "spatial_receipt_v2_digest"]
