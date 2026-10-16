"""M9 parity requires exact selected source and same-fixture measured results."""

import copy

import pytest

from r2.advanced_creative.digests import digest_canonical
from r2.contracts.advanced_creative import DonorParityReport, ParityVerdict
from r2.opportunity.parity import evaluate_m9_parity

HEAD = "a" * 40
PIN = "08e2151fa02de28a5d6a312b3d575692bf147ad7"
PATHS = (
    "skills/pipelines/explainer/research-director.md",
    "schemas/artifacts/research_brief.schema.json",
    "schemas/artifacts/decision_log.schema.json",
)
H = "sha256:" + "a" * 64
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


def report_body() -> dict:
    body = {
        "contract_version": "1",
        "donor": {
            "repository_url": "https://github.com/calesthio/OpenMontage",
            "commit_sha": PIN,
            "selected_paths": PATHS,
            "reachable_surface_digest": H,
            "runtime_identity": "python-fixture",
            "behavior_inventory_digest": H,
            "donor_test_inventory_digest": H,
            "fixture_set_digest": H,
        },
        "integrated_head": HEAD,
        "rows": [
            {
                "behavior_id": "research-vocabulary",
                "donor_test_refs": ["schema-validation"],
                "fixture_refs": ["fixture:western"],
                "intentional_difference": None,
                **dict.fromkeys(DIMENSIONS, "PARITY"),
                "evidence_refs": ["comparison:western"],
            }
        ],
        "commands": [
            {
                "evidence_ref": "comparison:western",
                "behavior_id": "research-vocabulary",
                "fixture_ref": "fixture:western",
                "donor_commit": PIN,
                "integrated_head": HEAD,
                "donor_exit_code": 0,
                "r2_exit_code": 0,
                "applicable": True,
                "dimensions": [
                    {"dimension": dimension, "comparison": "EQUAL", "donor": 1, "r2": 1} for dimension in DIMENSIONS
                ],
            }
        ],
        "required_skips": [],
        "material_unknowns": [],
        "reviewer": "independent-review-pending",
        "verdict": "PASS",
    }

    body["commands"].append(
        {
            "kind": "INVENTORY",
            "behavior_ids": ["research-vocabulary"],
            "donor_test_refs": ["schema-validation"],
            "fixture_refs": ["fixture:western"],
        }
    )
    body["donor"]["behavior_inventory_digest"] = digest_canonical(["research-vocabulary"])
    body["donor"]["donor_test_inventory_digest"] = digest_canonical(["schema-validation"])
    body["donor"]["fixture_set_digest"] = digest_canonical(["fixture:western"])
    return body


def test_recomputes_measured_parity_instead_of_reported_verdict():
    body = report_body()
    body["verdict"] = "BLOCKED"
    assert evaluate_m9_parity(DonorParityReport.model_validate(body), HEAD) is ParityVerdict.PASS
    body["commands"][0]["dimensions"][0]["r2"] = 0
    body["verdict"] = "PASS"
    assert evaluate_m9_parity(DonorParityReport.model_validate(body), HEAD) is ParityVerdict.BLOCKED


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_pin",
        "wrong_path",
        "missing_behavior",
        "missing_result",
        "stale_head",
        "skip",
        "unknown",
        "duplicate_row",
        "missing_fixture",
        "below_parity",
        "failed_r2",
        "missing_dimension",
    ],
)
def test_refuses_incomplete_or_mismatched_same_fixture_proof(mutation):
    body = report_body()
    if mutation == "wrong_pin":
        body["donor"]["commit_sha"] = "b" * 40
    elif mutation == "wrong_path":
        body["donor"]["selected_paths"] = ["unselected.py"]
    elif mutation == "missing_behavior":
        body["commands"][0]["behavior_id"] = "other"
    elif mutation == "missing_result":
        body["commands"] = []
    elif mutation == "stale_head":
        body["commands"][0]["integrated_head"] = "b" * 40
    elif mutation == "skip":
        body["required_skips"] = ["required measurement"]
    elif mutation == "unknown":
        body["material_unknowns"] = ["fixture reachability"]
    elif mutation == "duplicate_row":
        body["rows"].append(copy.deepcopy(body["rows"][0]))
    elif mutation == "missing_fixture":
        body["rows"][0]["fixture_refs"] = ["fixture:other"]
    elif mutation == "below_parity":
        body["commands"][0]["dimensions"][-1].update(comparison="LOWER_IS_BETTER", donor=1, r2=2)
    elif mutation == "failed_r2":
        body["commands"][0]["r2_exit_code"] = 1
    else:
        body["commands"][0]["dimensions"].pop()
    assert evaluate_m9_parity(DonorParityReport.model_validate(body), HEAD) is ParityVerdict.BLOCKED


def test_applicable_behavior_cannot_be_excluded():
    body = report_body()
    excluded = {
        **body["rows"][0],
        "behavior_id": "excluded",
        "intentional_difference": "SCOPE: not selected",
        **dict.fromkeys(DIMENSIONS, "EXCLUDED"),
    }
    body["rows"].append(excluded)
    body["commands"].append({**body["commands"][0], "behavior_id": "excluded"})
    assert evaluate_m9_parity(DonorParityReport.model_validate(body), HEAD) is ParityVerdict.BLOCKED


def test_donor_defect_requires_observed_fail_donor_pass_r2():
    body = report_body()
    body["rows"][0]["intentional_difference"] = "DONOR_DEFECT: malformed research must be refused"
    assert evaluate_m9_parity(DonorParityReport.model_validate(body), HEAD) is ParityVerdict.BLOCKED
    body["commands"][0]["donor_exit_code"] = 1
    assert evaluate_m9_parity(DonorParityReport.model_validate(body), HEAD) is ParityVerdict.PASS


def test_correct_commit_under_unselected_repository_is_not_donor_evidence():
    body = report_body()
    body["donor"]["repository_url"] = "https://example.test/unrelated"
    assert evaluate_m9_parity(DonorParityReport.model_validate(body), HEAD) is ParityVerdict.BLOCKED


def test_declared_reachable_inventory_cannot_lose_a_behavior_row():
    from r2.advanced_creative.digests import digest_canonical

    body = report_body()
    body["commands"][-1]["behavior_ids"] = ["research-vocabulary", "missing-behavior"]
    body["donor"]["behavior_inventory_digest"] = digest_canonical(["missing-behavior", "research-vocabulary"])
    body["donor"]["donor_test_inventory_digest"] = digest_canonical(["schema-validation"])
    body["donor"]["fixture_set_digest"] = digest_canonical(["fixture:western"])
    assert evaluate_m9_parity(DonorParityReport.model_validate(body), HEAD) is ParityVerdict.BLOCKED
