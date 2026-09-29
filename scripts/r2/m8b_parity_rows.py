"""Fold M8-B donor/port observations into donor parity rows (spec §11, M8-B executable plan D4).

Each harness replays the same canonical fixture cases on the donor and on the port and writes
one observation per operation. For every behavior, the fixtures tagged with it are compared
step by step:

- all steps equal: ``PARITY``;
- every unequal step lies inside a declared correction for that behavior, from its
  ``from_step`` to the end of its case: ``IMPROVED`` (a donor defect fixed, with the fixture as
  evidence);
- any other difference, or a behavior with no fixture: ``UNVERIFIED``.

``determinism`` compares two port runs. The dimensions measured elsewhere (``failure_safety``,
``observability``, ``performance``, ``resources``) are merged from ``--dimension`` files, and
default to ``UNVERIFIED``.

    uv run python scripts/r2/m8b_parity_rows.py --baseline <donor-baseline.json> \\
        --pair <name>=<fixtures.json>,<donor.json>,<port.json>,<port-rerun.json> [...] \\
        --corrections <corrections.json> [--dimension <file.json> ...] --out <rows.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from r2.contracts.advanced_creative import BehaviorParityRow, ParityDisposition

COMPARED = ("functionality", "correctness", "data_integrity")
MEASURED_ELSEWHERE = ("failure_safety", "observability", "performance", "resources")


@dataclass(frozen=True)
class HarnessRun:
    name: str
    fixtures: Mapping[str, object]
    donor: Mapping[str, list[object]]
    port: Mapping[str, list[object]]
    port_rerun: Mapping[str, list[object]]


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


def build_rows(
    baseline: Mapping[str, object],
    runs: Sequence[HarnessRun],
    corrections: Sequence[Mapping[str, object]],
    dimensions: Mapping[str, Mapping[str, str]],
) -> list[BehaviorParityRow]:
    rows: list[BehaviorParityRow] = []
    behaviors = baseline.get("behaviors")
    for item in behaviors if isinstance(behaviors, list) else []:
        behavior = str(item["behavior_id"])
        compared, determinism, refs = compare_behavior(behavior, runs, corrections)
        extra = dimensions.get(behavior, {})
        differences = [
            str(entry["description"])
            for entry in corrections
            if entry.get("behavior") == behavior and compared is ParityDisposition.IMPROVED
        ]
        values: dict[str, ParityDisposition] = dict.fromkeys(COMPARED, compared)
        values["determinism"] = determinism
        for name in MEASURED_ELSEWHERE:
            values[name] = ParityDisposition(extra.get(name, ParityDisposition.UNVERIFIED.value))
        rows.append(
            BehaviorParityRow(
                behavior_id=behavior,
                donor_test_refs=tuple(str(test) for test in item.get("donor_tests", [])),
                fixture_refs=tuple(refs),
                intentional_difference=" ".join(differences) or None,
                evidence_refs=tuple(f"fixture:{ref}" for ref in refs),
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--pair", action="append", required=True)
    parser.add_argument("--corrections", required=True)
    parser.add_argument("--dimension", action="append", default=[])
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
    rows = build_rows(
        baseline if isinstance(baseline, dict) else {}, [_pair(raw) for raw in args.pair], corrections, dimensions
    )
    Path(args.out).write_text(
        json.dumps([row.model_dump(mode="json") for row in rows], indent=2) + "\n", encoding="utf-8"
    )
    compared = {row.behavior_id: row.functionality.value for row in rows}
    print(json.dumps(compared, indent=0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
