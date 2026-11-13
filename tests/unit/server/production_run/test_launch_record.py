"""A stale launch qualification is recorded again like a missing one (ADR-0139; review H4)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from server.production_run import qualification


class _Policies:
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    async def resolve(self, **kwargs):
        del kwargs
        return SimpleNamespace(launch_profile_id="fiction_narration_vi_v1", profile_digest="sha256:" + "a" * 64)


def _preflight(reasons: tuple[str, ...]):
    class Preflight:
        def __init__(self, reader) -> None:
            del reader

        async def check(self, **kwargs):
            del kwargs
            return SimpleNamespace(blocking_reasons=reasons, route_digests=("sha256:" + "b" * 64,))

    return Preflight


@pytest.mark.parametrize(
    ("reasons", "recorded"),
    [
        (("LAUNCH_PROFILE_NOT_QUALIFIED",), True),
        (("LAUNCH_QUALIFICATION_CHANGED",), True),
        (("LAUNCH_QUALIFICATION_CHANGED", "MISSING_QUALIFIED_REVIEWER"), False),
        (("MODEL_CONFIG_CHANGED",), False),
    ],
)
async def test_a_missing_or_stale_record_is_written_and_any_other_blocker_is_returned(
    tmp_path, monkeypatch, reasons, recorded
):
    evidence = tmp_path / "launch.json"
    evidence.write_text(json.dumps({"ok": True}), encoding="utf-8")
    monkeypatch.setattr(qualification, "ProjectPolicyResolver", _Policies)
    monkeypatch.setattr(qualification, "ConfigResolver", lambda sessions: None)
    monkeypatch.setattr(qualification, "HostPreflightReader", lambda *a, **k: None)
    monkeypatch.setattr(qualification, "ProjectInputWitness", lambda *a, **k: None)
    monkeypatch.setattr(qualification, "ProductionPreflight", _preflight(reasons))

    record, left = await qualification.build_record(
        None,
        projects=None,
        user_id="u",
        project_name="p",
        evidence=evidence,
    )

    assert (record is not None) == recorded
    assert left == (() if recorded else reasons)
    if record is not None:
        assert record.route_digests == ("sha256:" + "b" * 64,)
