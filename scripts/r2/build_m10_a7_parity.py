"""Build the M10-A7 Kalinga DonorParityReport from the frozen baseline and the recorded same-fixture results.

The verdict is recomputed with `evaluate_quality_parity`; the report's own verdict field is only a copy of it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BASELINE = "docs/r2/evidence/R2_M10_A7_KALINGA_BASELINE.json"
TESTS = "tests/integration/server/services/test_quality_kalinga_parity.py"
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
# Per frozen criterion; evidence names the test that decides each row.
ASSESSMENT: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "missing_master": ((P, P, P, IM, IM, IM, P, P), ("test_missing_master_is_refused_before_any_probe",)),
    "audio_stream_required": (
        (P, P, IM, P, IM, IM, P, IM),
        (
            "test_audio_stream_requirement_matches_the_donor",
            "test_measurements_are_digest_deterministic[CONTAINER_STREAM-None]",
            "test_bounded_probes_stay_within_the_frozen_performance_rule[CONTAINER_STREAM-None]",
        ),
    ),
    "loudness_sanity": (
        (P, P, IM, P, IM, IM, P, IM),
        (
            "test_sane_loudness_passes_in_both",
            "test_silent_audio_fails_in_both_and_inapplicability_is_explicit",
            "test_measurements_are_digest_deterministic[LOUDNESS-None]",
            "test_bounded_probes_stay_within_the_frozen_performance_rule[LOUDNESS-None]",
        ),
    ),
    "caption_timing_present": (
        (P, IM, IM, IM, IM, IM, P, IM),
        (
            "test_caption_timing_present_passes_in_both",
            "test_caption_without_any_timing_is_detected_by_both",
            "test_sparse_caption_timing_passes_the_donor_but_fails_coverage",
            "test_missing_caption_evidence_is_skipped_by_the_donor_but_refused",
            "test_measurements_are_digest_deterministic[CAPTIONS-good.srt]",
            "test_bounded_probes_stay_within_the_frozen_performance_rule[CAPTIONS-good.srt]",
        ),
    ),
    "advisory_failure_never_ready": (
        (P, IM, P, IM, P, P, P, P),
        ("test_advisory_or_missing_gates_never_pass_or_become_ready",),
    ),
    # A failed probe carries the bounded launch's ResourceEvidence on the raised typed error.
    "tool_failure_typed": (
        (IM, IM, P, IM, P, IM, P, IM),
        ("test_truncated_or_unqualified_media_is_a_typed_probe_failure",),
    ),
}
UNKNOWNS: dict[str, str] = {}


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def build(root: Path, integrated_head: str, results: dict[str, Any]) -> dict[str, Any]:
    baseline = json.loads((root / BASELINE).read_text("utf-8"))
    donor = baseline["donor"]
    functions = json.loads((root / "tests/fixtures/r2/m10_kalinga/donor_functions.json").read_text("utf-8"))
    rows = []
    for frozen in baseline["rows"]:
        refs = tuple(f"{TESTS}::{name}" for name in ASSESSMENT.get(frozen["behavior_id"], ((), ()))[1])
        if frozen["intentional_difference"] is not None:
            values = ("EXCLUDED",) * len(DIMENSIONS)
        else:
            values = ASSESSMENT[frozen["behavior_id"]][0]
        rows.append(
            {
                "behavior_id": frozen["behavior_id"],
                "donor_test_refs": frozen["donor_refs"],
                "fixture_refs": frozen["fixture_refs"],
                "intentional_difference": frozen["intentional_difference"],
                **dict(zip(DIMENSIONS, values, strict=True)),
                "evidence_refs": list(refs),
            }
        )
    report = {
        "contract_version": "1",
        "donor": {
            "repository_url": donor["repository_url"],
            "commit_sha": donor["commit_sha"],
            "selected_paths": donor["selected_paths"],
            "reachable_surface_digest": _digest([(f["path"], f["name"], f["sha256"]) for f in functions["functions"]]),
            "runtime_identity": donor["runtime_identity"],
            "behavior_inventory_digest": _digest(baseline["rows"]),
            "donor_test_inventory_digest": _digest(
                sorted({ref for row in baseline["rows"] for ref in row["donor_refs"]})
            ),
            "fixture_set_digest": _digest(baseline["fixtures_sha256"]),
        },
        "integrated_head": integrated_head,
        "rows": rows,
        "commands": [results],
        "required_skips": [],
        "material_unknowns": sorted(f"{key}: {why}" for key, why in UNKNOWNS.items()),
        "reviewer": "Claude Opus 5.5 main agent (recomputed fold; not an independent acceptance)",
        "verdict": "PASS",
    }
    from r2.contracts.advanced_creative import DonorParityReport
    from r2.quality.parity import evaluate_quality_parity

    report["verdict"] = evaluate_quality_parity(DonorParityReport.model_validate(report), integrated_head).value
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--head", required=True)
    parser.add_argument("--results", type=Path, required=True, help="JSON object: command, result, timings")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo.resolve()
    sys.path.insert(0, str(root))
    results = json.loads(args.results.read_text("utf-8"))
    report = build(root, args.head, results)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(report["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
