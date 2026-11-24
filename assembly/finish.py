"""Finish post-stage (ASSEMBLY_PLAN M4.1): the old app's finishing units run on DramaClaw's composed episode.

DramaClaw v2.1.3 records `add_subtitles` on compose but burns nothing (`task_backend/runners/video.py`), and its
`add_bgm` is off in the Hermes toolset. The film is handed whole, as one unit with its own sound, to
`lib.presentation_renderer.render_presentations`: captions from the beats' narration (each beat lasts its line's audio,
which is how compose cuts beats), an ACE-Step music bed (`lib.music_bed`) ducked under the speech, loudness to
−14 LUFS, and the renderer's own checks, SRT and manifest.

`python -m assembly.finish --state ~/assembly-data/runs/<project>.json [--episode 1]`
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from assembly.connector.dramaclaw_tools import DramaClawTools
from assembly.connector.film import RunState
from lib.music_bed import MusicCue, MusicUnavailable, cue_for, music_service_from_env
from lib.presentation_renderer import RenderContract, RenderCue, RenderInput, RenderUnit, render_presentations

MICRO = 1_000_000
FILMS = Path(os.environ.get("ASSEMBLY_FILMS_DIR", "/mnt/arcreel/D/ArcReel/assembly/films"))
NEWAPI = os.environ.get("ASSEMBLY_NEWAPI_URL", "http://127.0.0.1:3000/v1")
MUSIC_ENV = {"ARCREEL_MUSIC_URL": "http://127.0.0.1:8001", "ARCREEL_MUSIC_FREE_URLS": "http://127.0.0.1:8188/free"}
# Used when no text model answers: a quiet, neutral underscore that sits under narration.
DEFAULT_MUSIC = {
    "music_caption": "gentle cinematic underscore, soft piano and warm strings, hopeful, light",
    "music_bpm": 84,
}
MUSIC_PROMPT = (
    "You choose background music for a short narrated film. Read the narration and answer with JSON only: "
    '{{"music_caption": "<English: genre, mood, instruments, texture; instrumental, no vocals>", '
    '"music_bpm": <integer 60-140>}}.\nTitle: {title}\nNarration:\n{text}'
)


def caption_cues(beats: Sequence[Mapping[str, Any]], film_seconds: float) -> tuple[RenderCue, ...]:
    """One cue per beat's narration; beat lengths are their audio lengths, scaled to the composed film."""
    spans = [
        (str(b.get("narration_segment") or "").strip(), float(b.get("audio_duration_seconds") or 0)) for b in beats
    ]
    total = sum(seconds for _, seconds in spans)
    if total <= 0:
        return ()
    scale, cursor, cues = film_seconds / total, 0.0, []
    for text, seconds in spans:
        start, end = cursor, cursor + seconds * scale
        cursor = end
        if text and end > start:
            cues.append(RenderCue(round(start * MICRO), min(round(end * MICRO), round(film_seconds * MICRO)), text))
    return tuple(cues)


def music_overview(title: str, beats: Sequence[Mapping[str, Any]], *, token: str) -> dict[str, Any]:
    """The film's music caption and tempo from one text-model call; the default when no model answers."""
    text = "\n".join(str(b.get("narration_segment") or "") for b in beats)[:4000]
    for model in ("DC-freezone-translator-LLM", "DC-freezone-vision-LLM"):
        try:
            response = httpx.post(
                f"{NEWAPI}/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "model": model,
                    "max_tokens": 2000,
                    "messages": [{"role": "user", "content": MUSIC_PROMPT.format(title=title, text=text)}],
                },
                timeout=120,
            )
            content = response.json()["choices"][0]["message"]["content"] or ""
            found = json.loads(content[content.index("{") : content.rindex("}") + 1])
            if isinstance(found.get("music_caption"), str) and isinstance(found.get("music_bpm"), int):
                return {"music_caption": found["music_caption"], "music_bpm": found["music_bpm"], "model": model}
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
            continue
    return {**DEFAULT_MUSIC, "model": "default"}


def _seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return float(out.strip())


def _size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    width, height = out.strip().split(",")[:2]
    return int(width), int(height)


def finish_episode(
    film: Path,
    beats: Sequence[Mapping[str, Any]],
    out_dir: Path,
    *,
    music: Path | None,
    episode: int,
    title: str | None = None,
) -> dict[str, Any]:
    seconds = _seconds(film)
    width, height = _size(film)
    unit = RenderUnit(
        unit_id="dramaclaw-episode",
        video_path=film,
        video_start_us=0,
        duration_us=round(seconds * MICRO),
        video_audio=True,
        video_gain=1.0,
        cues=caption_cues(beats, seconds),
    )
    contract = RenderContract(
        width=width,
        height=height,
        fps=30,
        min_seconds=1,
        max_seconds=3600,
        requires_narration=False,
        requires_subtitles=True,
    )
    receipt = render_presentations(
        episode=RenderInput(episode=episode, units=(unit,), music_path=music, captions=True, title_card=title),
        output_dir=out_dir,
        contract=contract,
    )
    manifest = json.loads(receipt.manifest_path.read_text(encoding="utf-8"))
    return {
        "final": str(receipt.final_path),
        "subtitles": str(receipt.subtitle_path),
        "manifest": str(receipt.manifest_path),
        "seconds": receipt.duration_seconds,
        "loudness": manifest.get("loudness"),
        "music": manifest.get("music"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    from assembly.connector.setup import _relay_token

    parser = argparse.ArgumentParser(prog="python -m assembly.finish")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--episode", type=int, default=1)
    parser.add_argument("--no-music", action="store_true")
    args = parser.parse_args(argv)
    state = RunState.load(args.state)
    film = Path(state.finals[str(args.episode)])
    beats = DramaClawTools(state.project_id).request(
        "GET", f"/projects/{state.project_id}/episodes/{args.episode}/beats"
    )
    beats = beats.get("data") or []
    music: Path | None = None
    overview: dict[str, Any] = {}
    if not args.no_music:
        overview = music_overview(state.title, beats, token=_relay_token())
        cue: MusicCue | None = cue_for({"overview": overview}, _seconds(film))
        service = music_service_from_env({**MUSIC_ENV, **os.environ})
        if cue and service:
            try:
                music = asyncio.run(service.render(cue, FILMS / "music" / f"{cue.digest()}.wav"))
            except MusicUnavailable as error:
                print(f"music skipped: {error}", flush=True)
    out = FILMS / f"{state.project_id}-ep{args.episode:02d}-finished"
    result = finish_episode(film, beats, out, music=music, episode=args.episode)
    result["music_overview"] = overview
    state.finished[str(args.episode)] = result
    state.save(args.state)
    print(f"FINISHED: {json.dumps(result, ensure_ascii=False)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
