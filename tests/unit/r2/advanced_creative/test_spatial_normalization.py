from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from r2.advanced_creative.spatial import (
    SpatialNormalizationError,
    SpatialSourceIdentity,
    normalize_spatial_candidate,
    normalize_spatial_topology,
)
from r2.contracts.advanced_creative import EvidenceClass, ExplorationKind


def _fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    contract: dict[str, Any] = {
        "schema_version": "r2-spatial-response-v1",
        "walls": {
            "front": {
                "must_preserve": [
                    {
                        "name": "red fire extinguisher cabinet",
                        "type": "cabinet",
                        "source_view": "master",
                        "size_lock": "large",
                        "source_spans": [{"source_ref": "master:1", "x0": 0.05, "y0": 0.2, "x1": 0.2, "y1": 0.8}],
                    }
                ]
            },
            "back": {
                "must_preserve": [
                    {"name": "blue exit door", "type": "door", "source_view": "reverse", "size_lock": "large"}
                ]
            },
            "left": {"panorama_position": "x=0%/100% seam", "shared_overlap": []},
            "right": {"panorama_position": "x=50%", "shared_overlap": []},
        },
        "joins": [],
    }
    overlap: dict[str, Any] = {
        "pairs": [
            {
                "id": "left_side_join",
                "overlap_items": [{"name": "red fire extinguisher cabinet"}, {"name": "plain wall surface"}],
                "continuation_items": [],
            }
        ],
        "do_not_duplicate": ["red fire extinguisher cabinet"],
    }
    return contract, overlap


def test_overlap_keeps_one_shared_anchor_and_only_back_direction_lock() -> None:
    contract, overlap = _fixture()
    before = deepcopy(contract)

    result = normalize_spatial_topology(contract, overlap)

    assert contract == before
    walls = result["walls"]
    assert [item["name"] for item in walls["left"]["shared_overlap"]] == ["red fire extinguisher cabinet"]
    assert (
        walls["left"]["shared_overlap"][0]["source_spans"]
        == before["walls"]["front"]["must_preserve"][0]["source_spans"]
    )
    assert walls["front"]["must_preserve"] == []
    assert result["joins"][0]["merge_once"] == ["red fire extinguisher cabinet"]
    assert result["joins"][0]["continue_smoothly"] == ["plain wall surface"]
    assert result["joins"][0]["do_not_duplicate"] == ["red fire extinguisher cabinet"]
    assert [(item["name"], item["required_direction"]) for item in result["direction_exclusion_locks"]] == [
        ("blue exit door", "back")
    ]
    assert [item["name"] for item in result["overlap_duplicate_warnings"]] == ["red fire extinguisher cabinet"]
    assert [item["name"] for item in result["overlap_merge_locks"]] == ["red fire extinguisher cabinet"]


def test_non_anchor_shared_surface_remains_inference_not_duplicate_anchor() -> None:
    contract, overlap = _fixture()
    contract["walls"]["left"]["shared_overlap"] = [{"name": "plain wall surface"}]

    result = normalize_spatial_topology(contract, overlap)

    assert [item["name"] for item in result["walls"]["left"]["shared_overlap"]] == ["red fire extinguisher cabinet"]
    assert result["walls"]["left"].get("inferred_fill", []) == []
    assert result["joins"][0]["continue_smoothly"] == ["plain wall surface"]


def test_normalization_is_idempotent() -> None:
    contract, overlap = _fixture()

    once = normalize_spatial_topology(contract, overlap)
    twice = normalize_spatial_topology(once, overlap)

    assert twice == once


def test_inferred_and_both_view_items_do_not_receive_direction_locks() -> None:
    contract, _ = _fixture()
    walls = contract["walls"]
    walls["front"]["must_preserve"] = [
        {"name": "large window", "type": "window", "source_view": "inferred", "size_lock": "large"}
    ]
    walls["back"]["must_preserve"] = [
        {"name": "blue exit door", "type": "door", "source_view": "both", "size_lock": "large"}
    ]

    result = normalize_spatial_topology(contract, None)

    assert result["direction_exclusion_locks"] == []


@pytest.mark.parametrize(
    "invalid",
    [
        {"walls": [], "joins": []},
        {"walls": {"front": [], "back": {}, "left": {}, "right": {}}, "joins": []},
        {"walls": {"front": {}, "back": {}, "left": {}, "right": {}}, "joins": {}},
    ],
)
def test_malformed_topology_fails_closed(invalid: dict[str, object]) -> None:
    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_topology(invalid, None)


def _candidate_fixture() -> tuple[dict[str, Any], dict[str, SpatialSourceIdentity]]:
    raw, _ = _fixture()
    raw["walls"]["back"]["must_preserve"][0]["source_spans"] = [
        {"source_ref": "reverse:1", "x0": 0.7, "y0": 0.2, "x1": 0.9, "y1": 0.8}
    ]
    raw["walls"]["front"]["inferred_fill"] = [
        {
            "name": "hidden corridor",
            "relation": "corridor may continue",
            "confidence": 0.4,
            "source_refs": ["master:1"],
        }
    ]
    raw["coverage_assessment"] = {
        "coverage_gaps": [
            {"area": "left_side_transition", "description": "left rear corner unseen", "source_refs": ["reverse:1"]}
        ]
    }
    sources = {
        "master:1": SpatialSourceIdentity(source_digest="sha256:" + "a" * 64, view="MASTER"),
        "reverse:1": SpatialSourceIdentity(source_digest="sha256:" + "b" * 64, view="REVERSE"),
    }
    return raw, sources


def test_candidate_normalization_preserves_visible_inferred_and_gap_evidence() -> None:
    raw, sources = _candidate_fixture()

    candidate = normalize_spatial_candidate(
        raw,
        overlap_analysis=None,
        sources=sources,
        execution_id="execution-1",
        normalizer_version="spatial-r2-v1",
    )

    assert candidate.kind is ExplorationKind.SPATIAL
    assert [assertion.evidence_class for assertion in candidate.spatial.assertions] == [
        EvidenceClass.VISIBLE,
        EvidenceClass.INFERRED,
        EvidenceClass.VISIBLE,
        EvidenceClass.GAP,
    ]
    front = candidate.spatial.assertions[0]
    assert front.source_spans[0].source_digest == sources["master:1"].source_digest
    assert front.evidence_detail is not None
    assert front.evidence_detail.model_dump(mode="json")["size_lock"] == "large"
    assert front.evidence_detail.model_dump(mode="json")["wall"] == "front"
    assert candidate.spatial.assertions[1].confidence == 0.4
    assert candidate.spatial.assertions[1].source_refs == ("master:1",)
    assert candidate.spatial.assertions[-1].source_spans == ()
    assert candidate.spatial.assertions[-1].source_refs == ("reverse:1",)
    assert len(candidate.spatial.direction_locks) == 2
    assert candidate == normalize_spatial_candidate(
        raw,
        overlap_analysis=None,
        sources=sources,
        execution_id="execution-1",
        normalizer_version="spatial-r2-v1",
    )


def test_same_visible_item_in_two_wall_buckets_has_distinct_assertion_ids() -> None:
    raw, sources = _candidate_fixture()
    raw["walls"]["front"]["shared_overlap"] = [deepcopy(raw["walls"]["front"]["must_preserve"][0])]

    candidate = normalize_spatial_candidate(
        raw,
        overlap_analysis=None,
        sources=sources,
        execution_id="execution-1",
        normalizer_version="spatial-r2-v1",
    )

    visible = [
        assertion for assertion in candidate.spatial.assertions if assertion.evidence_class is EvidenceClass.VISIBLE
    ]
    assert len(visible) == 3
    assert len({assertion.assertion_id for assertion in visible}) == 3


def test_candidate_rejects_visible_item_without_object_span() -> None:
    raw, sources = _candidate_fixture()
    del raw["walls"]["front"]["must_preserve"][0]["source_spans"]

    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=None,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )


@pytest.mark.parametrize(
    ("wall", "foreign_ref"),
    [("front", "reverse:1"), ("back", "master:1")],
)
def test_candidate_rejects_visible_source_view_mismatch(wall: str, foreign_ref: str) -> None:
    raw, sources = _candidate_fixture()
    raw["walls"][wall]["must_preserve"][0]["source_spans"][0]["source_ref"] = foreign_ref

    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=None,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )


def test_candidate_rejects_unknown_source_and_unbounded_inference() -> None:
    raw, sources = _candidate_fixture()
    raw["walls"]["front"]["must_preserve"][0]["source_spans"][0]["source_ref"] = "foreign:1"
    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=None,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )

    raw, sources = _candidate_fixture()
    del raw["walls"]["front"]["inferred_fill"][0]["confidence"]
    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=None,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )


def test_shared_anchor_retains_both_object_spans_without_direction_migration() -> None:
    raw, sources = _candidate_fixture()
    raw["walls"]["back"]["must_preserve"].append(
        {
            "name": "red fire extinguisher cabinet",
            "type": "cabinet",
            "source_view": "reverse",
            "size_lock": "large",
            "source_spans": [{"source_ref": "reverse:1", "x0": 0.8, "y0": 0.2, "x1": 0.95, "y1": 0.8}],
        }
    )
    _, overlap = _fixture()

    candidate = normalize_spatial_candidate(
        raw,
        overlap_analysis=overlap,
        sources=sources,
        execution_id="execution-1",
        normalizer_version="spatial-r2-v1",
    )

    shared = [a for a in candidate.spatial.assertions if a.subject_refs == ("red fire extinguisher cabinet",)]
    assert len(shared) == 1
    assert {span.view for span in shared[0].source_spans} == {"MASTER", "REVERSE"}
    assert all(
        lock.model_dump(mode="json")["name"] != "red fire extinguisher cabinet"
        for lock in candidate.spatial.direction_locks
    )


def test_existing_side_anchor_retains_span_from_each_view() -> None:
    raw, sources = _candidate_fixture()
    raw["walls"]["back"]["must_preserve"].append(
        {
            "name": "red fire extinguisher cabinet",
            "type": "cabinet",
            "source_view": "reverse",
            "source_spans": [{"source_ref": "reverse:1", "x0": 0.8, "y0": 0.2, "x1": 0.95, "y1": 0.8}],
        }
    )
    raw["walls"]["left"]["shared_overlap"] = [
        {
            "name": "red fire extinguisher cabinet",
            "source_view": "both",
            "source_spans": raw["walls"]["front"]["must_preserve"][0]["source_spans"],
        }
    ]
    _, overlap = _fixture()

    candidate = normalize_spatial_candidate(
        raw,
        overlap_analysis=overlap,
        sources=sources,
        execution_id="execution-1",
        normalizer_version="spatial-r2-v1",
    )

    shared = [a for a in candidate.spatial.assertions if a.subject_refs == ("red fire extinguisher cabinet",)]
    assert len(shared) == 1
    assert {span.source_ref for span in shared[0].source_spans} == {"master:1", "reverse:1"}


def test_non_anchor_surface_keeps_typed_seam_without_untyped_inference() -> None:
    raw, sources = _candidate_fixture()
    raw["walls"]["back"]["must_preserve"].append(
        {
            "name": "red fire extinguisher cabinet",
            "type": "cabinet",
            "source_view": "reverse",
            "source_spans": [{"source_ref": "reverse:1", "x0": 0.8, "y0": 0.2, "x1": 0.95, "y1": 0.8}],
        }
    )
    raw["walls"]["left"]["shared_overlap"] = [
        {
            "name": "plain wall surface",
            "source_view": "both",
            "source_spans": [
                {"source_ref": "master:1", "x0": 0.2, "y0": 0.1, "x1": 0.4, "y1": 0.9},
                {"source_ref": "reverse:1", "x0": 0.6, "y0": 0.1, "x1": 0.8, "y1": 0.9},
            ],
        }
    ]
    _, overlap = _fixture()

    candidate = normalize_spatial_candidate(
        raw,
        overlap_analysis=overlap,
        sources=sources,
        execution_id="execution-1",
        normalizer_version="spatial-r2-v1",
    )
    serialized = candidate.model_dump(mode="json")["spatial"]

    assert any(
        lock["kind"] == "join"
        and lock["id"] == "left_side_join"
        and lock["continue_smoothly"] == ["plain wall surface"]
        for lock in serialized["seam_locks"]
    )
    assert all("plain wall surface" not in assertion["subject_refs"] for assertion in serialized["assertions"])
    assert [
        assertion["relation"] for assertion in serialized["assertions"] if assertion["evidence_class"] == "INFERRED"
    ] == ["corridor may continue"]


def test_candidate_rejects_foreign_inference_source_and_empty_evidence() -> None:
    raw, sources = _candidate_fixture()
    raw["walls"]["front"]["inferred_fill"][0]["source_refs"] = ["foreign:1"]
    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=None,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )

    raw, sources = _candidate_fixture()
    for wall in raw["walls"].values():
        wall["must_preserve"] = []
        wall["inferred_fill"] = []
    raw["coverage_assessment"]["coverage_gaps"] = []
    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=None,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )


@pytest.mark.parametrize("invalid", ["not a list", ["not an object"]])
def test_candidate_rejects_malformed_seam_locks(invalid: object) -> None:
    raw, sources = _candidate_fixture()
    raw["must_not_transform"] = invalid

    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=None,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )


def test_candidate_does_not_accept_model_authored_seam_classification() -> None:
    raw, sources = _candidate_fixture()
    raw["must_not_transform"] = [{"kind": "join", "source_object": "red cabinet"}]

    candidate = normalize_spatial_candidate(
        raw,
        overlap_analysis=None,
        sources=sources,
        execution_id="execution-1",
        normalizer_version="spatial-r2-v1",
    )

    assert candidate.spatial.seam_locks[0].model_dump(mode="json")["kind"] == "forbidden_transform"


def test_candidate_rejects_unrecognized_wall_and_untyped_inference_before_normalization() -> None:
    raw, sources = _candidate_fixture()
    raw["walls"]["unmapped_view"] = {"must_preserve": [{"name": "unexamined door"}]}
    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=None,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )

    raw, sources = _candidate_fixture()
    raw["joins"] = [{"id": "unknown_join", "merge_once": ["red cabinet"]}]
    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=None,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )

    raw, sources = _candidate_fixture()
    raw["joins"] = [{"id": "left_side_join"}, {"id": "left_side_join"}]
    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=None,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )

    raw, sources = _candidate_fixture()
    _, overlap = _fixture()
    overlap["pairs"][0]["id"] = "unmapped_join"
    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=overlap,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )

    raw, sources = _candidate_fixture()
    raw["schema_version"] = "unreviewed-schema"
    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=None,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )

    raw, sources = _candidate_fixture()
    raw["walls"]["front"]["inferred_fill"] = ["untyped corridor guess"]
    _, overlap = _fixture()
    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=overlap,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )

    raw, sources = _candidate_fixture()
    raw["walls"]["front"]["must_preserve"][0]["source_view"] = "inferred"
    with pytest.raises(SpatialNormalizationError):
        normalize_spatial_candidate(
            raw,
            overlap_analysis=None,
            sources=sources,
            execution_id="execution-1",
            normalizer_version="spatial-r2-v1",
        )
