"""OpenMontage driver commands: Claude Code headless or Codex on the assembly NewAPI, resumable sessions."""

from __future__ import annotations

import json

from assembly.openmontage.run import build_command, session_of


def test_claude_runs_headless_and_resumes_its_session() -> None:
    cmd, _ = build_command("claude", "go", None)
    assert cmd[:3] == ["claude", "-p", "go"]
    cmd, _ = build_command("claude", "ok", "s-1")
    assert cmd[-2:] == ["--resume", "s-1"]


def test_codex_uses_the_assembly_profile_and_resumes() -> None:
    cmd, env = build_command("codex", "go", None)
    assert env["CODEX_HOME"].endswith("assembly-data/codex-home")
    assert cmd[:3] == ["codex", "exec", "--json"]
    cmd, _ = build_command("codex", "ok", "t-9")
    assert cmd[-3:] == ["resume", "t-9", "ok"]


def test_sessions_are_read_from_each_driver_output() -> None:
    assert session_of("claude", json.dumps({"session_id": "s-1", "result": "x"})) == "s-1"
    assert session_of("codex", '{"type":"thread.started","thread_id":"t-9"}\n{"type":"turn.completed"}') == "t-9"
