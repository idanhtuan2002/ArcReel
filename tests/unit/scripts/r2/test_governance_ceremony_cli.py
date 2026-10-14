"""The offline ceremony commands produce records the verifiers accept, and refuse unsafe files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from r2.contracts.governance_host_records import parse_approved_deployment
from r2.contracts.governance_verifier_registry import parse_verifier_registry
from r2.governance.ceremony import decode_public_key
from r2.governance.checkpoint_signature import verify_grant_checkpoint
from r2.governance.grant_signature import verify_grant_event
from scripts.r2.governance_ceremony import main


def _run(*argv: object) -> int:
    return main([str(arg) for arg in argv])


def test_the_offline_commands_build_a_verifiable_genesis_and_issue(tmp_path: Path) -> None:
    for name in ("grant", "checkpoint"):
        assert _run("keygen", "--private", tmp_path / f"{name}.key", "--public", tmp_path / f"{name}.pub") == 0
    assert (tmp_path / "grant.key").stat().st_mode & 0o777 == 0o600
    assert _run(
        "registry",
        "--deployment-id", "deploy-a",
        "--grant-key-id", "grant-key-a",
        "--grant-public", tmp_path / "grant.pub",
        "--checkpoint-key-id", "checkpoint-key-a",
        "--checkpoint-public", tmp_path / "checkpoint.pub",
        "--out", tmp_path / "registry.json",
    ) == 0  # fmt: skip
    assert _run(
        "approve",
        "--registry", tmp_path / "registry.json",
        "--image-ref", "arcreel/arcreel@sha256:" + "b" * 64,
        "--image-platform", "linux/amd64",
        "--operator-id", "op-a",
        "--out", tmp_path / "approved.json",
    ) == 0  # fmt: skip
    assert _run("genesis-body", "--registry", tmp_path / "registry.json", "--out", tmp_path / "genesis.body") == 0
    assert _run(
        "sign-checkpoint", "--key", tmp_path / "checkpoint.key",
        "--body", tmp_path / "genesis.body", "--out", tmp_path / "genesis.json",
    ) == 0  # fmt: skip
    assert _run(
        "sign-event", "--key", tmp_path / "grant.key", "--key-id", "grant-key-a", "--type", "ISSUE",
        "--user-id", "default", "--project", "show-a", "--principal", "reviewer-a", "--sequence", "1",
        "--expires-at", "2099-01-01T00:00:00Z", "--out", tmp_path / "issue.json",
    ) == 0  # fmt: skip

    registry = parse_verifier_registry((tmp_path / "registry.json").read_bytes())
    approved = parse_approved_deployment((tmp_path / "approved.json").read_bytes())
    assert approved.body.registry_file_digest == registry.registry_digest
    verify_grant_checkpoint(
        (tmp_path / "genesis.json").read_bytes(),
        deployment_id="deploy-a",
        key_id="checkpoint-key-a",
        public_key=decode_public_key((tmp_path / "checkpoint.pub").read_text().strip()),
    )
    event = verify_grant_event(
        (tmp_path / "issue.json").read_bytes(),
        key_id="grant-key-a",
        public_key=decode_public_key((tmp_path / "grant.pub").read_text().strip()),
    )
    assert (event.body.event_type, event.body.principal) == ("ISSUE", "reviewer-a")


def test_existing_outputs_and_readable_private_keys_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run("keygen", "--private", tmp_path / "a.key", "--public", tmp_path / "a.pub") == 0
    assert _run("keygen", "--private", tmp_path / "a.key", "--public", tmp_path / "b.pub") == 1
    os.chmod(tmp_path / "a.key", 0o644)
    (tmp_path / "body.json").write_bytes(b"{}")

    assert (
        _run("sign-checkpoint", "--key", tmp_path / "a.key", "--body", tmp_path / "body.json", "--out", tmp_path / "o")
        == 1
    )
    assert "refused" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_host_commands_require_root(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("the root check is exercised by a non-root run")
    assert _run("next-body", "--root", tmp_path, "--out", tmp_path / "next.body") == 1
