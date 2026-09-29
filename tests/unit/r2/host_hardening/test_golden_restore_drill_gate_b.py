"""The restore drill's Gate B check for the factual golden product (ADR-0092)."""

from __future__ import annotations

import pytest

from tests.drills.r2.golden_restore_drill import script_lock_problem

_SOURCE = "sha256:" + "a" * 64
_SCRIPT = "sha256:" + "b" * 64
_EXPECTED = {"source_digest": _SOURCE, "script_digest": _SCRIPT}


def test_a_lock_of_the_products_own_revisions_passes() -> None:
    assert script_lock_problem({"action": "LOCK", **_EXPECTED}, _EXPECTED) is None


@pytest.mark.parametrize(
    "lock",
    [
        {"action": "LOCK", "source_digest": "sha256:" + "c" * 64, "script_digest": _SCRIPT},
        {"action": "LOCK", "source_digest": _SOURCE, "script_digest": "sha256:" + "c" * 64},
    ],
)
def test_a_lock_of_other_revisions_is_a_digest_mismatch(lock: dict[str, str]) -> None:
    assert script_lock_problem(lock, _EXPECTED) == "GATE_B_DIGEST_MISMATCH"


@pytest.mark.parametrize("lock", [{}, {"action": "REVOKE", **_EXPECTED}])
def test_no_standing_lock_is_missing(lock: dict[str, str]) -> None:
    assert script_lock_problem(lock, _EXPECTED) == "GATE_B_MISSING"
