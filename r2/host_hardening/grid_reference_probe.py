"""Pure extraction of declared paths from one project grid record.

This probe does not open files, decide whether paths are live, or grant H6
capture/restore authority. The caller supplies bytes read under its own fence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

type GridProbeFailureCode = Literal["INVALID_RECORD", "SCHEMA_UNSUPPORTED", "IDENTITY_MISMATCH", "LIMIT_EXCEEDED"]
type ReferenceImagesState = Literal["ABSENT", "NULL", "LIST"]

_ROOT_FIELDS = frozenset(
    {
        "id",
        "episode",
        "script_file",
        "scene_ids",
        "grid_image_path",
        "rows",
        "cols",
        "cell_count",
        "frame_chain",
        "status",
        "prompt",
        "provider",
        "model",
        "grid_size",
        "created_at",
        "error_message",
        "reference_images",
        "split_at",
        "video_aspect_ratio",
    }
)
_FRAME_FIELDS = frozenset({"index", "row", "col", "frame_type", "prev_scene_id", "next_scene_id", "image_path"})
_REFERENCE_FIELDS = frozenset({"path", "name", "ref_type"})
_STATUSES = frozenset({"pending", "generating", "completed", "failed", "splitting"})


class GridProbeError(Exception):
    """A sanitized grid record extraction failure."""

    def __init__(self, code: GridProbeFailureCode) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class GridReference:
    field_path: str
    value: str | None
    present: bool


@dataclass(frozen=True)
class GridReferenceProbe:
    grid_id: str
    status: str
    split_at: str | None
    split_at_present: bool
    frame_chain_present: bool
    reference_images_state: ReferenceImagesState
    references: tuple[GridReference, ...]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-JSON constant")


def _known_object(value: object, fields: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GridProbeError("INVALID_RECORD")
    if value.keys() - fields:
        raise GridProbeError("SCHEMA_UNSUPPORTED")
    return value


def _nullable_string(value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise GridProbeError("INVALID_RECORD")
    return value


def inspect_grid_references(payload: bytes, *, expected_grid_id: str, max_bytes: int) -> GridReferenceProbe:
    """Extract current grid path fields without interpreting their liveness.

    Absent, null and present strings are distinct. An unknown JSON key fails
    closed because this unversioned record might introduce another path field.
    The legacy ``splitting`` status and absent ``split_at`` remain raw states.
    """
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    if len(payload) > max_bytes:
        raise GridProbeError("LIMIT_EXCEEDED")
    try:
        raw = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise GridProbeError("INVALID_RECORD") from None
    record = _known_object(raw, _ROOT_FIELDS)
    grid_id = record.get("id")
    status = record.get("status")
    script_file = record.get("script_file")
    if not isinstance(grid_id, str) or not isinstance(status, str) or status not in _STATUSES:
        raise GridProbeError("INVALID_RECORD")
    if grid_id != expected_grid_id:
        raise GridProbeError("IDENTITY_MISMATCH")
    if not isinstance(script_file, str):
        raise GridProbeError("INVALID_RECORD")

    references = [GridReference("script_file", script_file, True)]
    composite_present = "grid_image_path" in record
    references.append(
        GridReference("grid_image_path", _nullable_string(record.get("grid_image_path")), composite_present)
    )

    frame_chain_present = "frame_chain" in record
    frame_chain = record.get("frame_chain", [])
    if not isinstance(frame_chain, list):
        raise GridProbeError("INVALID_RECORD")
    for index, raw_frame in enumerate(frame_chain):
        frame = _known_object(raw_frame, _FRAME_FIELDS)
        present = "image_path" in frame
        references.append(
            GridReference(f"frame_chain[{index}].image_path", _nullable_string(frame.get("image_path")), present)
        )

    reference_images_state: ReferenceImagesState = "ABSENT"
    if "reference_images" in record:
        raw_images = record["reference_images"]
        if raw_images is None:
            reference_images_state = "NULL"
        elif isinstance(raw_images, list):
            reference_images_state = "LIST"
            for index, raw_image in enumerate(raw_images):
                image = _known_object(raw_image, _REFERENCE_FIELDS)
                path = image.get("path")
                if not isinstance(path, str):
                    raise GridProbeError("INVALID_RECORD")
                references.append(GridReference(f"reference_images[{index}].path", path, True))
        else:
            raise GridProbeError("INVALID_RECORD")

    split_at_present = "split_at" in record
    split_at = _nullable_string(record.get("split_at"))
    return GridReferenceProbe(
        grid_id=grid_id,
        status=status,
        split_at=split_at,
        split_at_present=split_at_present,
        frame_chain_present=frame_chain_present,
        reference_images_state=reference_images_state,
        references=tuple(references),
    )
