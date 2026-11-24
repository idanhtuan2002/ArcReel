"""Drive one DramaClaw film from a story file to a downloaded episode (ASSEMBLY_PLAN M2, §5).

The connector plays DramaClaw's own Hermes playbooks (`vendor/dramaclaw/hermes/skills/dramaclaw/playbooks/`) in their
"auto-advance" mode: read `pipeline/status.next_step`, start the one write task that step needs through DramaClaw's
toolset (`assembly.connector.dramaclaw_tools`), wait for it, and read the status again. Rules taken from the playbooks:
one write task at a time; a task that reports `completed` while the step does not advance is an anomaly and stops the
run (`references/async-tasks.md` "检查点异常处理"); failures report the task's own error. Our additions are only what
the Hermes agent does with its own judgement: Vietnamese voice casting (D9, D18) and missing `face_prompt`s.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from assembly.connector.dramaclaw_tools import DramaClawTools

RUNNING = {"queued", "running", "pending"}
FAILED = {"failed", "cancelled"}
POLL_SECONDS = 10
MAX_STEP_SECONDS = 6 * 3600
MISSING_TASK_SECONDS = 300
TRANSIENT_PAUSES = (120, 300, 600, 900)
_TRANSIENT = ("429", "rate-limited", "rate limit", "temporarily", "input_value='error'", "503", "502", "timed out")


def _transient(message: str) -> bool:
    return any(marker in message for marker in _TRANSIENT)


class RunStopped(RuntimeError):
    """The run cannot continue without a person; the message says why."""


class CheckpointReached(RunStopped):
    """A Hermes playbook checkpoint: the sponsor reviews in DramaClaw's UI, then resumes with `--approve CPn`."""


# Checkpoints of the Hermes playbooks (init.md CP1, episode.md CP2-CP5), keyed by the step they come before.
# CP1 stops in both modes ("自动推进…到 CP1 也必须停下"); CP2-CP5 stop in step mode only.
CHECKPOINTS: dict[str, tuple[str, str]] = {
    "identity_plan": (
        "CP1",
        "chân dung nhân vật chính, phân loại nhân vật, tên các tập (DramaClaw → project → Nhân vật / Tập)",
    ),
    "sketch_generation": ("CP2", "danh sách beat: cảnh, hình ảnh, lời thoại (DramaClaw → tập → Beats)"),
    "tts": ("CP3", "khung hình đầu của các beat (DramaClaw → tập → Khung hình đầu)"),
    "single_video": ("CP4", "âm thanh và giọng từng beat (DramaClaw → tập → Âm thanh)"),
    "done": ("CP5", "phim hoàn chỉnh của tập (file trong ~/assembly-data/runs/films/)"),
}


@dataclass
class RunState:
    project_id: str
    title: str
    spine: str
    mode: str = "auto"  # "auto" | "step" (ASSEMBLY_PLAN D21)
    approved: list[str] = field(default_factory=list)
    episodes_done: list[int] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    voices_cast: dict[str, str] = field(default_factory=dict)
    finals: dict[str, str] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> RunState:
        return cls(**json.loads(path.read_text(encoding="utf-8")))


def chapter_text(text: str) -> str:
    """DramaClaw's structured ingest splits on `Chapter N`; Vietnamese `Chương N` headings are rewritten to it."""
    out = re.sub(r"(?im)^\s*#*\s*ch(ư|u)ơng\s+(\d+)\s*[:.\-–]?\s*", lambda m: f"Chapter {m.group(2)} ", text)
    if not re.search(r"(?m)^Chapter \d+", out):
        out = "Chapter 1\n\n" + out.strip() + "\n"
    return out


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _has_media(item: dict[str, Any], kind: str) -> bool:
    return any(str(v or "").strip() for k, v in item.items() if kind in k and ("url" in k or "path" in k))


def _ok(result: Any, what: str) -> Any:
    if not isinstance(result, dict) or result.get("ok") is False:
        error = result.get("chat_error") or result.get("error") if isinstance(result, dict) else result
        raise RunStopped(f"{what}: {error}")
    return result.get("data", result)


def _latest_listed_status(tools: DramaClawTools, task_type: str, episode: int) -> str:
    """Status of the newest task of this type and episode in the project task list (scope-agnostic)."""
    listed = tools.call("dramaclaw_list_tasks", task_type=task_type, episode=episode)
    items = listed.get("data") if isinstance(listed, dict) else None
    items = items if isinstance(items, list) else (items or {}).get("tasks", [])
    for item in items:
        if item.get("task_type") == task_type and int(item.get("episode") or 0) == episode:
            return str(item.get("status") or "").lower()
    return ""


def wait_task(tools: DramaClawTools, task_type: str, episode: int, **extra: Any) -> dict[str, Any]:
    """Poll one DramaClaw task until it ends (async-tasks reference: queued/running/pending vs completed/failed)."""
    started = time.monotonic()
    while True:
        task = tools.call("dramaclaw_get_task", task_type=task_type, episode=episode, **extra)
        data = task.get("data") if isinstance(task, dict) else None
        status = str((data or {}).get("status") or "").lower()
        if status == "completed":
            return data or {}
        if status in FAILED:
            reason = (data or {}).get("chat_error") or (data or {}).get("error") or (data or {}).get("error_code")
            raise RunStopped(f"{task_type} ep{episode} {extra or ''} {status}: {reason}")
        if not status and isinstance(task, dict) and task.get("ok") is False:
            raise RunStopped(f"{task_type} ep{episode}: {task.get('error')}")
        if not status:
            listed = _latest_listed_status(tools, task_type, episode)
            if listed == "completed":
                return data or {}
            if listed in FAILED:
                raise RunStopped(f"{task_type} ep{episode}: listed task {listed}")
            if listed in RUNNING:
                started = time.monotonic()
        if not status and time.monotonic() - started > MISSING_TASK_SECONDS:
            raise RunStopped(f"{task_type} ep{episode} {extra or ''}: no such task after {MISSING_TASK_SECONDS}s")
        if time.monotonic() - started > MAX_STEP_SECONDS:
            raise RunStopped(f"{task_type} ep{episode} still {status or 'unknown'} after {MAX_STEP_SECONDS}s")
        time.sleep(POLL_SECONDS)


class FilmRun:
    def __init__(
        self,
        tools: DramaClawTools,
        state: RunState,
        state_path: Path,
        *,
        out_dir: Path,
        cast_voices: Callable[[FilmRun], None] | None = None,
        fill_face_prompts: Callable[[FilmRun, list[dict[str, Any]]], None] | None = None,
        rewrite_narration: Callable[[FilmRun, int], None] | None = None,
        log: Callable[[str], None] = print,
    ) -> None:
        self.tools = tools
        self.state = state
        self.state_path = state_path
        self.out_dir = out_dir
        self.cast_voices = cast_voices
        self.fill_face_prompts = fill_face_prompts
        self.rewrite_narration = rewrite_narration
        self.log = log

    # --- DramaClaw access -------------------------------------------------------------------------------------------

    def status(self, episode: int | None = None) -> dict[str, Any]:
        args = {"episode": episode} if episode else {}
        return _ok(self.tools.call("dramaclaw_pipeline_status", **args), "pipeline status")

    def wait(self, task_type: str, episode: int, **extra: Any) -> dict[str, Any]:
        return wait_task(self.tools, task_type, episode, **extra)

    def start(self, tool: str, what: str, /, **args: Any) -> Any:
        """Start one write task; when DramaClaw answers with a task type the task is awaited (async-tasks rule)."""
        return self.start_and_wait(tool, what, int(args.get("episode") or 0), **args)

    def start_and_wait(self, tool: str, what: str, episode: int, /, **args: Any) -> dict[str, Any]:
        """Start one async task and wait on the task type and scope its own start response names."""
        started = self.tools.call(tool, **args)
        data = _ok(started, what)
        task_type = (started.get("task_type") if isinstance(started, dict) else None) or (data or {}).get("task_type")
        scope = (started.get("scope") if isinstance(started, dict) else None) or (data or {}).get("scope")
        if not task_type:
            return data or {}
        key = str((started.get("task_key") if isinstance(started, dict) else None) or "")
        match = re.match(r"^task:[^:]+:project:[^:]+:(\d+):", key)
        task_episode = int(match.group(1)) if match else episode
        return self.wait(str(task_type), task_episode, **({"scope": scope} if scope else {}))

    def record(self, step: str, episode: int, note: str = "") -> None:
        self.state.steps.append({"step": step, "episode": episode, "note": note, "at": time.strftime("%F %T")})
        self.state.save(self.state_path)
        self.log(f"[{time.strftime('%T')}] ep{episode} {step} done {note}")

    # --- global stage (init playbook, Steps 4-7) -------------------------------------------------------------------

    def characters(self) -> list[dict[str, Any]]:
        data = _ok(self.tools.request("GET", f"/projects/{self.state.project_id}/characters"), "characters")
        return data if isinstance(data, list) else data.get("characters", [])

    def prepare_characters(self) -> None:
        """Init playbook Step 5 (face prompts) and Vietnamese casting; also run on resume if not done yet."""
        chars = self.characters()
        if self.fill_face_prompts:
            self.fill_face_prompts(self, [c for c in chars if not str(c.get("face_prompt") or "").strip()])
        if self.cast_voices and not self.state.voices_cast:
            self.cast_voices(self)

    def grade_characters(self, min_mentions: int = 3) -> None:
        """Init playbook Step 6.5: core and recurring named characters become `is_main` when extraction set none.

        The Hermes agent grades by judgement; here a character named at least `min_mentions` times across the
        episodes' raw content counts as recurring.
        """
        chars = [c for c in self.characters() if not c.get("is_main")]
        if not chars:
            return
        text = ""
        for ep in self.episodes():
            number = ep.get("number") or ep.get("episode") or ep.get("id")
            raw = self.tools.request("GET", f"/projects/{self.state.project_id}/episodes/{number}/raw-content")
            text += json.dumps(raw.get("data"), ensure_ascii=False)
        for char in chars:
            bare = re.sub(r"^(ông|bà|anh|chị|cô|chú|bác|em|cậu|dì|thím)\s+", "", str(char["name"]), flags=re.I)
            if text.count(bare) >= min_mentions:
                patched = self.tools.request(
                    "PATCH",
                    f"/projects/{self.state.project_id}/characters/{quote(str(char['name']), safe='')}",
                    body={"is_main": True},
                )
                _ok(patched, f"grade {char['name']}")

    def episodes(self) -> list[dict[str, Any]]:
        data = _ok(self.tools.request("GET", f"/projects/{self.state.project_id}/episodes"), "episodes")
        return data if isinstance(data, list) else data.get("episodes", [])

    def step_global(self, step: str) -> None:
        if step == "build_characters":
            self.start("dramaclaw_build_characters", "build characters")
            self.wait("build_characters", 0)
            chars = self.characters()
            if not chars:
                raise RunStopped("build_characters completed with no characters (playbook: anomaly)")
            self.prepare_characters()
            self.record(step, 0, f"{len(chars)} characters")
        elif step == "build_episodes":
            self.start("dramaclaw_plan_episodes", "plan episodes", planning_mode="chapters")
            self.wait("build_episodes", 0)
            self.grade_characters()
            self.record(step, 0, f"{len(self.episodes())} episodes")
        elif step == "portraits":
            # pipeline/status counts portraits of main characters only; one-off characters are skipped (init playbook
            # Step 6.5 grading), which also spares the once-only image pool.
            self.grade_characters()
            for char in self.characters():
                if not char.get("is_main") or _has_media(char, "portrait"):
                    continue
                self.start_and_wait("dramaclaw_generate_portrait", f"portrait {char['name']}", 0, name=char["name"])
            self.record(step, 0)
        else:
            raise RunStopped(f"no connector action for global step {step!r}")

    # --- episode stage (episode playbook, Steps 8-21) ---------------------------------------------------------------

    def beats(self, episode: int) -> list[dict[str, Any]]:
        data = _ok(self.tools.request("GET", f"/projects/{self.state.project_id}/episodes/{episode}/beats"), "beats")
        return data if isinstance(data, list) else data.get("beats", [])

    def step_episode(self, step: str, episode: int) -> None:
        if step == "voice_setup":
            # pipeline/status (v2.1.3) stops here while a narrator or character voice reference is missing.
            if not self.cast_voices:
                raise RunStopped("voice references missing and no casting configured")
            self.state.voices_cast = {}
            self.cast_voices(self)
        elif step == "identity_plan":
            self.start("dramaclaw_plan_identities", "plan identities", episode=episode)
            self.start("dramaclaw_plan_props", "plan props", episode=episode)
        elif step == "identity_images":
            for char in [c for c in self.characters() if c.get("is_main")]:
                ids = _ok(
                    self.tools.request(
                        "GET",
                        f"/projects/{self.state.project_id}/characters/{quote(str(char['name']), safe='')}/identities",
                    ),
                    "identities",
                )
                for ident in ids if isinstance(ids, list) else ids.get("identities", []):
                    if _has_media(ident, "image"):
                        continue
                    self.start_and_wait(
                        "dramaclaw_generate_identity_image",
                        f"identity image {char['name']}/{ident.get('id')}",
                        episode,
                        name=char["name"],
                        identity_id=ident.get("identity_id") or ident["id"],
                    )
        elif step == "script_writer":
            # DramaClaw's own rewrite writes zh/en narration only (`utils/source_language.py`); narrated films use its
            # rewriter ported with a Vietnamese output rule (`assembly.connector.rewriter`), saved the way DramaClaw's
            # route saves it. Drama films keep the screenplay lines (no rewrite).
            adapted = self.tools.request("GET", f"/projects/{self.state.project_id}/episodes/{episode}/adapted-content")
            current = str((adapted.get("data") or {}).get("content") or "")
            if self.state.spine == "narrated" and self.rewrite_narration and (not current.strip() or _has_cjk(current)):
                self.rewrite_narration(self, episode)
            elif self.state.spine != "narrated" and current.strip():
                _ok(
                    self.tools.request(
                        "DELETE", f"/projects/{self.state.project_id}/episodes/{episode}/adapted-content"
                    ),
                    "clear adapted content",
                )
            self.start("dramaclaw_generate_script", "script", episode=episode)
            self.wait("script_writer", episode)
        elif step == "sketch_generation":
            # The toolset assigns colours first and, with its default grid_index -1, generates every grid in one task.
            self.start("dramaclaw_generate_sketches", "sketches", episode=episode)
        elif step == "coloring":
            self.start("dramaclaw_detect_sketch_identities", "detect identities", episode=episode)
        elif step == "global_optimize_video":
            self.start("dramaclaw_optimize_video_global", "optimize video", episode=episode)
            self.wait("global_optimize_video", episode)
        elif step == "selected_regen":
            beats = [int(b["beat_number"]) for b in self.beats(episode) if int(b.get("beat_number") or 0) > 0]
            self.start("dramaclaw_render_first_frames", "first frames", episode=episode, beat_indices=beats)
            self.wait("selected_regen", episode)
        elif step == "tts":
            self.start("dramaclaw_generate_audio", "audio", episode=episode)
            self.wait("audio_generation_indextts2", episode)
        elif step == "single_video":
            for beat in self.beats(episode):
                number = int(beat.get("beat_number") or 0)
                if number <= 0 or beat.get("video_url") or beat.get("video_path"):
                    continue
                self.start("dramaclaw_start_single_video", f"video beat {number}", episode=episode, beat=number)
                self.wait("single_video", episode, beat_num=number)
        elif step == "compose_episode":
            self.start("dramaclaw_compose_episode", "compose", episode=episode)
            self.wait("compose_episode", episode)
            self.download_final(episode)
        else:
            raise RunStopped(f"no connector action for episode step {step!r}")
        self.record(step, episode)

    def download_final(self, episode: int) -> Path:
        final = _ok(self.tools.call("dramaclaw_get_final_video", episode=episode), "final video")
        url = str((final or {}).get("video_url") or "")
        if not url:
            raise RunStopped(f"episode {episode}: compose completed but no final video (playbook: anomaly)")
        if url.startswith("/"):
            url = self.tools.plugin._base_url() + url
        target = self.out_dir / f"{self.state.project_id}-ep{episode:02d}.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, timeout=600) as response:
            response.raise_for_status()
            with target.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
        self.state.finals[str(episode)] = str(target)
        self.state.save(self.state_path)
        return target

    def run_step_with_retries(self, step: str, episode: int) -> None:
        """Free text pools rate-limit by the minute; a step that failed on one is run again after a pause."""
        for pause in (*TRANSIENT_PAUSES, None):
            try:
                if episode <= 0:
                    self.step_global(step)
                else:
                    self.step_episode(step, episode)
                return
            except RunStopped as stop:
                if pause is None or not _transient(str(stop)) or isinstance(stop, CheckpointReached):
                    raise
                self.log(
                    f"[{time.strftime('%T')}] ep{episode} {step}: transient failure, retry in {pause}s ({stop})"[:400]
                )
                time.sleep(pause)

    def checkpoint(self, step: str, episode: int) -> None:
        point = CHECKPOINTS.get(step)
        if not point:
            return
        name, what = point
        key = name if name == "CP1" else f"{name}-ep{episode}"
        if key in self.state.approved or (name != "CP1" and self.state.mode != "step"):
            return
        raise CheckpointReached(f"{key}: xem {what}; duyệt xong chạy tiếp với --approve {key}")

    # --- the loop ---------------------------------------------------------------------------------------------------

    def run(self, max_rounds: int = 400) -> RunState:
        last: tuple[str, int] | None = None
        repeated = False
        if self.characters():
            self.prepare_characters()
            if self.episodes():
                self.grade_characters()
        for _ in range(max_rounds):
            status = self.status()
            step = str(status.get("next_step") or "")
            episode = int(status.get("current_episode") or 0)
            if not step:
                return self.state
            if step in {"ingest_fast", "configure", "ingest"}:
                raise RunStopped(f"project not prepared: next_step={step}")
            self.checkpoint(step, episode)
            if step == "done":
                return self.state
            if (step, episode) == last:
                if repeated:
                    raise RunStopped(
                        f"{step} ep{episode} completed but the pipeline did not advance (playbook: anomaly)"
                    )
                # A step can complete partially when free pools fail some calls (e.g. 10/18 beats); run it once more.
                repeated = True
                self.log(f"[{time.strftime('%T')}] ep{episode} {step}: did not advance, one more run after a pause")
                time.sleep(TRANSIENT_PAUSES[0])
            else:
                repeated = False
            last = (step, episode)
            self.run_step_with_retries(step, episode)
        raise RunStopped(f"no end after {max_rounds} rounds")
