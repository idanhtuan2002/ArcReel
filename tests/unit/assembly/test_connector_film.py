"""The connector walks DramaClaw's pipeline/status one write task at a time (ASSEMBLY_PLAN M2, Hermes playbooks)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest

from assembly.connector import film
from assembly.connector.film import FilmRun, RunState, RunStopped, chapter_text


class FakeTools:
    def __init__(self, statuses: list[dict[str, Any]], tasks: dict[str, str] | None = None) -> None:
        self.project_id = "p1"
        self.statuses = statuses
        self.tasks = tasks or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, tool: str, /, **args: Any) -> Any:
        self.calls.append((tool, args))
        if tool == "dramaclaw_pipeline_status":
            return {"ok": True, "data": self.statuses.pop(0)}
        if tool == "dramaclaw_get_task":
            status = self.tasks.get(args["task_type"], "completed")
            return {"ok": True, "data": {"status": status, "error": "upstream refused"}}
        return {"ok": True, "data": {}}

    def request(self, method: str, path: str, **_: Any) -> dict[str, Any]:
        if path.endswith("/characters"):
            return {"ok": True, "data": [{"name": "Vy", "is_main": True, "face_prompt": "x"}]}
        return {"ok": True, "data": []}


def _run(tools: FakeTools, tmp_path: Path) -> FilmRun:
    state = RunState(project_id="p1", title="t", spine="narrated")
    return FilmRun(tools, state, tmp_path / "s.json", out_dir=tmp_path, log=lambda _l: None)


def test_vietnamese_chapter_headings_become_dramaclaw_chapter_markers() -> None:
    assert chapter_text("Chương 1: Mưa\nA\nchương 2 - Nắng\nB").splitlines()[0] == "Chapter 1 Mưa"
    assert "Chapter 2 Nắng" in chapter_text("Chương 1: Mưa\nA\nchương 2 - Nắng\nB")
    assert chapter_text("Chỉ một đoạn.").startswith("Chapter 1\n")


def test_the_run_starts_one_task_per_status_round_and_ends_at_done(tmp_path: Path) -> None:
    tools = FakeTools(
        [
            {"next_step": "build_characters", "current_episode": None},
            {"next_step": "global_optimize_video", "current_episode": 1},
            {"next_step": "done", "current_episode": 1},
        ]
    )
    state = _run(tools, tmp_path).run()
    started = [c[0] for c in tools.calls if c[0] not in {"dramaclaw_pipeline_status", "dramaclaw_get_task"}]
    assert started == ["dramaclaw_build_characters", "dramaclaw_optimize_video_global"]
    assert [s["step"] for s in state.steps] == ["build_characters", "global_optimize_video"]


def test_a_completed_step_that_does_not_advance_stops_the_run(tmp_path: Path) -> None:
    tools = FakeTools([{"next_step": "tts", "current_episode": 1}, {"next_step": "tts", "current_episode": 1}])
    with pytest.raises(RunStopped, match="did not advance"):
        _run(tools, tmp_path).run()


def test_a_failed_task_stops_with_its_own_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(film, "POLL_SECONDS", 0)
    tools = FakeTools([{"next_step": "tts", "current_episode": 1}], {"audio_generation_indextts2": "failed"})
    with pytest.raises(RunStopped, match="upstream refused"):
        _run(tools, tmp_path).run()


def test_an_unprepared_project_is_not_driven(tmp_path: Path) -> None:
    tools = FakeTools([{"next_step": "configure", "current_episode": None}])
    with pytest.raises(RunStopped, match="not prepared"):
        _run(tools, tmp_path).run()


def test_project_names_meet_dramaclaw_rules() -> None:
    from assembly.connector.setup import project_name

    name = project_name("Chiếc đồng hồ của ông (narrated)")
    assert name.startswith("Chiec_dong_ho_cua_ong_narrated_")
    assert all(ch.isalnum() or ch == "_" for ch in name)


def test_a_resumed_run_prepares_existing_characters_before_the_next_step(tmp_path: Path) -> None:
    tools = FakeTools([{"next_step": "done", "current_episode": 1}])
    prepared: list[str] = []
    run = _run(tools, tmp_path)
    run.cast_voices = lambda r: prepared.append("cast")
    run.run()
    assert prepared == ["cast"]


def test_recurring_characters_are_graded_main_when_extraction_marked_none(tmp_path: Path) -> None:
    patched: list[str] = []

    class GradingTools(FakeTools):
        def request(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
            if path.endswith("/characters"):
                return {"ok": True, "data": [{"name": "ông Khang"}, {"name": "Lan"}]}
            if path.endswith("/episodes"):
                return {"ok": True, "data": [{"number": 1}]}
            if path.endswith("/raw-content"):
                return {"ok": True, "data": "Khang cười. Khang nói. Khang đi. Lan nhìn."}
            if method == "PATCH":
                patched.append(unquote(path.rsplit("/", 1)[1]))
            return {"ok": True, "data": {}}

    tools = GradingTools([])
    _run(tools, tmp_path).grade_characters()
    assert patched == ["ông Khang"]
