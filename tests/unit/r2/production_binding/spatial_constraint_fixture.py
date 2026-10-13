"""One exact SPATIAL revision with front, back and shared-side VISIBLE rows plus INFERRED and GAP rows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from r2.advanced_creative.digests import digest_payload
from r2.advanced_creative.spatial import SpatialSourceIdentity, normalize_spatial_candidate
from r2.contracts.advanced_creative import ExplorationKind, ExplorationRevision, LineageBinding
from r2.contracts.spatial_constraint import SpatialSourceBindingV1

USER = "default"
PROJECT = "demo-project"
BINDING_ID = "m8b:" + "b" * 64
PAIR_ID = "m8p:" + "c" * 64
PAIR_DECISION_DIGEST = "sha256:" + "d" * 64
MASTER_FRAME = "m8f:" + "1" * 64
REVERSE_FRAME = "m8f:" + "2" * 64
MASTER_DIGEST = "sha256:" + "a1" * 32
REVERSE_DIGEST = "sha256:" + "a2" * 32


def _span(ref: str, x0: float, x1: float) -> dict[str, Any]:
    return {"source_ref": ref, "x0": x0, "y0": 0.2, "x1": x1, "y1": 0.8}


def raw_response() -> dict[str, Any]:
    return {
        "schema_version": "r2-spatial-response-v1",
        "walls": {
            "front": {
                "must_preserve": [
                    {
                        "name": "red fire extinguisher cabinet",
                        "type": "cabinet",
                        "source_view": "master",
                        "size_lock": "large",
                        "source_spans": [_span("master", 0.7, 0.82)],
                    }
                ],
                "inferred_fill": [
                    {
                        "name": "radiator",
                        "relation": "may sit under the window",
                        "confidence": 0.3,
                        "source_refs": ["master"],
                    }
                ],
            },
            "back": {
                "must_preserve": [
                    {
                        "name": "blue exit door",
                        "type": "door",
                        "source_view": "reverse",
                        "size_lock": "large",
                        "source_spans": [_span("reverse", 0.65, 0.79)],
                    }
                ]
            },
            "left": {
                "shared_overlap": [
                    {
                        "name": "yellow painting",
                        "source_view": "both",
                        "source_spans": [_span("master", 0.0, 0.12), _span("reverse", 0.88, 1.0)],
                    }
                ]
            },
            "right": {"shared_overlap": []},
        },
        "joins": [],
        "coverage_assessment": {
            "coverage_gaps": [{"description": "ceiling corners unseen", "source_refs": ["reverse"]}]
        },
    }


def revision(
    *, master_digest: str = MASTER_DIGEST, reverse_digest: str = REVERSE_DIGEST, project_name: str = PROJECT
) -> ExplorationRevision:
    candidate = normalize_spatial_candidate(
        raw_response(),
        overlap_analysis=None,
        sources={
            "master": SpatialSourceIdentity(source_digest=master_digest, view="MASTER"),
            "reverse": SpatialSourceIdentity(source_digest=reverse_digest, view="REVERSE"),
        },
        execution_id="execution-1",
        normalizer_version="spatial-r2-v1",
    )
    lineage = LineageBinding(
        project_name=project_name,
        content_basis_digest="sha256:" + "3" * 64,
        approved_master_id=None,
        approved_master_digest=None,
        creative_profile_id="arcreel.host",
        creative_profile_version="1",
        policy_digest="sha256:" + "4" * 64,
    )
    return ExplorationRevision(
        candidate_id="spatial-candidate-1",
        revision=1,
        kind=ExplorationKind.SPATIAL,
        parent_revision=None,
        payload=candidate,
        payload_digest=digest_payload(candidate, lineage),
        lineage=lineage,
        created_by=USER,
        created_at=datetime(2026, 10, 13, tzinfo=UTC),
    )


def sources() -> tuple[SpatialSourceBindingV1, SpatialSourceBindingV1]:
    def source(view: str, frame: str, digest: str, parent: str) -> SpatialSourceBindingV1:
        return SpatialSourceBindingV1.model_validate(
            {
                "view": view,
                "parent_artifact_key": f"artifact-key-v1:{parent}",
                "parent_master_version": 1,
                "parent_candidate_id": f"candidate-{parent}",
                "parent_content_digest": "sha256:" + "5" * 64,
                "frame_derivation_receipt_id": frame,
                "frame_derivation_receipt_digest": "sha256:" + "6" * 64,
                "frame_candidate_id": frame,
                "frame_content_digest": digest,
            }
        )

    return (
        source("MASTER", MASTER_FRAME, MASTER_DIGEST, "SH01"),
        source("REVERSE", REVERSE_FRAME, REVERSE_DIGEST, "SH02"),
    )


def visible_ids_by_subject() -> dict[str, str]:
    payload = revision().payload
    return {
        assertion.subject_refs[0]: assertion.assertion_id
        for assertion in payload.spatial.assertions
        if assertion.evidence_class.value == "VISIBLE"
    }
