"""Deterministic topology normalization for spatial candidate evidence."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError, model_validator

from r2.advanced_creative.digests import digest_canonical
from r2.contracts.advanced_creative import (
    CanonicalJsonObject,
    EvidenceClass,
    ExplorationKind,
    SpatialAssertion,
    SpatialCandidate,
    SpatialImageSpan,
    SpatialPayload,
)

_TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "art",
    "fixture",
    "fixtures",
    "frame",
    "framed",
    "large",
    "small",
    "the",
    "wall",
}
_UNIQUE_ANCHORS = {
    "ad",
    "ads",
    "board",
    "cabinet",
    "counter",
    "curtain",
    "display",
    "door",
    "drapery",
    "extinguisher",
    "frame",
    "lightbox",
    "menu",
    "panel",
    "painting",
    "poster",
    "shelf",
    "shelves",
    "sign",
    "sofa",
    "couch",
    "bookshelf",
    "bookcase",
    "desk",
    "window",
}
_SURFACES = {"ceiling", "floor", "flooring", "light", "lighting", "rug", "wall"}
_CENTER_OBJECTS = ("area rug", "coffee table", "center table", "central table", "茶几", "地毯")
_SURFACE_MARKERS = (
    "carpet",
    "ceiling",
    "floor",
    "plain wall",
    "rug",
    "wall area",
    "wall behind",
    "wall section",
    "wall surface",
)
_UNIQUE_SURFACE_MARKERS = (
    "cabinet",
    "display",
    "door",
    "drapery",
    "curtain",
    "extinguisher",
    "lightbox",
    "menu",
    "panel",
    "poster",
    "sign",
    "window",
)
_DIRECTION_TYPES = {"cabinet", "display_panel", "door", "fixture", "furniture", "light", "opening", "sign"}
_LARGE_SIZES = {"large", "full_height", "full_width", "wall_dominant"}
_DIRECTION_NAMES = {
    "bookcase",
    "bookshelf",
    "cabinet",
    "desk",
    "display",
    "door",
    "elevator",
    "panel",
    "screen",
    "shelf",
    "sofa",
    "tv",
    "window",
}


class SpatialNormalizationError(ValueError):
    """The model response cannot be normalized without losing spatial evidence."""


class _RawSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_ref: str = Field(min_length=1)
    x0: FiniteFloat = Field(ge=0, le=1)
    y0: FiniteFloat = Field(ge=0, le=1)
    x1: FiniteFloat = Field(ge=0, le=1)
    y1: FiniteFloat = Field(ge=0, le=1)

    @model_validator(mode="after")
    def require_positive_area(self) -> _RawSpan:
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("object span must have positive area")
        return self


class _RawVisible(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    name: str = Field(min_length=1)
    source_view: Literal["master", "reverse", "both"]
    source_spans: list[_RawSpan] = Field(min_length=1)


class _RawInference(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    name: str = Field(min_length=1)
    relation: str = Field(min_length=1)
    confidence: FiniteFloat = Field(ge=0, le=1)
    source_refs: list[str] = Field(default_factory=list)


class _RawGap(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    description: str = Field(min_length=1)
    source_refs: list[str] = Field(default_factory=list)


class _RawWall(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    must_preserve: list[_RawVisible] = Field(default_factory=list)
    shared_overlap: list[_RawVisible] = Field(default_factory=list)
    inferred_fill: list[_RawInference] = Field(default_factory=list)


class _RawWalls(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    front: _RawWall
    back: _RawWall
    left: _RawWall
    right: _RawWall


class _RawCoverageAssessment(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    coverage_gaps: list[_RawGap] = Field(default_factory=list)


class _RawJoin(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    id: Literal["left_side_join", "right_side_join"]
    merge_once: list[str] = Field(default_factory=list)
    continue_smoothly: list[str] = Field(default_factory=list)
    do_not_duplicate: list[str] = Field(default_factory=list)


class _RawSpatialResponse(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    schema_version: Literal["r2-spatial-response-v1"]
    walls: _RawWalls
    joins: list[_RawJoin]
    coverage_assessment: _RawCoverageAssessment | None = None
    coverage_gaps: list[_RawGap] = Field(default_factory=list)
    must_not_transform: list[dict[str, Any]] = Field(default_factory=list)
    direction_exclusion_locks: list[dict[str, Any]] = Field(default_factory=list)
    overlap_merge_locks: list[dict[str, Any]] = Field(default_factory=list)
    overlap_duplicate_warnings: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_distinct_joins(self) -> _RawSpatialResponse:
        if len({join.id for join in self.joins}) != len(self.joins):
            raise ValueError("spatial joins must have distinct directions")
        return self


class _RawOverlapPair(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    id: Literal["left_side_join", "right_side_join"]
    overlap_items: list[str | dict[str, Any]] = Field(default_factory=list)
    continuation_items: list[str | dict[str, Any]] = Field(default_factory=list)


class _RawOverlapAnalysis(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    pairs: list[_RawOverlapPair]
    do_not_duplicate: list[str | dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_distinct_pairs(self) -> _RawOverlapAnalysis:
        if len({pair.id for pair in self.pairs}) != len(self.pairs):
            raise ValueError("overlap pairs must have distinct directions")
        return self


@dataclass(frozen=True)
class SpatialSourceIdentity:
    """Exact source identity supplied by an upstream custody reader."""

    source_digest: str
    view: Literal["MASTER", "REVERSE"]


def _tokens(value: object) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", str(value or "").lower())
        if len(token) > 1 and token not in _TOKEN_STOPWORDS
    }


def _same_name(candidate: str, target: str) -> bool:
    left, right = _tokens(candidate), _tokens(target)
    overlap = left & right
    return bool(overlap) and (overlap in (right, left) or len(overlap) >= min(2, len(right)))


def _unique_names(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        name = value.strip()
        key = " ".join(sorted(_tokens(name))) or name.lower()
        if name and key not in seen:
            seen.add(key)
            result.append(name)
    return result


def _names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return _unique_names(
        [str(item.get("name") or "").strip() if isinstance(item, dict) else str(item or "").strip() for item in value]
    )


def _unique_anchor(name: str) -> bool:
    lowered = name.lower()
    return bool(_tokens(name) & _UNIQUE_ANCHORS) or any(
        marker in lowered
        for marker in ("消防", "柜", "门", "窗", "屏", "牌", "菜单", "椅", "画", "沙发", "书架", "书柜")
    )


def _side_anchor(name: str) -> bool:
    lowered = name.lower().strip()
    if not lowered or any(marker in lowered for marker in _CENTER_OBJECTS):
        return False
    if any(marker in lowered for marker in _SURFACE_MARKERS) and not any(
        marker in lowered for marker in _UNIQUE_SURFACE_MARKERS
    ):
        return False
    if _tokens(name) & _SURFACES and not _tokens(name) & _UNIQUE_ANCHORS:
        return False
    return _unique_anchor(name)


def _wall(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SpatialNormalizationError(f"{name} wall must be an object")
    for field in ("must_preserve", "shared_overlap", "inferred_fill"):
        if field in value and not isinstance(value[field], list):
            raise SpatialNormalizationError(f"{name}.{field} must be a list")
    return value


def _move_representative(walls: dict[str, Any], name: str) -> dict[str, Any] | None:
    representative: dict[str, Any] | None = None
    combined_spans: list[Any] = []
    for wall_id in ("front", "back"):
        preserved = walls[wall_id].get("must_preserve", [])
        remaining: list[Any] = []
        for item in preserved:
            item_name = str(item.get("name") or "") if isinstance(item, dict) else str(item)
            if _same_name(item_name, name):
                if representative is None and isinstance(item, dict):
                    representative = deepcopy(item)
                if isinstance(item, dict):
                    item_spans = item.get("source_spans", [])
                    if not isinstance(item_spans, list):
                        raise SpatialNormalizationError("shared anchor source_spans must be a list")
                    for span in item_spans:
                        if span not in combined_spans:
                            combined_spans.append(deepcopy(span))
            else:
                remaining.append(item)
        walls[wall_id]["must_preserve"] = remaining
    if representative is not None:
        representative["source_spans"] = combined_spans
    return representative


def _direction_candidate(item: object) -> bool:
    if not isinstance(item, dict) or not str(item.get("name") or "").strip():
        return False
    source_view = str(item.get("source_view") or "").strip().lower()
    if source_view in {"both", "inferred"}:
        return False
    item_type = str(item.get("type") or "").strip().lower()
    size = str(item.get("size_lock") or "").strip().lower()
    if item_type == "wall_surface" and size not in _LARGE_SIZES:
        return False
    return item_type in _DIRECTION_TYPES or size in _LARGE_SIZES or bool(_tokens(item["name"]) & _DIRECTION_NAMES)


def _add_direction_locks(result: dict[str, Any]) -> None:
    locks = result.setdefault("direction_exclusion_locks", [])
    if not isinstance(locks, list):
        raise SpatialNormalizationError("direction_exclusion_locks must be a list")
    existing = {
        (str(item.get("name") or "").lower(), str(item.get("required_direction") or "").lower())
        for item in locks
        if isinstance(item, dict)
    }
    specs = {
        "front": (
            "raw x=25% / corrected viewer yaw 0°",
            "raw x=50% right-side join, raw x=75% reverse back center, or raw x=0%/100% safe seam",
            "This is visible in master front center and must not migrate to side/back zones.",
        ),
        "back": (
            "raw x=75% / corrected viewer yaw 180°",
            "raw x=25% master front center, raw x=50% right-side join, or raw x=0%/100% safe seam",
            "This is visible in reverse back center and must not be used to fill a side join or front wall.",
        ),
    }
    for direction, (zone, forbidden, reason) in specs.items():
        for item in result["walls"][direction].get("must_preserve", []):
            if not _direction_candidate(item):
                continue
            name = str(item["name"]).strip()
            key = (name.lower(), direction)
            if key not in existing:
                locks.append(
                    {
                        "name": name,
                        "required_direction": direction,
                        "required_panorama_zone": zone,
                        "must_not_appear_in": forbidden,
                        "reason": reason,
                    }
                )
                existing.add(key)


def normalize_spatial_topology(
    contract: dict[str, object], overlap_analysis: dict[str, object] | None
) -> dict[str, Any]:
    """Normalize selected donor overlap and direction behavior without mutating input."""
    result: dict[str, Any] = deepcopy(contract)
    walls = result.get("walls")
    joins = result.get("joins")
    if not isinstance(walls, dict) or not isinstance(joins, list):
        raise SpatialNormalizationError("walls object and joins list are required")
    for name in ("front", "back", "left", "right"):
        walls[name] = _wall(walls.get(name), name=name)
    if any(not isinstance(join, dict) for join in joins):
        raise SpatialNormalizationError("joins must contain objects")
    by_id: dict[str, dict[str, Any]] = {str(join.get("id") or ""): join for join in joins}

    pair_anchors: list[str] = []
    if overlap_analysis is not None:
        pairs = overlap_analysis.get("pairs", [])
        if not isinstance(pairs, list):
            raise SpatialNormalizationError("overlap pairs must be a list")
        for pair in pairs:
            if not isinstance(pair, dict):
                raise SpatialNormalizationError("overlap pair must be an object")
            pair_id = str(pair.get("id") or "").strip()
            if pair_id not in {"left_side_join", "right_side_join"}:
                continue
            side_id = "left" if pair_id == "left_side_join" else "right"
            join = by_id.get(pair_id)
            if join is None:
                new_join: dict[str, Any] = {
                    "id": pair_id,
                    "panorama_position": "x=0%/100% seam" if side_id == "left" else "x=50%",
                    "source_pair": "MASTER_LEFT + REVERSE_RIGHT"
                    if side_id == "left"
                    else "MASTER_RIGHT + REVERSE_LEFT",
                }
                join = new_join
                joins.append(join)
                by_id[pair_id] = join
            overlap = _names(pair.get("overlap_items"))
            anchors = [name for name in overlap if _side_anchor(name)]
            continuations = [name for name in overlap if not _side_anchor(name)]
            join["merge_once"] = _unique_names(anchors)
            join["do_not_duplicate"] = _unique_names(anchors)
            join["continue_smoothly"] = _unique_names(
                [*_names(join.get("continue_smoothly")), *_names(pair.get("continuation_items")), *continuations]
            )
            pair_anchors.extend(anchors)
            side = walls[side_id]
            shared = side.setdefault("shared_overlap", [])
            removed_names = [
                str(item.get("name") or "") if isinstance(item, dict) else str(item)
                for item in shared
                if not any(
                    _same_name(str(item.get("name") or "") if isinstance(item, dict) else str(item), anchor)
                    for anchor in anchors
                )
            ]
            side["shared_overlap"] = [
                item
                for item in shared
                if any(
                    _same_name(str(item.get("name") or "") if isinstance(item, dict) else str(item), anchor)
                    for anchor in anchors
                )
            ]
            if removed_names:
                join["continue_smoothly"] = _unique_names([*join["continue_smoothly"], *removed_names])
            for anchor in anchors:
                representative = _move_representative(walls, anchor)
                existing_anchor = next(
                    (
                        item
                        for item in side["shared_overlap"]
                        if _same_name(str(item.get("name") or "") if isinstance(item, dict) else str(item), anchor)
                    ),
                    None,
                )
                if existing_anchor is not None:
                    if not isinstance(existing_anchor, dict) or not isinstance(
                        existing_anchor.get("source_spans"), list
                    ):
                        raise SpatialNormalizationError("existing shared anchor requires source spans")
                    for span in (representative or {}).get("source_spans", []):
                        if span not in existing_anchor["source_spans"]:
                            existing_anchor["source_spans"].append(deepcopy(span))
                    continue
                side["shared_overlap"].append(
                    {
                        "name": anchor,
                        "type": str((representative or {}).get("type") or "fixture"),
                        "count": 1,
                        "source_view": "both",
                        "source_side": "side-overlap",
                        "panorama_zone": str(side.get("panorama_position") or ""),
                        "placement": f"{pair_id} shared overlap anchor",
                        "size_lock": str((representative or {}).get("size_lock") or "unknown"),
                        "visual_identity": str(
                            (representative or {}).get("visual_identity")
                            or "same physical side-edge anchor visible in both master and reverse"
                        ),
                        "must_not_become": ["two separate copies", "duplicated fixture"],
                        "source_spans": deepcopy((representative or {}).get("source_spans") or []),
                    }
                )
        result["overlap_duplicate_warnings"] = [
            {
                "name": name,
                "rule": "Do not create duplicate copies if this is visibly the same object, but do not move it between directions unless a side join explicitly lists it under merge_once.",
            }
            for name in _names(overlap_analysis.get("do_not_duplicate"))
        ]
        result["overlap_merge_locks"] = [
            {
                "name": name,
                "rule": "If this appears in both master and reverse side crops, render it once as a shared physical anchor, never as separate front/back copies.",
            }
            for name in _unique_names(pair_anchors)
        ]
        transforms = result.setdefault("must_not_transform", [])
        if not isinstance(transforms, list):
            raise SpatialNormalizationError("must_not_transform must be a list")
        for anchor in _unique_names(pair_anchors):
            if not any(
                isinstance(item, dict)
                and _same_name(str(item.get("source_object") or ""), anchor)
                and "duplicate" in str(item.get("forbidden_transform") or "").lower()
                for item in transforms
            ):
                transforms.append(
                    {
                        "source_object": anchor,
                        "forbidden_transform": "duplicate as separate master-side and reverse-side copies",
                        "reason": "overlap analyzer classified this as the same physical side-edge anchor.",
                    }
                )
    _add_direction_locks(result)
    return result


def _assertion_id(kind: EvidenceClass, wall: str, bucket: str, position: int, value: object) -> str:
    return (
        "spatial:"
        + digest_canonical({"kind": kind.value, "wall": wall, "bucket": bucket, "position": position, "value": value})[
            7:31
        ]
    )


def _evidence_detail(value: dict[str, Any]) -> CanonicalJsonObject:
    try:
        return CanonicalJsonObject.model_validate(value)
    except (ValidationError, ValueError) as exc:
        raise SpatialNormalizationError("spatial evidence contains invalid JSON") from exc


def _visible_assertion(
    item: object,
    *,
    wall: str,
    bucket: str,
    position: int,
    sources: dict[str, SpatialSourceIdentity],
) -> SpatialAssertion:
    if not isinstance(item, dict):
        raise SpatialNormalizationError("visible wall item must be an object")
    name = str(item.get("name") or "").strip()
    raw_spans = item.get("source_spans")
    if not name or not isinstance(raw_spans, list) or not raw_spans:
        raise SpatialNormalizationError("visible item requires a name and object-level source spans")
    spans: list[SpatialImageSpan] = []
    for raw_span in raw_spans:
        if not isinstance(raw_span, dict) or set(raw_span) != {"source_ref", "x0", "y0", "x1", "y1"}:
            raise SpatialNormalizationError("visible source span has an invalid shape")
        source_ref = raw_span["source_ref"]
        if not isinstance(source_ref, str) or source_ref not in sources:
            raise SpatialNormalizationError("visible source span is not in the verified source set")
        source = sources[source_ref]
        try:
            spans.append(
                SpatialImageSpan(
                    source_ref=source_ref,
                    source_digest=source.source_digest,
                    view=source.view,
                    x0=raw_span["x0"],
                    y0=raw_span["y0"],
                    x1=raw_span["x1"],
                    y1=raw_span["y1"],
                )
            )
        except ValidationError as exc:
            raise SpatialNormalizationError("visible source span is invalid") from exc
    source_view = str(item.get("source_view") or "").lower()
    span_views = {span.view for span in spans}
    if source_view == "both" and span_views != {"MASTER", "REVERSE"}:
        raise SpatialNormalizationError("shared visible anchor requires source spans from both views")
    if source_view in {"master", "reverse"} and span_views != {source_view.upper()}:
        raise SpatialNormalizationError("visible source spans disagree with the claimed source view")
    detail = _evidence_detail({**{key: value for key, value in item.items() if key != "source_spans"}, "wall": wall})
    relation = str(item.get("placement") or f"{name} on {wall} wall").strip()
    return SpatialAssertion(
        assertion_id=_assertion_id(EvidenceClass.VISIBLE, wall, bucket, position, item),
        evidence_class=EvidenceClass.VISIBLE,
        source_refs=tuple(dict.fromkeys(span.source_ref for span in spans)),
        source_spans=tuple(spans),
        evidence_detail=detail,
        relation=relation,
        subject_refs=(name,),
        confidence=None,
        warnings=(),
    )


def _claimed_sources(item: dict[str, Any], sources: dict[str, SpatialSourceIdentity]) -> tuple[str, ...]:
    claimed = item.get("source_refs", [])
    if not isinstance(claimed, list) or any(
        not isinstance(ref, str) or not ref.strip() or ref not in sources for ref in claimed
    ):
        raise SpatialNormalizationError("spatial evidence cites a source outside the verified source set")
    return tuple(dict.fromkeys(claimed))


def _inferred_assertion(
    item: object, *, wall: str, position: int, sources: dict[str, SpatialSourceIdentity]
) -> SpatialAssertion:
    if not isinstance(item, dict):
        raise SpatialNormalizationError("inferred fill requires a typed object and confidence")
    name = str(item.get("name") or "").strip()
    relation = str(item.get("relation") or "").strip()
    confidence = item.get("confidence")
    if (
        not name
        or not relation
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise SpatialNormalizationError("inferred fill requires a name, relation and bounded confidence")
    return SpatialAssertion(
        assertion_id=_assertion_id(EvidenceClass.INFERRED, wall, "inferred_fill", position, item),
        evidence_class=EvidenceClass.INFERRED,
        source_refs=_claimed_sources(item, sources),
        evidence_detail=_evidence_detail(item),
        relation=relation,
        subject_refs=(name,),
        confidence=float(confidence),
        warnings=(),
    )


def _gap_assertion(item: object, *, position: int, sources: dict[str, SpatialSourceIdentity]) -> SpatialAssertion:
    if not isinstance(item, dict) or not str(item.get("description") or "").strip():
        raise SpatialNormalizationError("coverage gap requires a description")
    return SpatialAssertion(
        assertion_id=_assertion_id(EvidenceClass.GAP, "coverage", "coverage_gaps", position, item),
        evidence_class=EvidenceClass.GAP,
        source_refs=_claimed_sources(item, sources),
        evidence_detail=_evidence_detail(item),
        relation=str(item["description"]).strip(),
        subject_refs=(),
        confidence=None,
        warnings=(),
    )


def _canonical_rows(value: object, *, field: str) -> tuple[CanonicalJsonObject, ...]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SpatialNormalizationError(f"{field} must be a list of objects")
    return tuple(_evidence_detail(item) for item in value)


def _tagged_rows(value: object, *, field: str, kind: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SpatialNormalizationError(f"{field} must be a list of objects")
    return [{**item, "kind": kind} for item in value]


def normalize_spatial_candidate(
    raw: dict[str, object],
    *,
    overlap_analysis: dict[str, object] | None,
    sources: dict[str, SpatialSourceIdentity],
    execution_id: str,
    normalizer_version: str,
) -> SpatialCandidate:
    """Build an evidence-only SpatialCandidate from a validated two-view response."""
    if not execution_id or not normalizer_version or not sources:
        raise SpatialNormalizationError("execution, normalizer and source identities are required")
    try:
        validated = _RawSpatialResponse.model_validate(raw).model_dump(mode="json")
        validated_overlap = (
            None
            if overlap_analysis is None
            else _RawOverlapAnalysis.model_validate(overlap_analysis).model_dump(mode="json")
        )
    except (ValidationError, ValueError) as exc:
        raise SpatialNormalizationError("spatial model response failed schema validation") from exc
    normalized = normalize_spatial_topology(validated, validated_overlap)
    assertions: list[SpatialAssertion] = []
    for wall_id in ("front", "back", "left", "right"):
        wall = normalized["walls"][wall_id]
        for position, item in enumerate(wall.get("must_preserve", [])):
            assertions.append(
                _visible_assertion(item, wall=wall_id, bucket="must_preserve", position=position, sources=sources)
            )
        for position, item in enumerate(wall.get("shared_overlap", [])):
            assertions.append(
                _visible_assertion(item, wall=wall_id, bucket="shared_overlap", position=position, sources=sources)
            )
        for position, item in enumerate(wall.get("inferred_fill", [])):
            assertions.append(_inferred_assertion(item, wall=wall_id, position=position, sources=sources))
    top_level_gaps = normalized.get("coverage_gaps", [])
    assessment = normalized.get("coverage_assessment")
    nested_gaps = assessment.get("coverage_gaps", []) if isinstance(assessment, dict) else []
    if top_level_gaps and nested_gaps:
        raise SpatialNormalizationError("coverage gaps have two competing locations")
    gaps = nested_gaps or top_level_gaps
    assertions.extend(_gap_assertion(item, position=position, sources=sources) for position, item in enumerate(gaps))
    if not assertions:
        raise SpatialNormalizationError("spatial candidate requires visible, inferred or gap evidence")
    seam_rows = (
        _tagged_rows(normalized["joins"], field="joins", kind="join")
        + _tagged_rows(normalized.get("must_not_transform", []), field="must_not_transform", kind="forbidden_transform")
        + _tagged_rows(
            normalized.get("overlap_merge_locks", []), field="overlap_merge_locks", kind="overlap_merge_lock"
        )
    )
    return SpatialCandidate(
        kind=ExplorationKind.SPATIAL,
        spatial=SpatialPayload(
            assertions=tuple(assertions),
            seam_locks=_canonical_rows(seam_rows, field="seam_locks"),
            direction_locks=_canonical_rows(normalized.get("direction_exclusion_locks", []), field="direction_locks"),
            duplicate_warnings=_canonical_rows(
                normalized.get("overlap_duplicate_warnings", []), field="overlap_duplicate_warnings"
            ),
            execution_id=execution_id,
            normalizer_version=normalizer_version,
        ),
    )
