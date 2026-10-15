"""Compare M8-F cohort runs on everything except run-scoped identities (plan F2, protocol replay_determinism).

``stable_view`` keeps the whole cohort record and removes only fields that name this run rather
than the artifact: generated ids, wall-clock times, grant events, and digests that chain over
them. Every other field (renders, reports' checks and verdicts, constraint content, sources,
promotion targets and results, learning evidence and lifts, masters) must match.

    uv run python scripts/r2/verify_m8f_determinism.py <results-a.json> <results-b.json>

compares run 1 of every cohort across two results files (for example SQLite and PostgreSQL), and
run 1 against run 2 inside each file. It exits 2 on any difference.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# (path pattern, reason). Paths use dots and ``[]`` for list items.
RUN_SCOPED: tuple[tuple[str, str], ...] = (
    (r"\.wall_seconds$|\.disk_mib$", "resource measurement, checked against the envelope instead"),
    (r"\.receipt_id$|\.report_id$|\.execution_id$", "generated per run"),
    (r"\.promoted_at$|\.expires_at$", "wall clock"),
    (r"\.grant_event_digest$", "the grant imported in this run"),
    (r"\.preview_digest$", "covers the preview id and creation time"),
    (r"\.result_master_id$", "M7 candidate id derived from the run's execution id"),
    (r"\.pair_decision$|\.pair_decision_digest$", "the pair decision carries its own id and time"),
    (r"\.frame_derivation_receipt_digest$", "the frame receipt carries its own id and time"),
    (r"\.candidate_payload_digest$", "binds the lineage, whose basis names this run's admission decision"),
    (
        r"\.receipt\.result\.(constraint_set_digest|constraint_set_id|binding_envelope_digest)$",
        "chains over the pair decision and frame receipts",
    ),
    (r"\.spatial\.receipt\.base_receipt\.result_digest$", "the binding version digest chains as above"),
    (r"\.canvas_payload_digests\[\]$|\.canvas_history\[\]\.payload_digest$", "binds the run's lineage"),
    (r"\.lineage\.content_basis_digest$", "names this run's admission decision"),
)


def _drop(value: Any, path: str, patterns: Sequence[re.Pattern[str]]) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop(item, f"{path}.{key}", patterns)
            for key, item in value.items()
            if not any(pattern.search(f"{path}.{key}") for pattern in patterns)
        }
    if isinstance(value, list):
        kept = [_drop(item, f"{path}[]", patterns) for item in value]
        return [] if any(pattern.search(f"{path}[]") for pattern in patterns) else kept
    return value


def stable_view(cohort_record: dict[str, Any]) -> dict[str, Any]:
    """The cohort record without run-scoped fields."""
    patterns = [re.compile(pattern) for pattern, _reason in RUN_SCOPED]
    return _drop(copy.deepcopy(cohort_record), "", patterns)


def differences(a: Any, b: Any, path: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for key in sorted(set(a) | set(b)) for d in differences(a.get(key), b.get(key), f"{path}.{key}")]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for index, (x, y) in enumerate(zip(a, b, strict=True)) for d in differences(x, y, f"{path}[{index}]")]
    return [] if a == b else [path or "<root>"]


def file_problems(paths: Sequence[Path]) -> list[str]:
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    problems: list[str] = []
    for path, document in zip(paths, documents, strict=True):
        for cohort, runs in document["cohorts"].items():
            if "run_2" in runs:
                run_1 = {key: runs["run_1"][key] for key in runs["run_2"]}
                problems += [
                    f"{path.name} {cohort} run 2: {d}"
                    for d in differences(stable_view(run_1), stable_view(runs["run_2"]))
                ]
    first, *rest = documents
    for path, document in zip(paths[1:], rest, strict=True):
        for cohort in sorted(set(first["cohorts"]) | set(document["cohorts"])):
            a = first["cohorts"].get(cohort, {}).get("run_1", {})
            b = document["cohorts"].get(cohort, {}).get("run_1", {})
            problems += [
                f"{paths[0].name} vs {path.name} {cohort}: {d}" for d in differences(stable_view(a), stable_view(b))
            ]
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args(argv)
    problems = file_problems(args.results)
    for problem in problems:
        print(f"M8_F_REPLAY_DIFFERS: {problem}", file=sys.stderr)
    if problems:
        return 2
    print("M8_F_DETERMINISM_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
