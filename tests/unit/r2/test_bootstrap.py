import json

from r2.bootstrap import frozen_docs_dir


def test_frozen_docs_dir_contains_decision_registry():
    path = frozen_docs_dir()
    assert (path / "R2_04_DECISION_REGISTRY.json").is_file()


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
