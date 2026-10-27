"""A4 additions cannot alter predecessor authority or enlarge the migration graph."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


def guard():
    try:
        return importlib.import_module("scripts.r2.verify_m10_a4_scope")
    except ModuleNotFoundError:
        pytest.fail("A4 guard is missing; scope cannot be admitted")


def test_compatibility_accepts_only_recorded_historical_and_proposed_bytes() -> None:
    packet = json.loads((ROOT / "docs/r2/evidence/R2_M10_A4_PACKET_2026-10-27.json").read_text())
    row = packet["migration_test_compatibility"]
    before = (ROOT / row["path"]).read_bytes()
    after = row["proposed_source"].encode()
    assert guard().compatibility_problems(row, before, mode="100644") == ()
    assert guard().compatibility_problems(row, after, mode="100644") == ()
    assert guard().compatibility_problems(row, after + b"\nprint('CANARY')", mode="100644") == (
        "POST_M8_BASE_SEAM_CHANGED",
    )
    assert guard().compatibility_problems(row, after, mode="100755") == ("POST_M8_BASE_SEAM_CHANGED",)


def test_model_exports_are_additive_without_executable_drift() -> None:
    before = b'"""Models."""\n__all__ = ["User"]\n'
    names = ("QualityProbeInvocationModel", "QualityProbeResultModel", "QualityProbeObservationModel")
    after = ("from lib.db.models.quality_probes import " + ", ".join(names) + "\n").encode()
    after += ('__all__ = ["User",' + ",".join(repr(n) for n in names) + "]\n").encode()
    after = b'"""Models."""\n' + after
    assert guard().registry_problems(before, before, names) == ()
    assert guard().registry_problems(before, after, names) == ()
    assert guard().registry_problems(before, after + b"print('CANARY')\n", names) == ("POST_M8_BASE_SEAM_CHANGED",)


def test_migration_accepts_only_one_exact_successor_with_frozen_predecessor() -> None:
    before = {"old.py": b"revision='65f53650f3a8'\ndown_revision=None\n"}
    args = {"target_path": "new.py", "revision": "07fd34535384", "predecessor": "65f53650f3a8"}
    after = {**before, "new.py": b"revision='07fd34535384'\ndown_revision='65f53650f3a8'\n"}
    assert guard().migration_problems(before, before, **args) == ()
    assert guard().migration_problems(before, after, **args) == ()
    assert guard().migration_problems(before, {**after, "extra.py": b"pass"}, **args) == ("M10_SCHEMA_CHANGE_REQUIRED",)
    assert guard().migration_problems(before, {**after, "old.py": b"revision='wrong'"}, **args) == (
        "M10_SCHEMA_CHANGE_REQUIRED",
    )


def test_capability_addition_cannot_rewrite_an_old_entry_or_claim_lookup() -> None:
    before = {"schema_version": 1, "profiles": [{"ref": "old", "evidence_digest": "frozen"}]}
    new = {
        "ref": "local-ffmpeg-quality-probe@host-quality-v1",
        "provider_id": "local-ffmpeg",
        "api_version": "ffmpeg-cli",
        "adapter_version": "host-quality-v1",
        "idempotency_mode": "NONE",
        "token_scope": None,
        "token_scope_value": None,
        "token_ttl_seconds": None,
        "not_found_semantics": "NON_AUTHORITATIVE",
        "lookup_settling_window_seconds": None,
        "supports_poll": False,
        "supports_cancel": False,
        "supports_webhook": False,
        "supports_lookup": False,
        "provider_sequence_is_monotonic": False,
        "evidence_digest": "sha256:" + "1" * 64,
        "qualification_status": "OFFLINE_VERIFIED",
        "evidence_recorded_at": "2026-10-27T00:00:00+00:00",
        "evidence_expires_at": None,
        "entry_digest": "sha256:" + "2" * 64,
    }
    after = {**before, "profiles": [*before["profiles"], new]}

    def encode(value: object) -> bytes:
        return json.dumps(value).encode()

    assert guard().capability_problems(encode(before), encode(before)) == ()
    assert guard().capability_problems(encode(before), encode(after)) == ()
    new["supports_lookup"] = True
    assert guard().capability_problems(encode(before), encode(after)) == ("POST_M8_BASE_SEAM_CHANGED",)
    new["supports_lookup"] = False
    after["profiles"][0] = {"ref": "old", "evidence_digest": "changed"}
    assert guard().capability_problems(encode(before), encode(after)) == ("POST_M8_BASE_SEAM_CHANGED",)


def test_route_allows_only_the_exact_local_quality_family() -> None:
    import subprocess

    before = subprocess.run(
        ["git", "show", f"{guard().BASELINE_REF}:r2/host_hardening/route_inventory.py"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    assert guard().route_problems(before, before) == ()
    after = guard().qualified_route_source(before)
    assert guard().route_problems(before, after) == ()
    assert guard().route_problems(before, after.replace(b"quality-probe", b"cloud-probe")) == (
        "POST_M8_BASE_SEAM_CHANGED",
    )
    assert guard().route_problems(before, after + b"print('CANARY')\n") == ("POST_M8_BASE_SEAM_CHANGED",)


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("r2/quality/probes.py", "import socket\n"),
        ("r2/quality/probes.py", "from sqlalchemy import select\n"),
        ("server/services/quality_probes.py", "from server.auth import get_current_user\n"),
        ("server/services/quality_probe_worker.py", "import httpx\n"),
        ("server/services/quality_probes.py", "def f(): return __import__('socket')\n"),
        ("server/services/quality_probe_runtime.py", "print('CANARY')\n"),
    ],
)
def test_source_boundaries_reject_network_auth_substitution_and_import_effects(path: str, source: str) -> None:
    assert guard().source_problems(path, source.encode()) == ("M10_NETWORK_SIDE_EFFECT_FORBIDDEN",)


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("server/services/quality_probe_runtime.py", "import subprocess\njob = subprocess.Popen(['sh'])\n"),
        ("r2/quality/probes.py", "def f(value=print('CANARY')): return value\n"),
        ("r2/quality/probes.py", "class Facts:\n    value = print('CANARY')\n"),
    ],
)
def test_assigned_class_and_default_argument_import_effects_are_refused(path: str, source: str) -> None:
    assert guard().source_problems(path, source.encode()) == ("M10_NETWORK_SIDE_EFFECT_FORBIDDEN",)
