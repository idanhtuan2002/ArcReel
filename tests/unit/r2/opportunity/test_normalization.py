from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from r2.contracts.opportunity import SourcePageResult
from r2.opportunity.errors import OpportunityError

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/r2/opportunity/manual_import.json"


def normalize(page):
    assert importlib.util.find_spec("r2.opportunity.normalization") is not None, "B4 lossless normalizer is missing"
    return importlib.import_module("r2.opportunity.normalization").normalize_manual_page(page)


def page(payload=None):
    raw = FIXTURE.read_bytes() if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    return SourcePageResult(
        provider_request_id="synthetic-upload",
        next_cursor=None,
        raw_payload=raw,
        raw_media_type="application/json",
        source_native_ids=("synthetic-metric-001", "synthetic-text-001"),
        data_classes=("manual-public-metadata", "manual-excerpt"),
        returned_record_count=2,
        quota_units_observed=0,
        provider_observed_at=None,
        terminal_page=True,
    )


def test_native_values_definitions_units_and_windows_are_preserved():
    rows = normalize(page())
    assert len(rows) == 2
    assert rows[0]["source_native_id"] == "synthetic-metric-001"
    assert rows[0]["native_field_name"] == "views"
    assert rows[0]["native_field_definition"] == "Synthetic view count within the declared window."
    assert rows[0]["native_field_version"] == "synthetic-count.v1"
    assert rows[0]["value"] == 125
    assert rows[0]["unit"] == "count"
    assert rows[0]["window_start"] == "2026-10-15T00:00:00Z"
    assert rows[0]["window_end"] == "2026-10-16T00:00:00Z"
    assert rows[1]["value"] == "Entirely synthetic fixture text."
    assert rows[1]["data_class"] == "manual-excerpt"
    assert rows[1]["window_start"] is None


@pytest.mark.parametrize(
    "fault",
    [
        "unknown_definition",
        "unit",
        "extra_field",
        "missing_field",
        "nonfinite",
        "native_id",
        "classes",
        "count",
        "window",
        "wrong_schema",
        "duplicate_record",
    ],
)
def test_ambiguous_or_untraceable_native_fields_are_refused(fault):
    body = json.loads(FIXTURE.read_bytes())
    if fault == "unknown_definition":
        body["records"][0]["definition_version"] = "unknown.v7"
    elif fault == "unit":
        body["records"][0]["unit"] = "seconds"
    elif fault == "extra_field":
        body["records"][0]["unmapped_native_field"] = 42
    elif fault == "missing_field":
        body["records"][0].pop("field_definition")
    elif fault == "nonfinite":
        body["records"][0]["value"] = float("nan")
    elif fault == "native_id":
        body["records"][0]["source_native_id"] = "another-id"
    elif fault == "window":
        body["records"][0]["window"]["ends_at"] = "2026-10-14T00:00:00Z"
    elif fault == "wrong_schema":
        body["schema"] = "unknown.v1"
    elif fault == "duplicate_record":
        body["records"][1] = body["records"][0]
    candidate = page(body)
    if fault == "classes":
        candidate = candidate.model_copy(update={"data_classes": ("manual-excerpt",)})
    elif fault == "count":
        candidate = candidate.model_copy(update={"returned_record_count": 1})
    with pytest.raises(OpportunityError, match="M9_NORMALIZATION_LOSSY"):
        normalize(candidate)


def test_duplicate_json_keys_are_not_silently_overwritten():
    candidate = page().model_copy(
        update={
            "raw_payload": b'{"schema":"first","schema":"m9.manual-fixture.v1","origin":"x","uploader":"x","records":[]}'
        }
    )
    with pytest.raises(OpportunityError, match="M9_NORMALIZATION_LOSSY"):
        normalize(candidate)


def test_zero_and_explicit_missingness_remain_distinct():
    body = json.loads(FIXTURE.read_bytes())
    body["records"][0]["value"] = 0
    assert normalize(page(body))[0]["value"] == 0
    body["records"][0].pop("value")
    body["records"][0]["missing_reason"] = "NOT_RETURNED"
    row = normalize(page(body))[0]
    assert "value" not in row
    assert row["missing_reason"] == "NOT_RETURNED"
