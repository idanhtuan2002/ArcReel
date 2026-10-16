"""M9's report verifier binds selected file bytes as well as measured results."""

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


def test_verifier_accepts_exact_bytes_and_refuses_changed_or_missing_blob():
    body, hashes = report_fixture()
    assert verify_m9_parity(body, HEAD, hashes) == []
    assert verify_m9_parity(body, HEAD, {**hashes, PATHS[0]: "sha256:" + "b" * 64})
    assert verify_m9_parity(body, HEAD, {path: value for path, value in hashes.items() if path != PATHS[0]})


def test_verifier_refuses_forged_measurement_and_malformed_report():
    body, hashes = report_fixture()
    body["commands"] = []
    assert verify_m9_parity(body, HEAD, hashes)
    assert verify_m9_parity({"verdict": "PASS"}, HEAD, {})
