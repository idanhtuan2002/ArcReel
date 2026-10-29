"""Build the M10-B6 donor parity reports (Kalinga seo_lint, OpenMontage ExportBundle) from the frozen baseline.

Each verdict is recomputed with `evaluate_quality_parity`; the report's own verdict field is only a copy of it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BASELINE = "docs/r2/evidence/R2_M10_B6_DONOR_BASELINE.json"
TESTS = "tests/integration/server/services/test_packaging_donor_parity.py"
# OpenMontage's `schemas.artifacts` validator and publish_log schema, pinned at the donor commit and run in-test.
SCHEMA_FIXTURE = "tests/fixtures/r2/m10_b6_donors/openmontage_schema.json"
P, IM = "PARITY", "IMPROVED"
DIMENSIONS = (
    "functionality",
    "correctness",
    "determinism",
    "failure_safety",
    "data_integrity",
    "observability",
    "performance",
    "resources",
)
# Pure text rules over identical inputs: data_integrity PARITY by the frozen criterion; typed codes improve observability.
_SEO = (P, P, P, P, P, IM, P, P)
_SEO_TESTS = (
    "test_every_donor_seo_finding_is_detected_by_its_m10_rule[{}]",
    "test_the_m10_check_stays_within_the_frozen_performance_rule",
)
# Per frozen criterion; evidence names the tests that decide each row.
ASSESSMENT: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    **{
        behavior: (
            _SEO,
            (_SEO_TESTS[0].format(behavior), _SEO_TESTS[1], "test_a_clean_package_passes_both_the_donor_and_m10"),
        )
        for behavior in (
            "kalinga_title_length",
            "kalinga_title_terms",
            "kalinga_description_terms",
            "kalinga_plain_text",
            "kalinga_description_min",
            "kalinga_hashtag_count",
            "kalinga_tag_min",
        )
    },
    # Both refuse a package without metadata (failure_safety PARITY); M10 refuses it structurally with a typed error.
    "kalinga_metadata_missing": (
        (P, P, P, P, P, IM, P, P),
        ("test_missing_metadata_is_a_donor_issue_and_cannot_even_be_constructed_in_m10",),
    ),
    "openmontage_missing_video": (
        (P, P, P, P, IM, IM, P, P),
        ("test_a_missing_video_is_refused_by_both",),
    ),
    "openmontage_missing_optional_asset": (
        (P, P, P, P, IM, IM, P, P),
        ("test_a_declared_optional_asset_that_is_missing_is_refused_by_both",),
    ),
    "openmontage_layout": (
        (P, P, IM, P, IM, P, P, IM),
        (
            "test_one_case_exports_the_same_member_bytes_and_metadata_values",
            "test_a_publish_log_rejected_by_the_donor_schema_writes_a_partial_bundle",
            "test_the_confined_export_stays_within_the_frozen_performance_rule",
        ),
    ),
    "openmontage_determinism": (
        (P, P, IM, P, IM, P, P, IM),
        (
            "test_the_donor_bundle_is_not_byte_stable_and_the_m10_archive_is",
            "test_the_confined_export_stays_within_the_frozen_performance_rule",
        ),
    ),
    "openmontage_no_upload": (
        (P, P, P, P, P, IM, P, IM),
        (
            "test_both_export_locally_without_uploading",
            "test_the_confined_export_stays_within_the_frozen_performance_rule",
        ),
    ),
    "openmontage_metadata_document": (
        (P, P, IM, P, IM, P, P, P),
        (
            "test_one_case_exports_the_same_member_bytes_and_metadata_values",
            "test_a_corrupted_metadata_value_would_be_detected_by_this_comparison",
        ),
    ),
}


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def build(root: Path, integrated_head: str, results: dict[str, Any]) -> dict[str, Any]:
    from r2.contracts.advanced_creative import DonorParityReport
    from r2.quality.parity import evaluate_quality_parity

    baseline = json.loads((root / BASELINE).read_text("utf-8"))
    functions = json.loads((root / baseline["donor_fixture"]["path"]).read_text("utf-8"))
    reports: dict[str, Any] = {}
    for key, donor in baseline["donors"].items():
        frozen_rows = [row for row in baseline["rows"] if row["donor"] == key]
        extra_fixtures = [] if key != "openmontage" else [f"{SCHEMA_FIXTURE}@{_file_digest(root / SCHEMA_FIXTURE)}"]
        rows = []
        for frozen in frozen_rows:
            excluded = not frozen["measured"]
            values, tests = (("EXCLUDED",) * len(DIMENSIONS), ()) if excluded else ASSESSMENT[frozen["behavior_id"]]
            rows.append(
                {
                    "behavior_id": frozen["behavior_id"],
                    "donor_test_refs": frozen["donor_test_refs"],
                    "fixture_refs": [baseline["fixtures"], *extra_fixtures],
                    "intentional_difference": frozen.get("intentional_difference"),
                    **dict(zip(DIMENSIONS, values, strict=True)),
                    "evidence_refs": [f"{TESTS}::{name}" for name in tests],
                }
            )
        pinned = functions["donors"][key]
        report = {
            "contract_version": "1",
            "donor": {
                "repository_url": donor["repository_url"],
                "commit_sha": donor["commit_sha"],
                "selected_paths": sorted(donor["blob_sha256"]),
                "reachable_surface_digest": _digest([(f["path"], f["name"], f["sha256"]) for f in pinned["functions"]]),
                "runtime_identity": baseline["runtime_identity"],
                "behavior_inventory_digest": _digest(frozen_rows),
                "donor_test_inventory_digest": _digest(
                    sorted({ref for row in frozen_rows for ref in row["donor_test_refs"]})
                ),
                "fixture_set_digest": _digest(baseline["donor_fixture"]),
            },
            "integrated_head": integrated_head,
            "rows": rows,
            "commands": [results],
            "required_skips": [],
            "material_unknowns": [],
            "reviewer": "Claude Opus 5.5 main agent (recomputed fold; not an independent acceptance)",
            "verdict": "PASS",
        }
        report["verdict"] = evaluate_quality_parity(DonorParityReport.model_validate(report), integrated_head).value
        reports[key] = report
    return {"schema_id": "m10.b6-donor-parity.v1", "baseline": BASELINE, "reports": reports}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--head", required=True)
    parser.add_argument("--results", type=Path, required=True, help="JSON object: command, result, timings")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo.resolve()
    sys.path.insert(0, str(root))
    body = build(root, args.head, json.loads(args.results.read_text("utf-8")))
    args.out.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print({key: report["verdict"] for key, report in body["reports"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
