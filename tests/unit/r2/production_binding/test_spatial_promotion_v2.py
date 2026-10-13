"""V2 spatial promotion wire: frozen digests and the base-row/sidecar coupling rules."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from r2.contracts.spatial_promotion import SpatialPromotionPreviewV2, SpatialPromotionReceiptV2
from r2.production_binding.spatial_promotion import spatial_preview_v2_digest, spatial_receipt_v2_digest
from tests.unit.r2.production_binding.spatial_promotion_fixture import preview_body, receipt_body

VECTORS = json.loads(
    (Path(__file__).resolve().parents[3] / "fixtures" / "r2" / "m8c_spatial_promotion_v2_vectors.json").read_text(
        encoding="utf-8"
    )
)


def test_the_fixture_reproduces_the_frozen_v2_digests() -> None:
    assert preview_body() == VECTORS["preview_v2"]["body"]
    assert spatial_preview_v2_digest(preview_body()) == VECTORS["preview_v2"]["digest"]
    assert receipt_body() == VECTORS["receipt_v2"]["body"]
    assert spatial_receipt_v2_digest(receipt_body()) == VECTORS["receipt_v2"]["digest"]


def test_a_sidecar_change_changes_the_preview_digest() -> None:
    changed = deepcopy(preview_body())
    changed["binding"]["binding_envelope_digest"] = "sha256:" + "0" * 64

    assert spatial_preview_v2_digest(changed) != VECTORS["preview_v2"]["digest"]


def _with(body: dict[str, Any], path: tuple[str, ...], value: object) -> dict[str, Any]:
    changed = deepcopy(body)
    node = changed
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return changed


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("base_preview", "target", "kind"), "ARTIFACT_SLOT"),
        (("base_preview", "target", "target_ref"), "m8b:" + "c" * 64),
        (("base_preview", "target", "expected_target_version"), 2),
        (("base_preview", "candidate_revision"), 2),
        (("binding", "selected_assertion_ids"), ["spatial:other"]),
        (("binding", "pair_version"), 2),
        (("binding", "binding_id"), "m8b:" + "c" * 64),
    ],
)
def test_a_preview_whose_base_row_and_sidecar_differ_is_refused(path: tuple[str, ...], value: object) -> None:
    with pytest.raises(ValidationError):
        SpatialPromotionPreviewV2.model_validate(_with(preview_body(), path, value))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("base_receipt", "result_artifact_ref"), "m8b:" + "b" * 64 + "@3"),
        (("base_receipt", "result_digest"), "sha256:" + "0" * 64),
        (("base_receipt", "result_master_id"), "master-1"),
        (("result", "constraint_set_id"), "m8s:" + "0" * 64),
        (("result", "binding_version"), 1),
    ],
)
def test_a_receipt_whose_base_row_and_result_differ_is_refused(path: tuple[str, ...], value: object) -> None:
    with pytest.raises(ValidationError):
        SpatialPromotionReceiptV2.model_validate(_with(receipt_body(), path, value))
