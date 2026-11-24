from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from assembly.web import app as web_app
from assembly.web import runs

PID = "01M863VMJQECF8PC9Z6FVNT6AV"


@pytest.fixture
def console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, list[list[str]], Path]:
    monkeypatch.setattr(runs, "RUNS", tmp_path)
    monkeypatch.setattr(runs, "STORIES", tmp_path / "stories")
    monkeypatch.setattr(web_app, "OPENMONTAGE_PROJECTS", tmp_path / "om")
    monkeypatch.setattr(runs, "unit_active", lambda unit: False)
    monkeypatch.setattr(
        runs,
        "pipeline_status",
        lambda pid, episode=1: {
            "global": {"ingested": True, "characters": True},
            "episode_status": {"identity_plan": True},
            "next_step": "identity_images",
        },
    )
    launched: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: Any) -> Any:
        launched.append(cmd)

        class Done:
            returncode = 0

        return Done()

    monkeypatch.setattr(runs.subprocess, "run", fake_run)
    return TestClient(web_app.app), launched, tmp_path


def _state(tmp: Path, finals: dict[str, str] | None = None) -> None:
    state = {
        "project_id": PID,
        "title": "Sinh vật nhỏ",
        "spine": "narrated",
        "mode": "auto",
        "approved": [],
        "steps": [{"step": "tts", "episode": 1, "note": "", "at": "2026-11-24 14:00"}],
        "voices_cast": {"__narrator__": "Thanh Bình"},
        "finals": finals or {},
    }
    (tmp / f"{PID}.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def test_a_checkpoint_shows_as_waiting_with_an_approve_button(console: Any) -> None:
    http, _, tmp = console
    _state(tmp)
    (tmp / "film-2.log").write_text(f"project {PID}; state x\nCHECKPOINT: CP1 chân dung — duyệt\n", encoding="utf-8")
    home = http.get("/").text
    assert "Chờ duyệt" in home
    assert "Sinh vật nhỏ" in home
    page = http.get(f"/run/{PID}").text
    assert "Duyệt CP1 và chạy tiếp" in page
    assert f"/projects/{PID}/episodes/1/overview" in page


def test_a_stop_after_a_resume_marker_is_a_failure_with_its_message(console: Any) -> None:
    http, _, tmp = console
    _state(tmp)
    log = f"project {PID}; state x\nCHECKPOINT: CP1\n--- resume\nSTOPPED: audio: queue full\n"
    (tmp / "film-2.log").write_text(log, encoding="utf-8")
    assert "Thất bại (1)" in http.get("/").text
    assert "audio: queue full" in http.get(f"/run/{PID}").text


def test_approving_resumes_the_run_with_that_checkpoint(console: Any) -> None:
    http, launched, tmp = console
    _state(tmp)
    (tmp / "film-2.log").write_text(f"project {PID}; state x\nCHECKPOINT: CP1\n", encoding="utf-8")
    http.post(f"/run/{PID}/resume", data={"approve": "CP1"}, follow_redirects=False)
    cmd = next(c for c in launched if c[0] == "systemd-run")
    assert f"--unit=assembly-run-{PID}" in cmd
    assert cmd[cmd.index("--approve") + 1] == "CP1"


def test_starting_from_a_story_saves_it_and_launches_the_connector(console: Any) -> None:
    http, launched, tmp = console
    response = http.post(
        "/start", data={"title": "Phim thử", "story": "Ngày xưa…", "mode": "step"}, follow_redirects=False
    )
    assert response.status_code == 303
    cmd = next(c for c in launched if c[0] == "systemd-run")
    story = Path(cmd[cmd.index("--story") + 1])
    assert story.read_text(encoding="utf-8") == "Ngày xưa…"
    assert cmd[cmd.index("--mode") + 1] == "step"
    assert "Phim thử" in json.loads((tmp / "web-index.json").read_text(encoding="utf-8")).popitem()[1]["title"]


def test_a_start_needs_a_story_or_a_video(console: Any) -> None:
    http, launched, _ = console
    assert http.post("/start", data={"title": "x"}).status_code == 400
    assert not launched


def test_only_the_recorded_final_film_is_served(console: Any) -> None:
    http, _, tmp = console
    film = tmp / "ep01.mp4"
    film.write_bytes(b"mp4")
    _state(tmp, finals={"1": str(film)})
    assert http.get(f"/film/{PID}/1").content == b"mp4"
    assert http.get(f"/film/{PID}/2").status_code == 404
    assert http.get("/film/..%2Fetc/1").status_code == 404
