"""Fixtures for the R2-DEC-031 donor-parity harnesses.

These tests execute the unmodified pinned donor TypeScript through a test-only Node
harness (``tsx`` loader) and compare it to the clean-room Python port. They skip only
when a Node toolchain is genuinely unavailable; a real gate run must not skip. Shared
run/load helpers live in ``_harness.py`` (conftest holds fixtures only).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_HARNESS_DIR = Path(__file__).parent


def _have_node() -> bool:
    return shutil.which("node") is not None and (
        shutil.which("pnpm") is not None or (_HARNESS_DIR / "node_modules").is_dir()
    )


@pytest.fixture(scope="session")
def donor_node_env() -> Path:
    if not _have_node():
        pytest.skip("Node/pnpm toolchain unavailable; donor-parity gate requires it")
    if not (_HARNESS_DIR / "node_modules" / "tsx").is_dir():
        subprocess.run(
            ["pnpm", "install", "--ignore-workspace", "--frozen-lockfile"],
            cwd=_HARNESS_DIR,
            check=True,
            capture_output=True,
        )
    return _HARNESS_DIR
