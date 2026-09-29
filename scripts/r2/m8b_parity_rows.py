"""Fold M8-B donor/port observations into donor parity rows (spec §11, M8-B executable plan D4).

Each harness replays the same canonical fixture cases on the donor and on the port and writes
one observation per operation. For every behavior, the fixtures tagged with it are compared
step by step:

- all steps equal: ``PARITY``;
- every unequal step lies inside a declared correction for that behavior, from its
  ``from_step`` to the end of its case: ``IMPROVED`` (a donor defect fixed, with the fixture as
  evidence);
- any other difference, or a behavior with no fixture: ``UNVERIFIED``.

``observability`` is compared like ``functionality``: the observations are the behavior's
externally observable surface (return values, stored drafts, save status, released waiters).
``failure_safety`` takes the compared disposition only for a behavior with at least one fixture
case tagged ``"evidences": ["failure_safety"]`` (a failure path: invalid input, a rejected or
failed save, a corrupt draft, a full quota); otherwise it is ``UNVERIFIED``. ``determinism``
compares two port runs.

``performance`` and ``resources`` come from ``--timing`` files: both sides measure every case of
a harness with the same runner (tools/parity/dramaclaw/timingRunner.ts). Per case, the port's
median time must be at most ``PERF_RATIO`` times the donor's plus ``PERF_SLACK_MS``
(``IMPROVED`` when every case is at most ``PERF_FASTER`` times the donor's). For resources, the
heap the case retains after garbage collection must be at most ``HEAP_RATIO`` times the donor's
plus ``HEAP_SLACK_BYTES``, and the localStorage bytes it leaves at most ``STORAGE_RATIO`` times
the donor's plus ``STORAGE_SLACK_BYTES``; an unmeasured heap is ``UNVERIFIED``. The absolute
slacks keep microsecond-, few-kilobyte- and few-byte cases from failing on a ratio alone. A
behavior with an unmeasured case is ``UNVERIFIED``.
``--dimension`` files override any dimension for a behavior.

    uv run python scripts/r2/m8b_parity_rows.py --baseline <donor-baseline.json> \\
        --pair <name>=<fixtures.json>,<donor.json>,<port.json>,<port-rerun.json> [...] \\
        --timing <name>=<donor.timing.json>,<port.timing.json> [...] \\
        --corrections <corrections.json> [--dimension <file.json> ...] --out <rows.json> \\
        [--report-out <report.json> --head <sha> --reviewer <name> --command <json> ...]

With ``--report-out``, the rows are also assembled into a ``DonorParityReport``: the donor
surface from the baseline, the digest of the fixture set (every ``--pair`` fixture file and the
corrections file), the integrated HEAD, the commands run, and the verdict recomputed with
``evaluate_parity``; no required skip or material unknown is declared.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from r2.advanced_creative.digests import digest_canonical
from r2.advanced_creative.parity import evaluate_parity
from r2.contracts.advanced_creative import BehaviorParityRow, DonorParityReport, ParityDisposition, ParityVerdict

COMPARED = ("functionality", "correctness", "data_integrity", "observability")
PERF_RATIO = 1.5
PERF_SLACK_MS = 0.05
PERF_FASTER = 0.67
HEAP_RATIO = 1.5
HEAP_SLACK_BYTES = 64 * 1024
STORAGE_RATIO = 1.1
STORAGE_SLACK_BYTES = 64


@dataclass(frozen=True)
class HarnessRun:
    name: str
    fixtures: Mapping[str, object]
    donor: Mapping[str, list[object]]
    port: Mapping[str, list[object]]
    port_rerun: Mapping[str, list[object]]


@dataclass(frozen=True)
class TimingRun:
    name: str
    donor: Mapping[str, Mapping[str, float | None]]
    port: Mapping[str, Mapping[str, float | None]]


def _cases(run: HarnessRun) -> list[Mapping[str, object]]:
    cases = run.fixtures.get("cases")
    return list(cases) if isinstance(cases, list) else []


def _declared(corrections: Sequence[Mapping[str, object]], harness: str, case: str, behavior: str) -> int | None:
    for item in corrections:
        if item.get("harness") == harness and item.get("case") == case and item.get("behavior") == behavior:
            step = item.get("from_step")
            return step if isinstance(step, int) else None
    return None


def compare_behavior(
    behavior: str, runs: Sequence[HarnessRun], corrections: Sequence[Mapping[str, object]]
) -> tuple[ParityDisposition, ParityDisposition, list[str]]:
    """The compared-dimension disposition, the determinism disposition, and the fixture refs."""
    refs: list[str] = []
    improved = False
    deterministic = True
    for run in runs:
        for case in _cases(run):
            behaviors = case.get("behaviors")
            if not isinstance(behaviors, list) or behavior not in behaviors:
                continue
            case_id = str(case["id"])
            refs.append(f"{run.name}:{case_id}")
            donor, port = run.donor.get(case_id), run.port.get(case_id)
            if donor is None or port is None or len(donor) != len(port):
                return ParityDisposition.UNVERIFIED, ParityDisposition.UNVERIFIED, refs
            if run.port_rerun.get(case_id) != port:
                deterministic = False
            first_difference = next(
                (index for index, (a, b) in enumerate(zip(donor, port, strict=True)) if a != b), None
            )
            if first_difference is None:
                continue
            declared = _declared(corrections, run.name, case_id, behavior)
            if declared is None or first_difference < declared:
                return ParityDisposition.UNVERIFIED, ParityDisposition.UNVERIFIED, refs
            improved = True
    if not refs:
        return ParityDisposition.UNVERIFIED, ParityDisposition.UNVERIFIED, refs
    compared = ParityDisposition.IMPROVED if improved else ParityDisposition.PARITY
    determinism = ParityDisposition.PARITY if deterministic else ParityDisposition.UNVERIFIED
    return compared, determinism, refs


def _behavior_cases(behavior: str, runs: Sequence[HarnessRun]) -> list[tuple[str, Mapping[str, object]]]:
    return [
        (run.name, case)
        for run in runs
        for case in _cases(run)
        if isinstance(case.get("behaviors"), list) and behavior in case["behaviors"]
    ]


def failure_safety(behavior: str, runs: Sequence[HarnessRun], compared: ParityDisposition) -> ParityDisposition:
    """The compared disposition when a tagged failure-path case covers the behavior."""
    tagged = any(
        isinstance(case.get("evidences"), list) and "failure_safety" in case["evidences"]
        for _, case in _behavior_cases(behavior, runs)
    )
    return compared if tagged else ParityDisposition.UNVERIFIED


def measure_behavior(
    behavior: str, runs: Sequence[HarnessRun], timings: Mapping[str, TimingRun]
) -> tuple[ParityDisposition, ParityDisposition, list[str]]:
    """The performance and resources dispositions from both sides' case timings, and the refs."""
    cases = _behavior_cases(behavior, runs)
    refs: list[str] = []
    faster = True
    for harness, case in cases:
        case_id = str(case["id"])
        timing = timings.get(harness)
        donor = timing.donor.get(case_id) if timing else None
        port = timing.port.get(case_id) if timing else None
        if donor is None or port is None:
            return ParityDisposition.UNVERIFIED, ParityDisposition.UNVERIFIED, refs
        refs.append(f"timing:{harness}:{case_id}")
        donor_ms, port_ms = float(donor["median_ms"]), float(port["median_ms"])
        if port_ms > donor_ms * PERF_RATIO + PERF_SLACK_MS:
            return ParityDisposition.UNVERIFIED, ParityDisposition.UNVERIFIED, refs
        donor_heap, port_heap = donor.get("retained_heap_bytes"), port.get("retained_heap_bytes")
        if donor_heap is None or port_heap is None or port_heap > donor_heap * HEAP_RATIO + HEAP_SLACK_BYTES:
            return ParityDisposition.UNVERIFIED, ParityDisposition.UNVERIFIED, refs
        if port["storage_bytes"] > donor["storage_bytes"] * STORAGE_RATIO + STORAGE_SLACK_BYTES:
            return ParityDisposition.UNVERIFIED, ParityDisposition.UNVERIFIED, refs
        faster = faster and port_ms <= donor_ms * PERF_FASTER and donor_ms - port_ms > PERF_SLACK_MS
    if not cases:
        return ParityDisposition.UNVERIFIED, ParityDisposition.UNVERIFIED, refs
    performance = ParityDisposition.IMPROVED if faster else ParityDisposition.PARITY
    return performance, ParityDisposition.PARITY, refs


def build_rows(
    baseline: Mapping[str, object],
    runs: Sequence[HarnessRun],
    corrections: Sequence[Mapping[str, object]],
    dimensions: Mapping[str, Mapping[str, str]],
    timings: Mapping[str, TimingRun] | None = None,
) -> list[BehaviorParityRow]:
    rows: list[BehaviorParityRow] = []
    behaviors = baseline.get("behaviors")
    for item in behaviors if isinstance(behaviors, list) else []:
        behavior = str(item["behavior_id"])
        compared, determinism, refs = compare_behavior(behavior, runs, corrections)
        performance, resources, timing_refs = measure_behavior(behavior, runs, timings or {})
        extra = dimensions.get(behavior, {})
        differences = [
            str(entry["description"])
            for entry in corrections
            if entry.get("behavior") == behavior and compared is ParityDisposition.IMPROVED
        ]
        values: dict[str, ParityDisposition] = dict.fromkeys(COMPARED, compared)
        values["determinism"] = determinism
        values["failure_safety"] = failure_safety(behavior, runs, compared)
        values["performance"] = performance
        values["resources"] = resources
        for name, value in extra.items():
            values[name] = ParityDisposition(value)
        rows.append(
            BehaviorParityRow(
                behavior_id=behavior,
                donor_test_refs=tuple(str(test) for test in item.get("donor_tests", [])),
                fixture_refs=tuple(refs),
                intentional_difference=" ".join(differences) or None,
                evidence_refs=(*(f"fixture:{ref}" for ref in refs), *timing_refs),
                **values,
            )
        )
    return rows


def _load(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _results(path: str) -> Mapping[str, list[object]]:
    document = _load(path)
    results = document.get("results") if isinstance(document, dict) else None
    return results if isinstance(results, dict) else {}


def _pair(raw: str) -> HarnessRun:
    name, _, files = raw.partition("=")
    fixtures, donor, port, rerun = files.split(",")
    loaded = _load(fixtures)
    return HarnessRun(
        name=name,
        fixtures=loaded if isinstance(loaded, dict) else {},
        donor=_results(donor),
        port=_results(port),
        port_rerun=_results(rerun),
    )


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _sha256(path: str) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_report(
    baseline: Mapping[str, object],
    rows: Sequence[BehaviorParityRow],
    fixture_files: Sequence[str],
    head: str,
    reviewer: str,
    commands: Sequence[Mapping[str, object]],
) -> DonorParityReport:
    donor = baseline.get("donor")
    donor = donor if isinstance(donor, dict) else {}
    draft = DonorParityReport.model_validate(
        {
            "contract_version": "1",
            "donor": {
                "repository_url": donor.get("repository_url"),
                "commit_sha": donor.get("commit"),
                "selected_paths": [
                    item["path"] if isinstance(item, dict) else item for item in _list(baseline.get("selected_paths"))
                ],
                "reachable_surface_digest": baseline.get("reachable_surface_digest"),
                "runtime_identity": baseline.get("runtime_identity"),
                "behavior_inventory_digest": baseline.get("behavior_inventory_digest"),
                "donor_test_inventory_digest": baseline.get("donor_test_inventory_digest"),
                "fixture_set_digest": digest_canonical({path: _sha256(path) for path in fixture_files}),
            },
            "integrated_head": head,
            "rows": [row.model_dump(mode="json") for row in rows],
            "commands": list(commands),
            "required_skips": [],
            "material_unknowns": [],
            "reviewer": reviewer,
            "verdict": ParityVerdict.BLOCKED.value,
        }
    )
    return draft.model_copy(update={"verdict": evaluate_parity(draft, head)})


def _timing(raw: str) -> TimingRun:
    name, _, files = raw.partition("=")
    donor, port = files.split(",")
    donor_doc, port_doc = _load(donor), _load(port)
    return TimingRun(
        name=name,
        donor=donor_doc if isinstance(donor_doc, dict) else {},
        port=port_doc if isinstance(port_doc, dict) else {},
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--pair", action="append", required=True)
    parser.add_argument("--corrections", required=True)
    parser.add_argument("--dimension", action="append", default=[])
    parser.add_argument("--timing", action="append", default=[])
    parser.add_argument("--report-out")
    parser.add_argument("--head")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--command", action="append", default=[], help="one JSON object per command run")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    baseline = _load(args.baseline)
    corrections_doc = _load(args.corrections)
    corrections = corrections_doc.get("corrections", []) if isinstance(corrections_doc, dict) else []
    dimensions: dict[str, dict[str, str]] = {}
    for path in args.dimension:
        document = _load(path)
        for behavior, values in (document.get("rows", {}) if isinstance(document, dict) else {}).items():
            dimensions.setdefault(behavior, {}).update(values)
    timings = {run.name: run for run in (_timing(raw) for raw in args.timing)}
    rows = build_rows(
        baseline if isinstance(baseline, dict) else {},
        [_pair(raw) for raw in args.pair],
        corrections,
        dimensions,
        timings,
    )
    Path(args.out).write_text(
        json.dumps([row.model_dump(mode="json") for row in rows], indent=2) + "\n", encoding="utf-8"
    )
    if args.report_out:
        if not args.head:
            parser.error("--report-out needs --head")
        fixture_files = [raw.partition("=")[2].split(",")[0] for raw in args.pair] + [args.corrections]
        report = build_report(
            baseline if isinstance(baseline, dict) else {},
            rows,
            fixture_files,
            args.head,
            args.reviewer,
            [json.loads(raw) for raw in args.command],
        )
        Path(args.report_out).write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
        print(f"verdict: {report.verdict.value}")
    compared = {row.behavior_id: row.functionality.value for row in rows}
    print(json.dumps(compared, indent=0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
