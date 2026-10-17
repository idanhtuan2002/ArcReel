"""Pure lossless decoding of the versioned manual-import acceptance format."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from r2.contracts.opportunity import MissingReason, SourcePageResult
from r2.opportunity.errors import OpportunityError, StopCode

# A definition is executable only when the adapter knows its exact native meaning.
_FIELDS = {
    ("views", "synthetic-count.v1"): (
        "manual-public-metadata",
        "count",
        "Synthetic view count within the declared window.",
    ),
    ("excerpt", "synthetic-excerpt.v1"): ("manual-excerpt", "text", "Synthetic text supplied by the Human fixture."),
}
_BASE_FIELDS = frozenset(
    {"source_native_id", "data_class", "field_name", "definition_version", "field_definition", "unit", "window"}
)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate native JSON field")
        result[key] = value
    return result


def _nonfinite(_: str) -> object:
    raise ValueError("nonfinite native number")


def decode_manual_payload(raw: bytes) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    """Return internal native drafts; no value, category or cross-source metric is derived."""
    try:
        if len(raw) > 2_097_152:
            raise ValueError("manual page exceeds byte ceiling")
        body = json.loads(raw, object_pairs_hook=_unique, parse_float=Decimal, parse_constant=_nonfinite)
        if (
            not isinstance(body, dict)
            or set(body) != {"schema", "origin", "uploader", "records"}
            or body["schema"] != "m9.manual-fixture.v1"
        ):
            raise ValueError("unknown manual payload schema")
        if any(not isinstance(body[key], str) or not body[key].strip() for key in ("origin", "uploader")):
            raise ValueError("manual provenance is absent")
        records = body["records"]
        if not isinstance(records, list) or len(records) > 1000:
            raise ValueError("manual record envelope differs")
        result = []
        identities = set()
        for record in records:
            if not isinstance(record, dict) or set(record) not in (
                _BASE_FIELDS | {"value"},
                _BASE_FIELDS | {"missing_reason"},
            ):
                raise ValueError("unmapped or ambiguous native field")
            native_id = record["source_native_id"]
            if not isinstance(native_id, str) or not native_id.strip():
                raise ValueError("native identity is absent")
            definition = _FIELDS.get((record["field_name"], record["definition_version"]))
            if definition is None or definition != (record["data_class"], record["unit"], record["field_definition"]):
                raise ValueError("unknown native definition or unit")
            window = record["window"]
            starts = ends = None
            if window is not None:
                if not isinstance(window, dict) or set(window) != {"starts_at", "ends_at"}:
                    raise ValueError("native window is ambiguous")
                starts, ends = window["starts_at"], window["ends_at"]
                a, b = datetime.fromisoformat(starts), datetime.fromisoformat(ends)
                if a.tzinfo is None or b.tzinfo is None or b < a:
                    raise ValueError("native window is unordered or naive")
            identity = (native_id, record["field_name"], record["definition_version"], starts, ends)
            if identity in identities:
                raise ValueError("ambiguous repeated native field")
            identities.add(identity)
            row = {
                "source_native_id": native_id,
                "native_field_name": record["field_name"],
                "native_field_definition": record["field_definition"],
                "native_field_version": record["definition_version"],
                "data_class": record["data_class"],
                "unit": record["unit"],
                "window_start": starts,
                "window_end": ends,
                "missing_reason": None,
                "normalization_version": "manual-import.v1",
            }
            if "value" in record:
                value = record["value"]
                if record["field_name"] == "views" and (type(value) is not int or value < 0):
                    raise ValueError("native count cannot be coerced")
                if record["field_name"] == "excerpt" and not isinstance(value, str):
                    raise ValueError("native text cannot be coerced")
                row["value"] = value
            else:
                row["missing_reason"] = MissingReason(record["missing_reason"]).value
            result.append(row)
        return body, tuple(result)
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise OpportunityError(StopCode.M9_NORMALIZATION_LOSSY) from None


def normalize_manual_page(page: SourcePageResult) -> tuple[dict[str, object], ...]:
    _, rows = decode_manual_payload(page.raw_payload)
    identities = {row["source_native_id"] for row in rows}
    classes = {row["data_class"] for row in rows}
    if (
        page.raw_media_type != "application/json"
        or page.returned_record_count != len(rows)
        or set(page.source_native_ids) != identities
        or (rows and set(page.data_classes) != classes)
    ):
        raise OpportunityError(StopCode.M9_NORMALIZATION_LOSSY)
    return rows
