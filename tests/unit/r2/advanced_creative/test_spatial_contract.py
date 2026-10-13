from __future__ import annotations

import pytest
from pydantic import ValidationError

from r2.contracts.advanced_creative import (
    CanonicalJsonObject,
    EvidenceClass,
    SpatialAssertion,
    SpatialImageSpan,
    SpatialPayload,
)


def test_legacy_spatial_assertion_json_has_no_added_empty_field() -> None:
    assertion = SpatialAssertion(
        assertion_id="a1",
        evidence_class=EvidenceClass.VISIBLE,
        source_refs=("master:1",),
        relation="cabinet on front wall",
        subject_refs=("cabinet",),
        confidence=None,
        warnings=(),
    )

    assert assertion.model_dump(mode="json") == {
        "assertion_id": "a1",
        "evidence_class": "VISIBLE",
        "source_refs": ["master:1"],
        "relation": "cabinet on front wall",
        "subject_refs": ["cabinet"],
        "confidence": None,
        "warnings": [],
    }


def test_spatial_image_spans_are_typed_and_bound_to_assertion_sources() -> None:
    span = SpatialImageSpan(
        source_ref="master:1",
        source_digest="sha256:" + "a" * 64,
        view="MASTER",
        x0=0.1,
        y0=0.2,
        x1=0.4,
        y1=0.7,
    )
    assertion = SpatialAssertion(
        assertion_id="a1",
        evidence_class=EvidenceClass.VISIBLE,
        source_refs=("master:1",),
        source_spans=(span,),
        relation="cabinet on front wall",
        subject_refs=("cabinet",),
        confidence=None,
        warnings=(),
    )

    dumped = assertion.model_dump(mode="json")
    assert dumped["source_spans"] == [span.model_dump(mode="json")]
    assert SpatialAssertion.model_validate(dumped) == assertion


@pytest.mark.parametrize(
    ("x0", "x1"),
    [(0.4, 0.4), (0.7, 0.4), (-0.1, 0.4), (0.1, 1.1)],
)
def test_spatial_image_span_rejects_invalid_horizontal_extent(x0: float, x1: float) -> None:
    with pytest.raises(ValidationError):
        SpatialImageSpan(
            source_ref="master:1",
            source_digest="sha256:" + "a" * 64,
            view="MASTER",
            x0=x0,
            y0=0.2,
            x1=x1,
            y1=0.7,
        )


def test_spatial_assertion_rejects_span_for_unlisted_source() -> None:
    with pytest.raises(ValidationError):
        SpatialAssertion(
            assertion_id="a1",
            evidence_class=EvidenceClass.VISIBLE,
            source_refs=("master:1",),
            source_spans=(
                SpatialImageSpan(
                    source_ref="master:2",
                    source_digest="sha256:" + "a" * 64,
                    view="MASTER",
                    x0=0.1,
                    y0=0.2,
                    x1=0.4,
                    y1=0.7,
                ),
            ),
            relation="cabinet on front wall",
            subject_refs=("cabinet",),
            confidence=None,
            warnings=(),
        )


def test_shared_anchor_can_retain_both_view_spans() -> None:
    master = SpatialImageSpan(
        source_ref="master:1",
        source_digest="sha256:" + "a" * 64,
        view="MASTER",
        x0=0.05,
        y0=0.2,
        x1=0.2,
        y1=0.8,
    )
    reverse = SpatialImageSpan(
        source_ref="reverse:1",
        source_digest="sha256:" + "b" * 64,
        view="REVERSE",
        x0=0.8,
        y0=0.2,
        x1=0.95,
        y1=0.8,
    )

    assertion = SpatialAssertion(
        assertion_id="shared-cabinet",
        evidence_class=EvidenceClass.VISIBLE,
        source_refs=("master:1", "reverse:1"),
        source_spans=(master, reverse),
        evidence_detail=CanonicalJsonObject.model_validate({"type": "cabinet", "size_lock": "large", "count": 1}),
        relation="same shared side anchor",
        subject_refs=("cabinet",),
        confidence=None,
        warnings=(),
    )

    assert len(assertion.model_dump(mode="json")["source_spans"]) == 2
    assert assertion.model_dump(mode="json")["evidence_detail"] == {
        "count": 1,
        "size_lock": "large",
        "type": "cabinet",
    }


def test_spatial_assertion_rejects_conflicting_identity_for_one_source_ref() -> None:
    spans = (
        SpatialImageSpan(
            source_ref="master:1", source_digest="sha256:" + "a" * 64, view="MASTER", x0=0.1, y0=0.1, x1=0.3, y1=0.3
        ),
        SpatialImageSpan(
            source_ref="master:1", source_digest="sha256:" + "b" * 64, view="REVERSE", x0=0.4, y0=0.4, x1=0.6, y1=0.6
        ),
    )
    with pytest.raises(ValidationError, match="one identity"):
        SpatialAssertion(
            assertion_id="a1",
            evidence_class=EvidenceClass.VISIBLE,
            source_refs=("master:1",),
            source_spans=spans,
            relation="cabinet on front wall",
            subject_refs=("cabinet",),
            confidence=None,
            warnings=(),
        )


def test_spatial_payload_rejects_duplicate_assertion_ids() -> None:
    assertion = SpatialAssertion(
        assertion_id="same-id",
        evidence_class=EvidenceClass.VISIBLE,
        source_refs=("master:1",),
        relation="cabinet on front wall",
        subject_refs=("cabinet",),
        confidence=None,
        warnings=(),
    )
    with pytest.raises(ValidationError, match="unique assertion ids"):
        SpatialPayload(
            assertions=(assertion, assertion),
            seam_locks=(),
            direction_locks=(),
            duplicate_warnings=(),
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )
