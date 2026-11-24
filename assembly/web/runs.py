"""Runs seen by the control page: connector state files, their logs and systemd user units.

A run is one DramaClaw project driven by `python -m assembly.connector`. Its state file is
`<runs>/<project_id>.json` (`RunState`); its log is the file whose first `project <id>` line names it; a run started
from the page runs as the user unit `assembly-run-<key>` and logs to `<runs>/<key>.log`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

RUNS = Path(os.environ.get("ASSEMBLY_RUNS_DIR", Path.home() / "assembly-data/runs"))
STORIES = Path.home() / "assembly-data/stories"
DRAMACLAW_API = os.environ.get("DRAMACLAW_API", "http://127.0.0.1:8780/api/v1")
REPO = Path(__file__).resolve().parents[2]

# DramaClaw `pipeline/status` keys (playbooks/resume.md) in run order, with the DramaClaw screen that shows each one.
GLOBAL_STEPS = [
    ("ingested", "Nạp truyện", "ingest"),
    ("configured", "Cấu hình", "styles"),
    ("characters", "Nhân vật", "characters"),
    ("episodes", "Chia tập", "episodes"),
    ("portraits_done", "Chân dung (CP1)", "characters"),
]
EPISODE_STEPS = [
    ("identity_plan", "Kế hoạch tạo hình", "overview"),
    ("identity_images", "Ảnh tạo hình", "overview"),
    ("script", "Kịch bản / lời kể", "script"),
    ("sketches", "Phác thảo", "sketches"),
    ("coloring", "Tô màu + kiểm tra", "sketches"),
    ("global_optimize", "Tối ưu video", "beats"),
    ("first_frames", "Khung hình đầu", "beats"),
    ("tts", "Lồng tiếng", "audio"),
    ("video", "Video từng beat", "video"),
]
_MARK = re.compile(r"^(CHECKPOINT|STOPPED|DONE): (.*)$")
_CP = re.compile(r"\b(CP[1-5])\b")


@dataclass
class Run:
    project_id: str
    title: str
    mode: str
    state: dict[str, Any]
    log: Path | None = None
    unit: str | None = None
    active: bool = False
    status: str = "stopped"  # running | waiting | failed | done | stopped
    message: str = ""
    checkpoint: str | None = None
    finals: dict[str, str] = field(default_factory=dict)


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, check=False)


def unit_active(unit: str) -> bool:
    return _systemctl("is-active", "--quiet", unit).returncode == 0


def _index() -> dict[str, dict[str, str]]:
    path = RUNS / "web-index.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save_index(index: dict[str, dict[str, str]]) -> None:
    (RUNS / "web-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def logs_by_project() -> dict[str, Path]:
    """Map project id → its log, from each log's `project <id>` line (latest log wins)."""
    found: dict[str, Path] = {}
    for log in sorted(RUNS.glob("*.log"), key=lambda p: p.stat().st_mtime):
        with log.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("project "):
                    found[line.split()[1].rstrip(";")] = log
                    break
    return found


def last_marker(log: Path) -> tuple[str, str]:
    """The last CHECKPOINT/STOPPED/DONE line after the last resume marker."""
    kind, message = "", ""
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("--- "):
            kind, message = "", ""
        elif match := _MARK.match(line):
            kind, message = match.group(1), match.group(2)
    return kind, message


def load_runs() -> list[Run]:
    resolve_new_projects()
    logs, index = logs_by_project(), _index()
    units = {entry.get("project_id"): entry["unit"] for entry in index.values() if entry.get("project_id")}
    runs: list[Run] = []
    for path in sorted(RUNS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.name == "web-index.json":
            continue
        state = json.loads(path.read_text(encoding="utf-8"))
        if "project_id" not in state:
            continue
        run = Run(
            state["project_id"],
            state.get("title", ""),
            state.get("mode", "auto"),
            state,
            logs.get(state["project_id"]),
            units.get(state["project_id"]),
            finals=state.get("finals") or {},
        )
        run.active = bool(run.unit and unit_active(run.unit))
        kind, run.message = last_marker(run.log) if run.log else ("", "")
        if run.active:
            run.status = "running"
        elif kind == "CHECKPOINT":
            run.status, cp = "waiting", _CP.search(run.message)
            run.checkpoint = cp.group(1) if cp else None
        elif kind == "STOPPED":
            run.status = "failed"
        elif kind == "DONE" or run.finals:
            run.status = "done"
        runs.append(run)
    return runs


def pending_starts() -> list[dict[str, str]]:
    """Runs started from the page whose project is not created yet (their log has no `project` line so far)."""
    out = []
    for key, entry in _index().items():
        if not entry.get("project_id"):
            log = RUNS / f"{key}.log"
            text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
            out.append(
                {
                    "key": key,
                    "title": entry.get("title", ""),
                    "active": str(unit_active(entry["unit"])),
                    "tail": "\n".join(text.splitlines()[-6:]),
                }
            )
    return out


def resolve_new_projects() -> None:
    index, changed = _index(), False
    for key, entry in index.items():
        log = RUNS / f"{key}.log"
        if not entry.get("project_id") and log.exists():
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("project "):
                    entry["project_id"], changed = line.split()[1].rstrip(";"), True
                    break
    if changed:
        _save_index(index)


def pipeline_status(project_id: str, episode: int = 1) -> dict[str, Any]:
    try:
        response = httpx.get(
            f"{DRAMACLAW_API}/projects/{project_id}/pipeline/status", params={"episode": episode}, timeout=10
        )
        return response.json().get("data") or {}
    except (httpx.HTTPError, ValueError):
        return {}


def timeline(project_id: str, episode: int = 1) -> list[dict[str, Any]]:
    data = pipeline_status(project_id, episode)
    glob, ep = data.get("global") or {}, data.get("episode_status") or {}
    rows = [
        {"key": k, "label": label, "done": bool(glob.get(k)), "page": page, "scope": "project"}
        for k, label, page in GLOBAL_STEPS
    ]
    rows += [
        {"key": k, "label": label, "done": bool(ep.get(k)), "page": page, "scope": "episode"}
        for k, label, page in EPISODE_STEPS
    ]
    rows.append(
        {
            "key": "compose",
            "label": "Dựng phim",
            "done": bool(data.get("next_step") == "done"),
            "page": "compose",
            "scope": "episode",
        }
    )
    return rows


def _launch(key: str, args: list[str]) -> None:
    log = RUNS / f"{key}.log"
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"--- {time.strftime('%H:%M:%S')} {' '.join(a for a in args if not a.startswith('/'))}\n")
    _systemctl("reset-failed", f"assembly-run-{key}")
    subprocess.run(
        [
            "systemd-run",
            "--user",
            f"--unit=assembly-run-{key}",
            f"--working-directory={REPO}",
            f"--property=StandardOutput=append:{log}",
            f"--property=StandardError=append:{log}",
            sys.executable,
            "-m",
            "assembly.connector",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )


def start_new(*, title: str, story_text: str, video: str, spine: str, region: str, mode: str) -> str:
    key = time.strftime("%Y%m%d-%H%M%S")
    args = ["--title", title, "--spine", spine, "--region", region, "--mode", mode]
    if video:
        args += ["--from-video", video]
    else:
        STORIES.mkdir(parents=True, exist_ok=True)
        story = STORIES / f"{key}.txt"
        story.write_text(story_text, encoding="utf-8")
        args += ["--story", str(story)]
    index = _index()
    index[key] = {"unit": f"assembly-run-{key}", "title": title}
    _save_index(index)
    _launch(key, args)
    return key


def _key_for(project_id: str) -> str:
    index = _index()
    for key, entry in index.items():
        if entry.get("project_id") == project_id:
            return key
    index[project_id] = {"unit": f"assembly-run-{project_id}", "title": "", "project_id": project_id}
    _save_index(index)
    return project_id


def resume(project_id: str, approve: list[str]) -> None:
    key = _key_for(project_id)
    args = ["--state", str(RUNS / f"{project_id}.json")]
    for cp in approve:
        args += ["--approve", cp]
    if not (RUNS / f"{key}.log").exists():
        old = logs_by_project().get(project_id)
        (RUNS / f"{key}.log").write_text(f"project {project_id}; (log trước: {old})\n", encoding="utf-8")
    _launch(key, args)


def pause(project_id: str) -> None:
    unit = _index().get(_key_for(project_id), {}).get("unit")
    if unit:
        _systemctl("stop", unit)
