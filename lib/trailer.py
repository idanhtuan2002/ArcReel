"""A trailer cut from a finished film (ADR-0164): hook, escalation, a tease, never the ending.

The film's spoken lines (its subtitles, per episode) are numbered and shown to the model with their place in the
story; the model picks a hook line and 2–5 beats and writes at most two short title cards and an end card. The picks
are checked without the model: they exist, are distinct, beats run in story order, none is in the last part of the
story (no spoiler), each fits the clip limits and the whole trailer has a trailer's length. The cut takes each picked
line whole from its episode's verified final (so no sentence is cut and its burned caption stays whole; a line under
an episode's next-episode card is not picked), with short
sound fades, puts the title cards between the beats and ends on the film's title with the end card; the sound is
mastered to the films' loudness.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lib.screen_text import END_SECONDS, FONT, wrap
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult

type Generate = Callable[[TextGenerationRequest], Awaitable[TextGenerationResult]]

#: A pick must end before this share of the story (the ending is not shown).
SPOILER_LIMIT = 0.7
MIN_SECONDS = 12.0
MAX_SECONDS = 45.0
MAX_LINE_SECONDS = 10.0
CARD_SECONDS = 1.6
CARD_CHARS = 40
END_CARD_CHARS = 70
FADE_IN = 0.06
FADE_OUT = 0.15
#: Sound kept after a line ends, so its last word is not clipped.
TAIL = 0.2
MAX_ATTEMPTS = 3
LOUDNESS = "loudnorm=I=-14:TP=-1.0:LRA=20"

_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})")


class TrailerError(RuntimeError):
    """The trailer could not be planned or cut; the message names why."""


@dataclass(frozen=True)
class Line:
    id: str
    episode: int
    start: float
    end: float
    text: str
    #: Seconds from the start of the story (earlier episodes' lengths included).
    story_at: float


@dataclass(frozen=True)
class Episode:
    number: int
    final: Path
    duration: float
    subtitles: str
    #: Whether the episode ends on a next-episode card (another episode follows).
    has_end_card: bool


class TrailerPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hook: str = Field(description="id of the line that opens the trailer: the most intriguing question or image")
    beats: list[str] = Field(min_length=2, max_length=5, description="ids of the lines that escalate, in story order")
    cards: list[str] = Field(default_factory=list, max_length=2, description="short title-card texts between beats")
    end_card: str = Field(description="one short line under the film's title on the last card")


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            match = _TIME.search(line)
            if match:
                g = [int(x) for x in match.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                body = " ".join(part.strip() for part in lines[i + 1 :] if part.strip())
                if body and end > start:
                    cues.append((start, end, body))
                break
    return cues


def story_lines(episodes: Sequence[Episode]) -> tuple[list[Line], float]:
    """Every spoken line of the film with its id (``E<episode>L<n>``) and place in the story; and the story's length."""
    lines: list[Line] = []
    offset = 0.0
    for episode in sorted(episodes, key=lambda e: e.number):
        for n, (start, end, text) in enumerate(parse_srt(episode.subtitles), start=1):
            lines.append(Line(f"E{episode.number}L{n}", episode.number, start, end, text, offset + start))
        offset += episode.duration
    return lines, offset


def clip_window(line: Line, episode: Episode) -> tuple[float, float]:
    """The part of the episode a picked line is cut from: the whole line and a short tail of sound."""
    return line.start, min(line.end + TAIL, episode.duration)


def _under_end_card(line: Line, episode: Episode) -> bool:
    return episode.has_end_card and line.end > episode.duration - END_SECONDS


def plan_problems(plan: TrailerPlan, lines: Sequence[Line], episodes: Sequence[Episode], total: float) -> list[str]:
    by_id = {line.id: line for line in lines}
    by_number = {e.number: e for e in episodes}
    problems: list[str] = []
    picks = [plan.hook, *plan.beats]
    unknown = [p for p in picks if p not in by_id]
    if unknown:
        return [f"unknown line ids {unknown}; use only the ids listed"]
    if len(set(picks)) != len(picks):
        problems.append("a line is picked twice; every pick must be a different line")
    story_order = [by_id[b].story_at for b in plan.beats]
    if story_order != sorted(story_order):
        problems.append("the beats are not in story order")
    seconds = 0.0
    for pick in picks:
        line = by_id[pick]
        start, stop = clip_window(line, by_number[line.episode])
        if line.story_at + (line.end - line.start) > SPOILER_LIMIT * total:
            problems.append(
                f"{pick} is in the last {round((1 - SPOILER_LIMIT) * 100)}% of the story (it gives away the ending)"
            )
        if _under_end_card(line, by_number[line.episode]):
            problems.append(f"{pick} is under the next-episode card; pick another line")
        if line.end - line.start > MAX_LINE_SECONDS:
            problems.append(f"{pick} is longer than {MAX_LINE_SECONDS:g} s; pick a shorter line")
        seconds += max(0.0, stop - start)
    seconds += CARD_SECONDS * len(plan.cards) + END_SECONDS
    if not MIN_SECONDS <= seconds <= MAX_SECONDS:
        problems.append(
            f"the trailer would last {seconds:.0f} s; keep it between {MIN_SECONDS:g} and {MAX_SECONDS:g} s"
        )
    long_cards = [c for c in plan.cards if len(c) > CARD_CHARS or not c.strip()]
    if long_cards:
        problems.append(f"title cards must be 1–{CARD_CHARS} characters: {long_cards}")
    if not plan.end_card.strip() or len(plan.end_card) > END_CARD_CHARS:
        problems.append(f"the end card must be 1–{END_CARD_CHARS} characters")
    return problems


def _prompt(title: str, lines: Sequence[Line], total: float, problems: Sequence[str]) -> str:
    listing = "\n".join(
        f"{line.id} [{line.story_at / total * 100:.0f}% · {line.end - line.start:.1f}s] {line.text}" for line in lines
    )
    retry = (
        ("\nThe previous plan was refused:\n- " + "\n- ".join(problems) + "\nFix every point.\n") if problems else ""
    )
    return f"""You cut a trailer for the short film "{title}" from its own spoken lines.

Lines (id [place in the story · length] text):
{listing}

Build a beat map: a hook line that makes the viewer ask a question, then 2–5 beats that escalate the conflict, in
story order, ending on a tease. Never show the ending: every pick must be before {SPOILER_LIMIT * 100:.0f}% of the
story. Prefer lines with a person, a decision, a danger or a secret over description. The whole trailer lasts
{MIN_SECONDS:g}–{MAX_SECONDS:g} seconds (the lines' lengths, {CARD_SECONDS:g} s per title card, {END_SECONDS:g} s for
the end card). Title cards are optional, at most two, trailer-like: a few words, no explanation of what the lines
already say, at most {CARD_CHARS} characters. The end card is one short line under the title (at most
{END_CARD_CHARS} characters), an invitation to watch. Write the cards in the language of the lines.
{retry}
Answer with JSON: {{"hook": id, "beats": [ids], "cards": [texts], "end_card": text}}."""


async def plan_trailer(title: str, episodes: Sequence[Episode], generate: Generate) -> TrailerPlan:
    lines, total = story_lines(episodes)
    if not lines or total <= 0:
        raise TrailerError("NO_SPOKEN_LINES")
    problems: list[str] = []
    for _attempt in range(MAX_ATTEMPTS):
        result = await generate(
            TextGenerationRequest(prompt=_prompt(title, lines, total, problems), response_schema=TrailerPlan)
        )
        try:
            plan = TrailerPlan.model_validate(json.loads(result.text))
        except (ValueError, ValidationError) as error:
            problems = [f"the answer is not valid JSON for the schema: {str(error)[:300]}"]
            continue
        problems = plan_problems(plan, lines, episodes, total)
        if not problems:
            return plan
    raise TrailerError("NO_PASSING_PLAN: " + "; ".join(problems)[:300])


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise TrailerError(f"{name} is not installed")
    return found


async def _run(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await process.communicate()
    if process.returncode != 0:
        raise TrailerError(f"ffmpeg failed: {err.decode(errors='replace')[-400:]}")
    return out.decode(errors="replace")


async def probe(final: Path) -> tuple[int, int, float, float]:
    """Width, height, frame rate and duration of a film."""
    out = await _run(
        _tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(final),
    )  # fmt: skip
    data = json.loads(out)
    stream = data["streams"][0]
    num, _, den = str(stream["r_frame_rate"]).partition("/")
    fps = float(num) / float(den or 1)
    return int(stream["width"]), int(stream["height"]), fps, float(data["format"]["duration"])


def _ass_filter(path: Path) -> str:
    escaped = str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return f"ass='{escaped}'"


def card_ass(width: int, height: int, seconds: float, text: str, title: str | None = None) -> str:
    """A centered trailer card: an optional large title over the card text, faded in and out."""
    short = min(width, height)
    title_size, text_size = round(short * 0.11), round(short * 0.085)
    fade = f"{{\\fad(200,{250 if title is None else 0})}}"
    body = "\\N".join(wrap(_text(text), width=20))
    if title is not None:
        heading = "\\N".join(wrap(_text(title), width=18))
        body = f"{{\\fs{title_size}\\b1}}{heading}\\N{{\\fs{round(text_size * 0.5)}}} \\N{{\\fs{text_size}\\b0}}{body}"
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding",
            f"Style: Card,{FONT},{text_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,"
            f"{max(2, round(text_size * 0.06))},2,5,{round(width * 0.08)},{round(width * 0.08)},0,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            f"Dialogue: 0,0:00:00.00,{_clock(seconds)},Card,,0,0,0,,{fade}{body}",
            "",
        ]
    )


def _text(value: str) -> str:
    return " ".join(value.replace("{", "(").replace("}", ")").split())


def _clock(seconds: float) -> str:
    centis = max(0, round(seconds * 100))
    minutes, rest = divmod(centis, 6000)
    secs, cs = divmod(rest, 100)
    return f"0:{minutes:02d}:{secs:02d}.{cs:02d}"


async def _still(final: Path, at: float, target: Path) -> None:
    await _run(
        _tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(final), "-frames:v", "1", str(target)
    )


async def _card(
    text: str,
    seconds: float,
    size: tuple[int, int, float],
    backdrop: Path,
    target: Path,
    work: Path,
    *,
    title: str | None = None,
) -> None:
    """A card over a blurred, darkened still of the film, with silence."""
    width, height, fps = size
    ass = work / (target.stem + ".ass")
    ass.write_text(card_ass(width, height, seconds, text, title), encoding="utf-8")
    look = f"scale={width}:{height},boxblur=24:2,eq=brightness=-0.22:saturation=0.7,fps={fps:g},format=yuv420p"
    await _run(
        _tool("ffmpeg"), "-y", "-v", "error",
        "-loop", "1", "-t", f"{seconds:.3f}", "-i", str(backdrop),
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={seconds:.3f}",
        "-vf", f"{look},{_ass_filter(ass)}", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", str(target),
    )  # fmt: skip


async def _clip(final: Path, start: float, stop: float, size: tuple[int, int, float], target: Path) -> None:
    width, height, fps = size
    length = stop - start
    await _run(
        _tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(final),
        "-vf", f"scale={width}:{height},fps={fps:g},format=yuv420p",
        "-af", f"aresample=48000,afade=t=in:d={FADE_IN},afade=t=out:st={max(0.0, length - FADE_OUT):.3f}:d={FADE_OUT}",
        "-ac", "2", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(target),
    )  # fmt: skip


async def cut_trailer(
    plan: TrailerPlan, episodes: Sequence[Episode], *, title: str, output: Path
) -> list[dict[str, object]]:
    """Cut the planned trailer into ``output`` (MP4); returns the cut list (episode, start, end, text or card)."""
    lines, _total = story_lines(episodes)
    by_id = {line.id: line for line in lines}
    by_number = {e.number: e for e in episodes}
    first = by_number[by_id[plan.hook].episode]
    width, height, fps, _ = await probe(first.final)
    size = (width, height, fps)
    order: list[tuple[str, str]] = [("line", plan.hook)]
    cards = list(plan.cards)
    for i, beat in enumerate(plan.beats):
        if cards and (i == 0 or i == len(plan.beats) - 1):
            order.append(("card", cards.pop(0)))
        order.append(("line", beat))
    order.extend(("card", c) for c in cards)
    cuts: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="trailer-") as tmp:
        work = Path(tmp)
        parts: list[Path] = []
        backdrops: list[Path] = []
        for n, pick in enumerate([plan.hook, *plan.beats]):
            line = by_id[pick]
            still = work / f"still_{n:02d}.png"
            await _still(by_number[line.episode].final, (line.start + line.end) / 2, still)
            backdrops.append(still)
        shown = 0
        for n, (kind, value) in enumerate(order):
            part = work / f"part_{n:02d}.mp4"
            if kind == "card":
                await _card(value, CARD_SECONDS, size, backdrops[min(shown, len(backdrops) - 1)], part, work)
                cuts.append({"card": value, "seconds": CARD_SECONDS})
            else:
                line = by_id[value]
                episode = by_number[line.episode]
                start, stop = clip_window(line, episode)
                await _clip(episode.final, start, stop, size, part)
                cuts.append({"line": line.id, "episode": line.episode, "start": start, "end": stop, "text": line.text})
                shown += 1
            parts.append(part)
        end = work / "part_end.mp4"
        await _card(plan.end_card, END_SECONDS, size, backdrops[0], end, work, title=title)
        cuts.append({"card": f"{title} — {plan.end_card}", "seconds": END_SECONDS})
        parts.append(end)
        inputs: list[str] = []
        for part in parts:
            inputs += ["-i", str(part)]
        joined = "".join(f"[{i}:v][{i}:a]" for i in range(len(parts)))
        output.parent.mkdir(parents=True, exist_ok=True)
        await _run(
            _tool("ffmpeg"), "-y", "-v", "error", *inputs,
            "-filter_complex", f"{joined}concat=n={len(parts)}:v=1:a=1[v][a];[a]{LOUDNESS},aresample=48000[m]",
            "-map", "[v]", "-map", "[m]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output),
        )  # fmt: skip
    return cuts


__all__ = [
    "Episode",
    "Line",
    "TrailerError",
    "TrailerPlan",
    "card_ass",
    "clip_window",
    "cut_trailer",
    "parse_srt",
    "plan_problems",
    "plan_trailer",
    "probe",
    "story_lines",
]
