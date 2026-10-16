"""M9's report verifier binds selected file bytes as well as measured results."""

import hashlib
import json

import pytest

from r2.advanced_creative.digests import digest_canonical
from scripts.r2.verify_m9_parity import verify_m9_parity

HEAD = "a" * 40
PIN = "08e2151fa02de28a5d6a312b3d575692bf147ad7"
H = "sha256:" + "a" * 64
PATHS = (
    "skills/pipelines/explainer/research-director.md",
    "schemas/artifacts/research_brief.schema.json",
    "schemas/artifacts/decision_log.schema.json",
)


def report_fixture() -> tuple[dict, dict[str, str]]:
    hashes: dict[str, str] = dict.fromkeys(PATHS, H)
    dimensions = (
        "functionality",
        "correctness",
        "determinism",
        "failure_safety",
        "data_integrity",
        "observability",
        "performance",
        "resources",
    )
    body = {
        "contract_version": "1",
        "donor": {
            "repository_url": "https://github.com/calesthio/OpenMontage",
            "commit_sha": PIN,
            "selected_paths": PATHS,
            "reachable_surface_digest": digest_canonical(hashes),
            "runtime_identity": "fixture",
            "behavior_inventory_digest": H,
            "donor_test_inventory_digest": H,
            "fixture_set_digest": H,
        },
        "integrated_head": HEAD,
        "rows": [
            {
                "behavior_id": "research",
                "donor_test_refs": ["test:research"],
                "fixture_refs": ["fixture:research"],
                "intentional_difference": None,
                **dict.fromkeys(dimensions, "PARITY"),
                "evidence_refs": ["proof:research"],
            }
        ],
        "commands": [
            {
                "evidence_ref": "proof:research",
                "behavior_id": "research",
                "fixture_ref": "fixture:research",
                "donor_commit": PIN,
                "integrated_head": HEAD,
                "donor_exit_code": 0,
                "r2_exit_code": 0,
                "applicable": True,
                "dimensions": [
                    {"dimension": dimension, "comparison": "EQUAL", "donor": 1, "r2": 1} for dimension in dimensions
                ],
            }
        ],
        "required_skips": [],
        "material_unknowns": [],
        "reviewer": "pending",
        "verdict": "PASS",
    }
    body["commands"].append(
        {
            "kind": "INVENTORY",
            "behavior_ids": ["research"],
            "donor_test_refs": ["test:research"],
            "fixture_refs": ["fixture:research"],
        }
    )
    body["donor"]["behavior_inventory_digest"] = digest_canonical(["research"])
    body["donor"]["donor_test_inventory_digest"] = digest_canonical(["test:research"])
    body["donor"]["fixture_set_digest"] = digest_canonical(["fixture:research"])
    return body, hashes


def test_verifier_accepts_exact_bytes_and_refuses_changed_or_missing_blob(monkeypatch):
    body, hashes = report_fixture()
    install_fixture_harness(body, monkeypatch)
    assert verify_m9_parity(body, HEAD, hashes, execution_fixture(body)) == []
    assert verify_m9_parity(body, HEAD, {**hashes, PATHS[0]: "sha256:" + "b" * 64})
    assert verify_m9_parity(body, HEAD, {path: value for path, value in hashes.items() if path != PATHS[0]})


def test_verifier_refuses_forged_measurement_and_malformed_report():
    body, hashes = report_fixture()
    body["commands"] = []
    assert verify_m9_parity(body, HEAD, hashes)
    assert verify_m9_parity({"verdict": "PASS"}, HEAD, {})


def test_declared_comparison_scalars_without_retained_execution_bytes_are_not_parity():
    body, hashes = report_fixture()
    assert verify_m9_parity(body, HEAD, hashes)


def execution_fixture(body):
    comparison = body["commands"][0]
    fixture = b"one shared immutable test input"
    fixture_sha = hashlib.sha256(fixture).hexdigest()
    blobs = {"fixture.json": fixture}
    outputs = {}
    for side, commit in (("donor", body["donor"]["commit_sha"]), ("r2", body["integrated_head"])):
        path = side + ".json"
        blobs[path] = json.dumps(
            {
                "behavior_id": comparison["behavior_id"],
                "fixture_sha256": fixture_sha,
                "dimensions": {row["dimension"]: row[side] for row in comparison["dimensions"]},
            }
        ).encode()
        outputs[side] = {
            "argv": [side, "--fixture", "fixture.json"],
            "source_commit": commit,
            "exit_code": comparison[side + "_exit_code"],
            "stdout": {"path": path, "sha256": hashlib.sha256(blobs[path]).hexdigest()},
        }
    record = {
        "schema_version": "m9.fixture-execution.v1",
        "behavior_id": comparison["behavior_id"],
        "fixture_ref": comparison["fixture_ref"],
        "fixture": {"path": "fixture.json", "sha256": fixture_sha},
        **outputs,
    }
    blobs[comparison["evidence_ref"]] = json.dumps(record).encode()
    return blobs


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_record",
        "missing_fixture",
        "changed_fixture",
        "missing_output",
        "changed_output",
        "changed_measurement",
        "wrong_commit",
        "wrong_exit",
        "foreign_fixture",
        "unknown_record_field",
    ],
)
def test_retained_pair_must_match_identity_fixture_bytes_and_all_measured_outputs(mutation, monkeypatch):
    body, hashes = report_fixture()
    evidence = execution_fixture(body)
    install_fixture_harness(body, monkeypatch)
    if mutation == "missing_record":
        del evidence["proof:research"]
    elif mutation == "missing_fixture":
        del evidence["fixture.json"]
    elif mutation == "changed_fixture":
        evidence["fixture.json"] = b"different"
    elif mutation == "missing_output":
        del evidence["donor.json"]
    elif mutation == "changed_output":
        evidence["donor.json"] = b"different"
    elif mutation == "changed_measurement":
        body["commands"][0]["dimensions"][0]["donor"] = 2
    else:
        record = json.loads(evidence["proof:research"])
        if mutation == "wrong_commit":
            record["r2"]["source_commit"] = "b" * 40
        elif mutation == "wrong_exit":
            record["r2"]["exit_code"] = 1
        elif mutation == "foreign_fixture":
            record["fixture_ref"] = "foreign"
        else:
            record["unknown"] = True
        evidence["proof:research"] = json.dumps(record).encode()
    assert verify_m9_parity(body, HEAD, hashes, evidence)


def test_report_cannot_change_a_measurement_even_when_the_declared_fold_still_passes(monkeypatch):
    body, hashes = report_fixture()
    evidence = execution_fixture(body)
    install_fixture_harness(body, monkeypatch)
    for row in body["commands"][0]["dimensions"]:
        row["donor"] = row["r2"] = 2
    assert verify_m9_parity(body, HEAD, hashes, evidence)


def test_artifact_loader_refuses_paths_outside_the_declared_proof_root(tmp_path):
    from r2.contracts.advanced_creative import DonorParityReport
    from scripts.r2.verify_m9_parity import retained_evidence

    body, _ = report_fixture()
    body["commands"][0]["evidence_ref"] = "../outside.json"
    body["rows"][0]["evidence_refs"] = ["../outside.json"]
    with pytest.raises(ValueError, match="leaves"):
        retained_evidence(DonorParityReport.model_validate(body), tmp_path)


def test_cli_requires_the_retained_pair_even_when_source_hashes_match(tmp_path, monkeypatch, capsys):
    from scripts.r2 import verify_m9_parity as verifier

    body, hashes = report_fixture()
    for name, raw in execution_fixture(body).items():
        (tmp_path / name).write_bytes(raw)
    report = tmp_path / "report.json"
    report.write_text(json.dumps(body))
    monkeypatch.setattr(verifier, "clone_file_hashes", lambda *_: hashes)
    install_fixture_harness(body, monkeypatch)
    args = [str(report), "--head", HEAD, "--donor-clone", str(tmp_path)]
    assert verifier.main(args) == 0
    assert "M9_DONOR_PARITY_OK" in capsys.readouterr().out
    (tmp_path / "donor.json").unlink()
    assert verifier.main(args) == 2


def install_fixture_harness(body, monkeypatch):
    from scripts.r2 import verify_m9_parity as verifier

    blobs = execution_fixture(body)
    record = json.loads(blobs[body["commands"][0]["evidence_ref"]])
    pair = verifier.ExecutedPair(
        **{
            side: verifier.ExecutedRuntime(
                argv=tuple(record[side]["argv"]),
                source_commit=record[side]["source_commit"],
                exit_code=record[side]["exit_code"],
                stdout=blobs[record[side]["stdout"]["path"]],
            )
            for side in ("donor", "r2")
        }
    )

    def execute(head, fixture):
        assert head == HEAD
        assert fixture == blobs["fixture.json"]
        return pair

    monkeypatch.setattr(verifier, "REGISTERED_FIXTURE_HARNESSES", {(PIN, "research"): execute})
    return pair


def test_fully_self_attested_bytes_cannot_pass_without_a_registered_execution_harness():
    body, hashes = report_fixture()
    assert verify_m9_parity(body, HEAD, hashes, execution_fixture(body))


def test_a_registered_harness_must_recompute_the_recorded_outputs(monkeypatch):
    from scripts.r2 import verify_m9_parity as verifier

    body, hashes = report_fixture()
    pair = install_fixture_harness(body, monkeypatch)
    changed = pair.model_copy(
        update={"r2": pair.r2.model_copy(update={"stdout": b"freshly observed different output"})}
    )
    monkeypatch.setattr(verifier, "REGISTERED_FIXTURE_HARNESSES", {(PIN, "research"): lambda *_: changed})
    assert verify_m9_parity(body, HEAD, hashes, execution_fixture(body))
