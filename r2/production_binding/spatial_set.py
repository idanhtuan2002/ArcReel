"""Digest, identity and server-side derivation of a typed spatial constraint set."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from r2.advanced_creative.digests import digest_payload
from r2.contracts.advanced_creative import (
    EvidenceClass,
    ExplorationKind,
    ExplorationRevision,
    SpatialAssertion,
    SpatialCandidate,
)
from r2.contracts.common import ensure_json_value
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.spatial_constraint import (
    SpatialConstraintSetV1,
    SpatialConstraintV1,
    SpatialCoverageWarningV1,
    SpatialSourceBindingV1,
)

SPATIAL_CONSTRAINT_SET_DOMAIN = "r2.m8.spatial.constraint_set.v1"
_KIND_BY_WALL = {
    "front": "PRESERVE_ON_WALL",
    "back": "PRESERVE_ON_WALL",
    "left": "SHARED_SIDE_ANCHOR",
    "right": "SHARED_SIDE_ANCHOR",
}


class SpatialConstraintError(ValueError):
    """The selection cannot become a typed production constraint."""


def spatial_constraint_set_digest(body: Mapping[str, Any]) -> str:
    constraint_set = SpatialConstraintSetV1.model_validate(body)
    envelope = ensure_json_value(
        {
            "domain": SPATIAL_CONSTRAINT_SET_DOMAIN,
            "canonical_version": "1",
            "body": constraint_set.model_dump(mode="json"),
        }
    )
    return "sha256:" + hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()


def spatial_constraint_set_id(digest: str) -> str:
    return "m8s:" + digest.removeprefix("sha256:")


def _wall(assertion: SpatialAssertion) -> str:
    detail = assertion.evidence_detail.model_dump(mode="json") if assertion.evidence_detail is not None else {}
    wall = detail.get("wall")
    if wall not in _KIND_BY_WALL:
        raise SpatialConstraintError(f"assertion {assertion.assertion_id} has no server-stamped wall")
    return wall


def _constraint(assertion: SpatialAssertion) -> SpatialConstraintV1:
    if assertion.evidence_class is not EvidenceClass.VISIBLE:
        raise SpatialConstraintError(f"assertion {assertion.assertion_id} is not VISIBLE")
    if len(assertion.subject_refs) != 1:
        raise SpatialConstraintError(f"assertion {assertion.assertion_id} must name exactly one subject")
    wall = _wall(assertion)
    try:
        return SpatialConstraintV1(
            assertion_id=assertion.assertion_id,
            relation_kind=_KIND_BY_WALL[wall],  # type: ignore[arg-type]
            subject_ref=assertion.subject_refs[0],
            wall=wall,  # type: ignore[arg-type]
            source_spans=assertion.source_spans,
        )
    except ValueError as exc:
        raise SpatialConstraintError(f"assertion {assertion.assertion_id}: {exc}") from exc


def derive_spatial_constraint_set(
    *,
    user_id: str,
    project_name: str,
    binding_id: str,
    revision: ExplorationRevision,
    selected_assertion_ids: Sequence[str],
    pair_id: str,
    pair_version: int,
    pair_decision_digest: str,
    ordered_sources: tuple[SpatialSourceBindingV1, SpatialSourceBindingV1],
) -> SpatialConstraintSetV1:
    """Select VISIBLE assertions of one exact SPATIAL revision as typed constraints.

    Non-selected INFERRED and GAP rows become coverage warnings; non-selected VISIBLE rows are
    omitted. The revision's payload digest is recomputed, so a tampered revision is refused.
    """
    if revision.kind is not ExplorationKind.SPATIAL or not isinstance(revision.payload, SpatialCandidate):
        raise SpatialConstraintError("constraints can only be derived from a SPATIAL revision")
    if digest_payload(revision.payload, revision.lineage) != revision.payload_digest:
        raise SpatialConstraintError("the spatial revision payload differs from its digest")
    selected = list(selected_assertion_ids)
    if not selected or len(selected) != len(set(selected)):
        raise SpatialConstraintError("the selection must name distinct assertions")
    spatial = revision.payload.spatial
    by_id = {assertion.assertion_id: assertion for assertion in spatial.assertions}
    unknown = [assertion_id for assertion_id in selected if assertion_id not in by_id]
    if unknown:
        raise SpatialConstraintError(f"the selection names unknown assertions: {unknown}")
    constraints = tuple(_constraint(by_id[assertion_id]) for assertion_id in selected)
    try:
        warnings = tuple(
            SpatialCoverageWarningV1(
                assertion_id=assertion.assertion_id,
                evidence_class=assertion.evidence_class,
                relation=assertion.relation,
            )
            for assertion in spatial.assertions
            if assertion.evidence_class in (EvidenceClass.INFERRED, EvidenceClass.GAP)
        )
        return SpatialConstraintSetV1(
            schema_version="1",
            user_id=user_id,
            project_name=project_name,
            binding_id=binding_id,
            candidate_id=revision.candidate_id,
            candidate_revision=revision.revision,
            candidate_payload_digest=revision.payload_digest,
            constraints=constraints,
            coverage_warnings=warnings,
            seam_locks=spatial.seam_locks,
            direction_locks=spatial.direction_locks,
            duplicate_warnings=spatial.duplicate_warnings,
            normalizer_version=spatial.normalizer_version,
            pair_id=pair_id,
            pair_version=pair_version,
            pair_decision_digest=pair_decision_digest,
            ordered_sources=ordered_sources,
        )
    except ValueError as exc:
        raise SpatialConstraintError(str(exc)) from exc


__all__ = [
    "SPATIAL_CONSTRAINT_SET_DOMAIN",
    "SpatialConstraintError",
    "derive_spatial_constraint_set",
    "spatial_constraint_set_digest",
    "spatial_constraint_set_id",
]
