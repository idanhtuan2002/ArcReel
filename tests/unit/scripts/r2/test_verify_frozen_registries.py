import json
import shutil

from r2.bootstrap import frozen_docs_dir
from scripts.r2.verify_frozen_registries import verify


def test_frozen_registry_integrity():
    assert verify() == []


def test_every_authoritative_contract_has_one_commit_authority():
    data = json.loads((frozen_docs_dir() / "R2_03_CONTRACT_REGISTRY.json").read_text())
    non_authoritative = {
        "NON_AUTHORITATIVE",
        "PROPOSAL",
        "PROPOSAL_TO_NARRATIVE_AUTHORITY",
        "CROSS_AUTHORITY_LINEAGE",
        "REVIEW_PLANE",
    }
    for item in data["contracts"]:
        if item["authority"] not in non_authoritative:
            assert item.get("commit_authority"), item["name"]


def test_verifier_rejects_downgraded_h1(tmp_path):
    target = tmp_path / "r2"
    shutil.copytree(frozen_docs_dir(), target)

    hardening_path = target / "R2_05_HOST_HARDENING_REGISTRY.json"
    data = json.loads(hardening_path.read_text())
    h1 = next(item for item in data["requirements"] if item["id"] == "H1")
    h1["severity"] = "ADVISORY"
    hardening_path.write_text(json.dumps(data))

    errors = verify(target)
    assert any("H1" in error for error in errors)
