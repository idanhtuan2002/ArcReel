"""Compare selected spatial normalizer behavior with one pinned DramaClaw source file."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from r2.advanced_creative.spatial import (
    SpatialNormalizationError,
    SpatialSourceIdentity,
    normalize_spatial_candidate,
    normalize_spatial_topology,
)

DONOR_SHA256 = "975e634cdd99500be5e29901da4930db14d5b81b1d14e6616e7e2e71081f1c92"
_FUNCTIONS = {
    "_tokenize_name",
    "_is_name_match",
    "_is_unique_overlap_anchor",
    "_is_side_merge_lock_anchor",
    "_unique_strings",
    "_extract_pair_names",
    "_find_representative_and_remove",
    "_append_shared_overlap",
    "_clean_shared_overlap",
    "_merge_join_values",
    "_is_direction_lock_candidate",
    "_names",
    "apply_overlap_analysis",
    "add_direction_exclusion_locks",
}
_CONSTANTS = {
    "_TOKEN_STOPWORDS",
    "_UNIQUE_ANCHOR_TOKENS",
    "_SIDE_JOIN_SURFACE_TOKENS",
    "_SIDE_JOIN_CENTER_OBJECT_MARKERS",
    "_SIDE_JOIN_SURFACE_MARKERS",
    "_SIDE_JOIN_SURFACE_UNIQUE_MARKERS",
    "_DIRECTION_LOCK_TYPES",
    "_DIRECTION_LOCK_SIZE_LOCKS",
    "_DIRECTION_LOCK_NAME_TOKENS",
}


def _donor_functions(path: Path) -> dict[str, Any]:
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != DONOR_SHA256:
        raise ValueError("donor source SHA-256 does not match the M8 pin")
    selected: list[ast.stmt] = [
        node
        for node in ast.parse(source, filename=str(path)).body
        if (isinstance(node, ast.FunctionDef) and node.name in _FUNCTIONS)
        or (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in _CONSTANTS for target in node.targets)
        )
    ]
    namespace: dict[str, Any] = {"Any": Any, "re": re}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    if not _FUNCTIONS.issubset(namespace) or not _CONSTANTS.issubset(namespace):
        raise ValueError("pinned donor normalizer symbols are incomplete")
    return namespace


def _base() -> dict[str, Any]:
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


def _cases() -> list[tuple[str, dict[str, Any], dict[str, Any] | None]]:
    left = {
        "pairs": [
            {
                "id": "left_side_join",
                "overlap_items": [{"name": "red fire extinguisher cabinet"}, {"name": "plain wall surface"}],
                "continuation_items": [],
            }
        ],
        "do_not_duplicate": ["red fire extinguisher cabinet"],
    }
    right_contract = _base()
    right_contract["walls"]["front"]["must_preserve"].append(
        {"name": "yellow menu sign", "type": "sign", "source_view": "master", "size_lock": "medium"}
    )
    right = {
        "pairs": [
            {
                "id": "right_side_join",
                "overlap_items": [{"name": "yellow menu sign"}, {"name": "plain wall surface"}],
                "continuation_items": [],
            }
        ],
        "do_not_duplicate": ["yellow menu sign"],
    }
    surface = {
        "pairs": [
            {
                "id": "left_side_join",
                "overlap_items": [{"name": "coffee table"}, {"name": "plain wall surface"}],
                "continuation_items": [],
            }
        ],
        "do_not_duplicate": [],
    }
    existing_surface_contract = _base()
    existing_surface_contract["walls"]["left"]["shared_overlap"] = [
        {"name": "plain wall surface", "source_view": "both"}
    ]
    return [
        ("left_shared_anchor", _base(), left),
        ("direction_only", _base(), None),
        ("right_shared_anchor", right_contract, right),
        ("non_anchor_continuation", _base(), surface),
        ("existing_non_anchor_surface", existing_surface_contract, left),
    ]


def _topology_without_source_spans(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _topology_without_source_spans(item) for key, item in value.items() if key != "source_spans"}
    if isinstance(value, list):
        return [_topology_without_source_spans(item) for item in value]
    return value


def _typed_surface_continuation(donor: dict[str, Any], r2: dict[str, Any]) -> bool:
    mapped = deepcopy(donor)
    inferred = mapped["walls"]["left"].pop("inferred_fill", None)
    # The donor adds an untyped prose instruction to inferred_fill; R2 inferred
    # assertions require a name, relation and confidence, so the same surfaces are
    # kept only as typed join continue_smoothly entries.
    return (
        inferred
        == [
            "Continue non-anchor overlap surfaces/materials smoothly; do not treat these as "
            "unique duplicated side anchors: plain wall surface."
        ]
        and "inferred_fill" not in r2["walls"]["left"]
        and mapped == r2
    )


def compare(donor_source: Path) -> dict[str, Any]:
    donor = _donor_functions(donor_source)
    rows: list[dict[str, Any]] = []
    for name, contract, overlap in _cases():
        donor_result = deepcopy(contract)
        if overlap is not None:
            donor["apply_overlap_analysis"](donor_result, deepcopy(overlap))
        donor["add_direction_exclusion_locks"](donor_result)
        ours = normalize_spatial_topology(contract, overlap)
        donor_selected = _topology_without_source_spans(donor_result)
        r2_selected = _topology_without_source_spans(ours)
        typed_continuation = name == "existing_non_anchor_surface" and _typed_surface_continuation(
            donor_selected, r2_selected
        )
        rows.append(
            {
                "case": name,
                "status": ("PARITY" if donor_selected == r2_selected else "IMPROVED" if typed_continuation else "DIFF"),
                "donor": donor_selected,
                "r2": r2_selected,
            }
        )
    without_spans = _base()
    donor["add_direction_exclusion_locks"](without_spans)
    donor_accepts_without_spans = bool(without_spans["direction_exclusion_locks"])
    try:
        normalize_spatial_candidate(
            _base(),
            overlap_analysis=None,
            sources={
                "master:1": SpatialSourceIdentity(source_digest="sha256:" + "a" * 64, view="MASTER"),
                "reverse:1": SpatialSourceIdentity(source_digest="sha256:" + "b" * 64, view="REVERSE"),
            },
            execution_id="parity-probe",
            normalizer_version="spatial-r2-v1",
        )
        r2_rejects_without_spans = False
    except SpatialNormalizationError:
        r2_rejects_without_spans = True
    correction = {
        "case": "visible_object_requires_source_span",
        "scope": "donor topology normalizer versus R2 candidate admission",
        "donor_accepts_without_spans": donor_accepts_without_spans,
        "r2_rejects_without_spans": r2_rejects_without_spans,
        "status": "IMPROVED" if donor_accepts_without_spans and r2_rejects_without_spans else "DIFF",
    }
    return {"donor_source_sha256": DONOR_SHA256, "cases": rows, "correction": correction}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("donor_source", type=Path)
    args = parser.parse_args()
    result = compare(args.donor_source)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return (
        0
        if all(row["status"] in {"PARITY", "IMPROVED"} for row in result["cases"])
        and result["correction"]["status"] == "IMPROVED"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
