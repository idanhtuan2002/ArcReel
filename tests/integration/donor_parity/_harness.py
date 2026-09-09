"""Shared helpers for the R2-DEC-031 donor-parity suites (not a conftest).

Runs the vendored, unmodified pinned donor TypeScript through the ``tsx`` loader and
returns its results keyed by fixture id, for comparison against the Python port.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

HARNESS_DIR = Path(__file__).parent
REPO_ROOT = HARNESS_DIR.parents[2]


def run_node_runner(harness_dir: Path, runner: str, cases_path: str) -> dict[str, dict]:
    """Run one ``*_runner.mjs`` with the tsx loader and return ``{case_id: result}``.

    ``cwd`` is the harness dir so ``--import tsx`` resolves against its own
    ``node_modules``; the runner resolves every other path against the repo root.
    """
    proc = subprocess.run(
        ["node", "--import", "tsx", str(harness_dir / runner), cases_path],
        cwd=harness_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return {row["id"]: row for row in json.loads(proc.stdout)}


def load_jsonl(rel_path: str) -> list[dict]:
    lines = (REPO_ROOT / rel_path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]
