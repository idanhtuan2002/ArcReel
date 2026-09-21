"""R2-DEC-031 drift detection: vendor/openmontage/remotion-composer/ must
match the exact byte content recorded at vendoring time
(docs/r2/evidence/R2_M3_DONOR_BASELINE.json). A future accidental edit to a
vendored file (as opposed to a deliberate re-vendor with a baseline update)
must fail this test, not pass silently."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from r2.m3.donor_baseline import compute_vendor_tree_digest

REPO_ROOT = Path(__file__).resolve().parents[4]
VENDORED_ROOT = REPO_ROOT / "vendor" / "openmontage" / "remotion-composer"
BASELINE_PATH = REPO_ROOT / "docs" / "r2" / "evidence" / "R2_M3_DONOR_BASELINE.json"


def _baseline_port() -> dict[str, Any]:
    document = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return document["ports"]["remotion_composer"]


def test_vendored_remotion_composer_exists() -> None:
    assert VENDORED_ROOT.is_dir()
    assert (VENDORED_ROOT / "src" / "Explainer.tsx").is_file()
    assert (VENDORED_ROOT / "package.json").is_file()


def test_vendored_tree_matches_the_recorded_portable_digest() -> None:
    port = _baseline_port()
    actual = compute_vendor_tree_digest(VENDORED_ROOT)
    assert actual == port["verification"]["portable_content_digest"]


def test_vendored_tree_file_count_matches_the_baseline() -> None:
    # Counts only files git actually tracks -- robust to a local `npm install`
    # or render run having left node_modules/.remotion/out sitting alongside
    # the vendored source in this same checkout when the test runs.
    port = _baseline_port()
    result = subprocess.run(
        ["git", "ls-files", "--", str(VENDORED_ROOT)],
        check=True,
        capture_output=True,
        text=True,
    )
    tracked_files = [line for line in result.stdout.splitlines() if line]
    assert len(tracked_files) == port["verification"]["file_count"]


def test_node_modules_is_never_committed() -> None:
    # node_modules is installed fresh (npm ci) at use time -- it may exist on
    # disk in a local dev checkout, but git must never track it (it would
    # both bloat the repo and make the digest above meaningless, since its
    # content isn't the donor's own source).
    result = subprocess.run(
        ["git", "ls-files", "--", str(VENDORED_ROOT / "node_modules")],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""
