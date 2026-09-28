"""Parsing of the portfolio admission settings (ADR-0094)."""

from __future__ import annotations

import pytest

from lib.project_admission import (
    PAUSED_PROJECTS_SETTING,
    PROJECT_CEILING_SETTING,
    ProjectAdmission,
    parse_project_admission,
)


def test_unset_settings_admit_everything() -> None:
    assert parse_project_admission({}) == ProjectAdmission()


def test_the_settings_become_a_pause_set_and_a_ceiling() -> None:
    admission = parse_project_admission({PAUSED_PROJECTS_SETTING: '["a", "b"]', PROJECT_CEILING_SETTING: "2"})
    assert admission == ProjectAdmission(paused=frozenset({"a", "b"}), ceiling=2)


@pytest.mark.parametrize(
    "settings",
    [
        {PAUSED_PROJECTS_SETTING: "not json"},
        {PAUSED_PROJECTS_SETTING: '{"a": 1}'},
        {PROJECT_CEILING_SETTING: "many"},
        {PROJECT_CEILING_SETTING: "-1"},
        {PROJECT_CEILING_SETTING: "0"},
    ],
)
def test_a_malformed_or_zero_value_is_ignored(settings: dict[str, str]) -> None:
    assert parse_project_admission(settings) == ProjectAdmission()
