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
