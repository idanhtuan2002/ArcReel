"""Typed spatial constraints that one exact LOCATION binding version can carry (ADR-0102 decision 3).

Every field is derived on the server from one exact SPATIAL candidate revision, its reviewed
pair and its frame receipts. Only VISIBLE assertions become constraints; INFERRED and GAP rows
are carried as coverage warnings and never as production facts.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from r2.contracts.advanced_creative import CanonicalJsonObject, EvidenceClass, SpatialImageSpan
from r2.contracts.common import R2ContractModel
from r2.contracts.production_binding_authority import BindingId, ExactName
from r2.contracts.production_target import Sha256Digest
from r2.contracts.spatial_pair import PairId
from r2.contracts.spatial_source import FrameCandidateId

SpatialConstraintSetId = Annotated[str, StringConstraints(pattern=r"^m8s:[0-9a-f]{64}$")]
SpatialRelationKind = Literal["PRESERVE_ON_WALL", "SHARED_SIDE_ANCHOR"]
SpatialWall = Literal["front", "back", "left", "right"]
SpatialView = Literal["MASTER", "REVERSE"]

_KIND_WALLS: dict[str, frozenset[str]] = {
    "PRESERVE_ON_WALL": frozenset({"front", "back"}),
    "SHARED_SIDE_ANCHOR": frozenset({"left", "right"}),
}


class _ConstraintBody(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SpatialConstraintV1(_ConstraintBody):
    assertion_id: ExactName
    relation_kind: SpatialRelationKind
    subject_ref: ExactName
    wall: SpatialWall
    source_spans: tuple[SpatialImageSpan, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_kind_and_views(self) -> Self:
        if self.wall not in _KIND_WALLS[self.relation_kind]:
            raise ValueError(f"{self.relation_kind} does not apply to the {self.wall} wall")
        views = {span.view for span in self.source_spans}
        if self.relation_kind == "SHARED_SIDE_ANCHOR" and views != {"MASTER", "REVERSE"}:
            raise ValueError("a shared side anchor needs source spans from both views")
        return self


class SpatialSourceBindingV1(_ConstraintBody):
    view: SpatialView
    parent_artifact_key: ExactName
    parent_master_version: int = Field(ge=1)
    parent_candidate_id: ExactName
    parent_content_digest: Sha256Digest
    frame_derivation_receipt_id: FrameCandidateId
    frame_derivation_receipt_digest: Sha256Digest
    frame_candidate_id: FrameCandidateId
    frame_content_digest: Sha256Digest

    @model_validator(mode="after")
    def check_frame_identity(self) -> Self:
        if self.frame_derivation_receipt_id != self.frame_candidate_id:
            raise ValueError("a frame receipt ID must equal its frame candidate ID")
        return self


class SpatialCoverageWarningV1(_ConstraintBody):
    assertion_id: ExactName
    evidence_class: Literal[EvidenceClass.INFERRED, EvidenceClass.GAP]
    relation: ExactName


class SpatialConstraintSetV1(_ConstraintBody):
    schema_version: Literal["1"]
    user_id: ExactName
    project_name: ExactName
    binding_id: BindingId
    candidate_id: ExactName
    candidate_revision: int = Field(ge=1)
    candidate_payload_digest: Sha256Digest
    constraints: tuple[SpatialConstraintV1, ...] = Field(min_length=1)
    coverage_warnings: tuple[SpatialCoverageWarningV1, ...]
    seam_locks: tuple[CanonicalJsonObject, ...]
    direction_locks: tuple[CanonicalJsonObject, ...]
    duplicate_warnings: tuple[CanonicalJsonObject, ...]
    normalizer_version: ExactName
    pair_id: PairId
    pair_version: int = Field(ge=1)
    pair_decision_digest: Sha256Digest
    ordered_sources: tuple[SpatialSourceBindingV1, SpatialSourceBindingV1]

    @model_validator(mode="after")
    def check_identities(self) -> Self:
        if [source.view for source in self.ordered_sources] != ["MASTER", "REVERSE"]:
            raise ValueError("constraint set sources must be MASTER then REVERSE")
        if self.ordered_sources[0].frame_candidate_id == self.ordered_sources[1].frame_candidate_id:
            raise ValueError("constraint set sources must be two distinct frames")
        ids = [item.assertion_id for item in (*self.constraints, *self.coverage_warnings)]
        if len(ids) != len(set(ids)):
            raise ValueError("constraint and warning assertion IDs must be unique")
        digests = {source.view: source.frame_content_digest for source in self.ordered_sources}
        for constraint in self.constraints:
            for span in constraint.source_spans:
                if digests[span.view] != span.source_digest:
                    raise ValueError("a constraint span does not resolve to the frame of its view")
        return self


__all__ = [
    "SpatialConstraintSetId",
    "SpatialConstraintSetV1",
    "SpatialConstraintV1",
    "SpatialCoverageWarningV1",
    "SpatialRelationKind",
    "SpatialSourceBindingV1",
    "SpatialView",
    "SpatialWall",
]
