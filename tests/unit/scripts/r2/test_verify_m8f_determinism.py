"""The M8-F determinism verifier compares everything except run-scoped fields."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.r2.verify_m8f_determinism import file_problems, stable_view

RECORD = {
    "deliverables": {"FORMAT": 2},
    "wall_seconds": 7.1,
    "digests": {
        "format": {
            "square@1": {"artifact_digest": "sha256:a", "receipt": {"receipt_id": "r-1", "result_digest": "sha256:a"}}
        },
        "spatial": {
            "constraint_set": {"constraints": [{"relation_kind": "SHARED"}], "pair_decision_digest": "sha256:p1"},
            "receipt": {"result": {"constraint_set_digest": "sha256:c1", "binding_version": 2}},
        },
    },
}


def test_run_scoped_fields_are_ignored() -> None:
    other = json.loads(json.dumps(RECORD))
    other["wall_seconds"] = 9.9
    other["digests"]["format"]["square@1"]["receipt"]["receipt_id"] = "r-2"
    other["digests"]["spatial"]["constraint_set"]["pair_decision_digest"] = "sha256:p2"
    other["digests"]["spatial"]["receipt"]["result"]["constraint_set_digest"] = "sha256:c2"

    assert stable_view(RECORD) == stable_view(other)


def test_artifact_content_differences_are_reported(tmp_path: Path) -> None:
    other = json.loads(json.dumps(RECORD))
    other["digests"]["format"]["square@1"]["artifact_digest"] = "sha256:b"
    other["digests"]["spatial"]["constraint_set"]["constraints"][0]["relation_kind"] = "PRESERVE"
    other["digests"]["spatial"]["receipt"]["result"]["binding_version"] = 3
    first, second = tmp_path / "sqlite.json", tmp_path / "pg.json"
    first.write_text(json.dumps({"cohorts": {"W": {"run_1": RECORD, "run_2": RECORD}}}), encoding="utf-8")
    second.write_text(json.dumps({"cohorts": {"W": {"run_1": other, "run_2": other}}}), encoding="utf-8")

    problems = file_problems([first, second])

    assert problems == [
        "sqlite.json vs pg.json W: .digests.format.square@1.artifact_digest",
        "sqlite.json vs pg.json W: .digests.spatial.constraint_set.constraints[0].relation_kind",
        "sqlite.json vs pg.json W: .digests.spatial.receipt.result.binding_version",
    ]


def test_a_second_run_that_differs_inside_one_file_is_reported(tmp_path: Path) -> None:
    other = json.loads(json.dumps(RECORD))
    other["deliverables"]["FORMAT"] = 1
    path = tmp_path / "sqlite.json"
    path.write_text(json.dumps({"cohorts": {"W": {"run_1": RECORD, "run_2": other}}}), encoding="utf-8")

    assert file_problems([path]) == ["sqlite.json W run 2: .deliverables.FORMAT"]
