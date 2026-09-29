"""M8 advanced-creative contracts (spec 2026-09-13 §4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from r2.contracts.advanced_creative import (
    CanonicalJsonObject,
    CanvasCandidate,
    CanvasNode,
    EvidenceClass,
    ExplorationKind,
    ExplorationRevision,
    FormatCandidate,
    LineageBinding,
    PromotionPreview,
    PromotionReceipt,
    PromotionTarget,
    PromotionTargetKind,
    SpatialAssertion,
    SpatialCandidate,
    SpatialPayload,
)

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


def _lineage(**overrides: object) -> LineageBinding:
    fields: dict[str, object] = {
        "project_name": "demo",
        "content_basis_digest": DIGEST,
        "approved_master_id": None,
        "approved_master_digest": None,
        "creative_profile_id": "profile",
        "creative_profile_version": "1",
        "policy_digest": DIGEST,
    }
    return LineageBinding(**(fields | overrides))


def _canvas() -> CanvasCandidate:
    return CanvasCandidate(
        kind=ExplorationKind.CANVAS,
        graph_schema_version="1",
        nodes=(CanvasNode(node_id="n1", node_type="shot", body={"z": 1, "a": [2, {"k": 1.5}]}),),
        edges=(),
        groups=(),
        storyboard_order=("n1",),
        viewport_bookmarks=(),
    )


def _spatial() -> SpatialCandidate:
    assertion = SpatialAssertion(
        assertion_id="a1",
        evidence_class=EvidenceClass.GAP,
        source_refs=("frame:1",),
        relation="left_of",
        subject_refs=("x", "y"),
        confidence=None,
        warnings=(),
    )
    payload = SpatialPayload(
        assertions=(assertion,),
        seam_locks=(),
        direction_locks=(),
        duplicate_warnings=(),
        execution_id=None,
        normalizer_version="1",
    )
    return SpatialCandidate(kind=ExplorationKind.SPATIAL, spatial=payload)


def _revision(**overrides: object) -> ExplorationRevision:
    fields: dict[str, object] = {
        "candidate_id": "c1",
        "revision": 1,
        "kind": ExplorationKind.CANVAS,
        "parent_revision": None,
        "payload": _canvas(),
        "payload_digest": DIGEST,
        "lineage": _lineage(),
        "created_by": "u1",
        "created_at": NOW,
    }
    return ExplorationRevision(**(fields | overrides))


def _preview(target_kind: PromotionTargetKind, *, ttl: timedelta, master: bool) -> PromotionPreview:
    return PromotionPreview(
        preview_id="p1",
        preview_command_id="cmd",
        project_name="demo",
        candidate_id="c1",
        candidate_revision=1,
        candidate_payload_digest=DIGEST,
        target=PromotionTarget(kind=target_kind, target_ref="slot", expected_target_version=0),
        expected_master_id="m1" if master else None,
        expected_master_digest=DIGEST if master else None,
        impact={},
        impact_digest=DIGEST,
        authorization_scope="scope",
        issued_at=NOW,
        expires_at=NOW + ttl,
    )


def test_contracts_are_frozen() -> None:
    revision = _revision()

    with pytest.raises(ValidationError):
        revision.revision = 2


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        LineageBinding.model_validate(_lineage().model_dump() | {"unexpected": True})


def test_timestamps_must_be_aware() -> None:
    with pytest.raises(ValidationError):
        _revision(created_at=datetime(2026, 9, 29, 12, 0))


@pytest.mark.parametrize("digest", ["sha256:" + "A" * 64, "sha256:" + "a" * 63, "a" * 64])
def test_digests_must_be_lowercase_sha256(digest: str) -> None:
    with pytest.raises(ValidationError):
        _revision(payload_digest=digest)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("Infinity")])
def test_canonical_json_numbers_must_be_finite(value: object) -> None:
    with pytest.raises(ValidationError):
        CanonicalJsonObject.model_validate({"n": value})


def test_canonical_json_is_recursively_frozen_and_key_sorted() -> None:
    source = {"b": [1, {"y": 2, "x": 1}], "a": "text"}
    value = CanonicalJsonObject.model_validate(source)
    nested = source["b"]
    assert isinstance(nested, list)
    nested[1]["x"] = 99

    assert [key for key, _ in value.root] == ["a", "b"]
    array = value.root[1][1]
    assert isinstance(array, tuple)
    inner = array[1]
    assert isinstance(inner, CanonicalJsonObject)
    assert inner.root == (("x", 1), ("y", 2))


def test_canonical_json_keeps_array_order_and_round_trips() -> None:
    value = CanonicalJsonObject.model_validate({"list": [3, 1, 2], "n": 1.25})

    dumped = value.model_dump(mode="json")

    assert dumped == {"list": [3, 1, 2], "n": 1.25}
    assert CanonicalJsonObject.model_validate(dumped) == value


def test_canonical_json_rejects_non_string_keys() -> None:
    with pytest.raises(ValidationError):
        CanonicalJsonObject.model_validate({1: "x"})


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        (ExplorationKind.CANVAS, _canvas()),
        (ExplorationKind.SPATIAL, _spatial()),
    ],
)
def test_the_payload_discriminator_selects_its_candidate(kind: ExplorationKind, payload: object) -> None:
    revision = _revision(kind=kind, payload=payload)

    restored = ExplorationRevision.model_validate_json(revision.model_dump_json())

    assert restored == revision
    assert type(restored.payload) is type(payload)


def test_a_format_payload_is_the_third_discriminator() -> None:
    payload = FormatCandidate(
        kind=ExplorationKind.FORMAT,
        plan_digest=DIGEST,
        rendered_artifact_ref="artifact",
        rendered_artifact_digest=DIGEST,
        technical_report_id="t",
        technical_report_digest=DIGEST,
        semantic_report_id="s",
        semantic_report_digest=DIGEST,
        execution_id="e",
    )

    assert _revision(kind=ExplorationKind.FORMAT, payload=payload).payload == payload


def test_the_revision_kind_must_equal_the_payload_kind() -> None:
    with pytest.raises(ValidationError):
        _revision(kind=ExplorationKind.SPATIAL)


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=3601), timedelta(seconds=-1)])
def test_a_preview_ttl_outside_the_bound_is_refused(ttl: timedelta) -> None:
    with pytest.raises(ValidationError):
        _preview(PromotionTargetKind.ARTIFACT_SLOT, ttl=ttl, master=True)


@pytest.mark.parametrize("ttl", [timedelta(seconds=1), timedelta(seconds=900), timedelta(seconds=3600)])
def test_a_preview_ttl_inside_the_bound_is_accepted(ttl: timedelta) -> None:
    assert _preview(PromotionTargetKind.ARTIFACT_SLOT, ttl=ttl, master=True).expires_at == NOW + ttl


def test_an_artifact_preview_requires_the_master_and_a_binding_preview_forbids_it() -> None:
    with pytest.raises(ValidationError):
        _preview(PromotionTargetKind.ARTIFACT_SLOT, ttl=timedelta(seconds=900), master=False)
    with pytest.raises(ValidationError):
        _preview(PromotionTargetKind.PRODUCTION_BINDING, ttl=timedelta(seconds=900), master=True)
    assert _preview(PromotionTargetKind.PRODUCTION_BINDING, ttl=timedelta(seconds=900), master=False)


@pytest.mark.parametrize(
    ("kind", "master", "valid"),
    [
        (PromotionTargetKind.ARTIFACT_SLOT, "m1", True),
        (PromotionTargetKind.ARTIFACT_SLOT, None, False),
        (PromotionTargetKind.PRODUCTION_BINDING, None, True),
        (PromotionTargetKind.PRODUCTION_BINDING, "m1", False),
    ],
)
def test_the_receipt_master_is_coupled_to_the_target_kind(
    kind: PromotionTargetKind, master: str | None, valid: bool
) -> None:
    def build() -> PromotionReceipt:
        return PromotionReceipt(
            receipt_id="r1",
            command_id="cmd",
            project_name="demo",
            preview_digest=DIGEST,
            candidate_id="c1",
            candidate_revision=1,
            target=PromotionTarget(kind=kind, target_ref="slot", expected_target_version=0),
            result_artifact_ref="artifact",
            result_master_id=master,
            result_digest=DIGEST,
            promoted_at=NOW,
        )

    if valid:
        assert build().result_master_id == master
    else:
        with pytest.raises(ValidationError):
            build()
