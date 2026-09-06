import json
import shutil

from r2.bootstrap import frozen_docs_dir
from scripts.r2.verify_frozen_registries import verify


def test_execution_identity_is_registered_as_production_blocker():
    data = json.loads(
        (frozen_docs_dir() / "R2_05_HOST_HARDENING_REGISTRY.json").read_text()
    )
    h1 = next(item for item in data["requirements"] if item["id"] == "H1")
    assert h1["severity"] == "PRODUCTION_BLOCKER"
    assert h1["decision_ref"] == "R2-HOST-001"


def test_registry_verifier_rejects_h1_downgrade(tmp_path):
    target = tmp_path / "r2"
    shutil.copytree(frozen_docs_dir(), target)

    path = target / "R2_05_HOST_HARDENING_REGISTRY.json"
    data = json.loads(path.read_text())
    h1 = next(item for item in data["requirements"] if item["id"] == "H1")
    h1["severity"] = "ADVISORY"
    path.write_text(json.dumps(data))

    errors = verify(target)
    assert "H1 must remain PRODUCTION_BLOCKER" in errors
