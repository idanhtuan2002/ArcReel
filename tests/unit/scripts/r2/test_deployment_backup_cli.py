"""scripts/r2/deployment_backup.py argument handling (no database)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.r2.deployment_backup import build_parser, main


def test_create_requires_explicit_roots_and_identity() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["create", "--backup-set-id", "bs", "--backup-dir", "/tmp/x"])


def test_database_url_is_read_from_the_named_environment_variable(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.delenv("DRILL_TARGET_URL", raising=False)

    with pytest.raises(SystemExit) as exited:
        main(
            [
                "restore",
                "--backup-dir",
                str(tmp_path / "set"),
                "--target-root",
                f"data={tmp_path / 'data'}",
                "--target-database-url-env",
                "DRILL_TARGET_URL",
            ]
        )

    assert "DRILL_TARGET_URL is not set" in str(exited.value)


def test_malformed_root_is_rejected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DRILL_TARGET_URL", "postgresql://unused")

    with pytest.raises(SystemExit) as exited:
        main(
            [
                "restore",
                "--backup-dir",
                str(tmp_path / "set"),
                "--target-root",
                "data",
                "--target-database-url-env",
                "DRILL_TARGET_URL",
            ]
        )

    assert "NAME=PATH" in str(exited.value)


def test_malformed_golden_evidence_is_a_structured_error(tmp_path: Path, capsys) -> None:
    evidence = tmp_path / "golden.json"
    evidence.write_text("{}", encoding="utf-8")

    code = main(
        [
            "attest",
            "--backup-dir",
            str(tmp_path / "set"),
            "--golden-evidence",
            str(evidence),
            "--measured-rpo-seconds",
            "0",
            "--measured-rto-seconds",
            "0",
        ]
    )

    assert code == 2
    assert "INVALID_INPUT" in capsys.readouterr().err


def test_libpq_command_target_moves_every_password_form_off_argv() -> None:
    from r2.host_hardening.deployment_backup import libpq_command_target

    assert libpq_command_target("postgresql+asyncpg://u:p%40ss@h:5432/db") == (
        "postgresql://u@h:5432/db",
        {"PGPASSWORD": "p@ss"},
    )
    assert libpq_command_target("postgresql://u@h/db?password=q%26s&sslmode=require") == (
        "postgresql://u@h/db?sslmode=require",
        {"PGPASSWORD": "q&s"},
    )
    assert libpq_command_target("postgresql://u@h/db") == ("postgresql://u@h/db", {})
