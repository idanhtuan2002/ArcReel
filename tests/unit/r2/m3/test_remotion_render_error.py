"""A failed Remotion render reports the tail of its own output."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from r2.m3 import remotion_engine


def test_a_failed_render_carries_the_tail_of_its_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lines = [f"line {n}" for n in range(30)] + ["Error: ENOSPC: no space left on device"]

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="\n".join(lines))

    monkeypatch.setattr(remotion_engine.subprocess, "run", fake_run)

    with pytest.raises(remotion_engine.RemotionRenderError) as raised:
        remotion_engine._run_render(tmp_path, tmp_path / "out.mp4", {"cuts": []})

    message = str(raised.value)
    assert "exited 1 for out.mp4" in message
    assert "ENOSPC" in message
    assert "line 10" not in message
