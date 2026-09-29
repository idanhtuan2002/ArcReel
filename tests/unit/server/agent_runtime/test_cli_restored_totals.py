"""The CLI's restore-on-resume rule, read from the same global config the CLI reads."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.agent_runtime.cli_restored_totals import RestoredTotals, cli_global_config_path, restored_totals


def _write(path: Path, projects: object) -> None:
    path.write_text(json.dumps({"projects": projects}), encoding="utf-8")


def test_the_config_dir_file_holds_the_restored_totals(tmp_path: Path) -> None:
    _write(
        tmp_path / ".claude.json",
        {
            "/a": {"lastSessionId": "other", "lastCost": 9.0},
            "/b": {
                "lastSessionId": "sdk-1",
                "lastCost": 0.25,
                "lastModelUsage": {"m": {"inputTokens": 10, "outputTokens": 5, "cacheReadInputTokens": 2}},
            },
        },
    )

    assert restored_totals("sdk-1", {"CLAUDE_CONFIG_DIR": str(tmp_path)}) == RestoredTotals(0.25, (12, 5, 17))


def test_a_session_that_is_not_any_projects_last_exit_restores_nothing(tmp_path: Path) -> None:
    _write(tmp_path / ".claude.json", {"/a": {"lastSessionId": "other", "lastCost": 1.0}})

    assert restored_totals("sdk-1", {"CLAUDE_CONFIG_DIR": str(tmp_path)}) is None


@pytest.mark.parametrize("content", ["", "not json", "[]", '{"projects": []}'])
def test_an_unreadable_config_restores_nothing(tmp_path: Path, content: str) -> None:
    (tmp_path / ".claude.json").write_text(content, encoding="utf-8")

    assert restored_totals("sdk-1", {"CLAUDE_CONFIG_DIR": str(tmp_path)}) is None


def test_a_missing_config_restores_nothing(tmp_path: Path) -> None:
    assert restored_totals("sdk-1", {"CLAUDE_CONFIG_DIR": str(tmp_path)}) is None


def test_the_legacy_config_file_takes_precedence(tmp_path: Path) -> None:
    (tmp_path / ".config.json").write_text("{}", encoding="utf-8")

    assert cli_global_config_path({"CLAUDE_CONFIG_DIR": str(tmp_path)}) == tmp_path / ".config.json"


def test_a_custom_oauth_url_selects_its_own_config_file(tmp_path: Path) -> None:
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path), "CLAUDE_CODE_CUSTOM_OAUTH_URL": "https://x"}

    assert cli_global_config_path(env) == tmp_path / ".claude-custom-oauth.json"


def test_without_a_config_dir_the_file_is_in_the_home_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert cli_global_config_path({}) == tmp_path / ".claude.json"
