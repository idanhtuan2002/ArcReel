"""Audiobook and sleep-story rendering from a story manuscript (ADR-0159).

A committed story's exported Markdown (``# title``, ``## chapter``, ``> blurb``, ``* * *`` scene breaks, paragraphs) is
read aloud chapter by chapter: each paragraph is cut into sentence-bounded segments that one TTS call speaks, every
segment is cached by the digest of its text and voice (a re-run speaks only what is missing), and ffmpeg joins them
with pauses, lays an optional music bed under the voice, masters the loudness and writes an M4B with chapter marks, an
MP3, an MP4 (cover still + audio) and the chapter timestamps a video description takes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

#: The most characters one TTS call speaks: whole sentences up to this size (a longer sentence is spoken alone).
SEGMENT_CHARS = 400
SAMPLE_RATE = 24000
_SCENE_BREAK = "* * *"
_SENTENCE = re.compile(r"(?<=[.!?…»”\"])\s+")


@dataclass(frozen=True)
class Chapter:
    title: str
    #: Paragraph groups; a scene break starts a new group.
    scenes: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class Book:
    title: str
    chapters: tuple[Chapter, ...]


@dataclass(frozen=True)
class AudiobookPreset:
    name: str
    sentence_pause: float
    paragraph_pause: float
    scene_pause: float
    chapter_pause: float
    #: Speech tempo (ffmpeg ``atempo``); 1.0 keeps the voice as spoken.
    tempo: float
    #: Music bed level under the voice, in dB.
    music_db: float
    #: Integrated loudness target of the master, LUFS.
    loudness: float
    #: Seconds of fade-out at the end.
    fade_out: float
    music_caption: str


PRESETS: dict[str, AudiobookPreset] = {
    "standard": AudiobookPreset(
        "standard",
        0.35,
        0.7,
        1.4,
        2.5,
        1.0,
        -26.0,
        -18.0,
        3.0,
        "gentle cinematic underscore, soft piano and strings, unobtrusive, steady",
    ),
    "sleep": AudiobookPreset(
        "sleep",
        0.6,
        1.2,
        2.2,
        4.0,
        0.92,
        -24.0,
        -23.0,
        20.0,
        "slow ambient lullaby, soft warm pads and distant piano, very calm, no drums",
    ),
}


def parse_manuscript(markdown: str) -> Book:
    """The book in an exported manuscript: the ``#`` title, ``##`` chapters, scene groups split at ``* * *``; the
    blurb (``>``) is not narrated. A manuscript without chapters is one chapter titled by the book."""
    title = ""
    chapters: list[Chapter] = []
    chapter_title: str | None = None
    scenes: list[list[str]] = [[]]

    def close() -> None:
        groups = tuple(tuple(group) for group in scenes if group)
        if groups:
            chapters.append(Chapter(chapter_title if chapter_title is not None else title, groups))

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line or line.startswith(">"):
            continue
        if line.startswith("## "):
            close()
            chapter_title, scenes = line[3:].strip(), [[]]
        elif line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line == _SCENE_BREAK:
            scenes.append([])
        elif not line.startswith("#"):
            scenes[-1].append(line)
    close()
    return Book(title=title, chapters=tuple(chapters))


def segments(paragraph: str, limit: int = SEGMENT_CHARS) -> list[str]:
    """Sentence-bounded pieces of at most ``limit`` characters (a longer sentence is its own piece)."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE.split(paragraph.strip()):
        if current and len(current) + 1 + len(sentence) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


Speak = Callable[[str, Path], Awaitable[None]]


@dataclass
class AudiobookResult:
    m4b: Path
    mp3: Path
    mp4: Path | None
    chapters: list[tuple[str, float]] = field(default_factory=list)
    timestamps: Path | None = None
    duration: float = 0.0
    spoken_segments: int = 0
    cached_segments: int = 0


def _ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found is None:
        raise RuntimeError("ffmpeg is not installed")
    return found


async def _run(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, err = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode(errors='replace')[-400:]}")


async def _duration(path: Path) -> float:
    probe = shutil.which("ffprobe")
    if probe is None:
        raise RuntimeError("ffprobe is not installed")
    process = await asyncio.create_subprocess_exec(
        probe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await process.communicate()
    return float(out.decode().strip() or 0)


async def _normalize(source: Path, target: Path, tempo: float) -> None:
    """One segment as mono 24 kHz PCM at the preset's tempo."""
    filters = f"aresample={SAMPLE_RATE}" + (f",atempo={tempo}" if abs(tempo - 1.0) > 1e-3 else "")
    await _run(
        _ffmpeg(), "-y", "-v", "error", "-i", str(source), "-ac", "1", "-af", filters, "-c:a", "pcm_s16le", str(target)
    )


async def _silence(target: Path, seconds: float) -> None:
    await _run(
        _ffmpeg(),
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={SAMPLE_RATE}:cl=mono",
        "-t",
        f"{seconds:.3f}",
        "-c:a",
        "pcm_s16le",
        str(target),
    )


async def _concat(parts: Sequence[Path], target: Path) -> None:
    listing = target.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    await _run(
        _ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(target)
    )


def segment_digest(text: str, voice_key: str) -> str:
    return hashlib.sha256(f"{voice_key}\n{text}".encode()).hexdigest()[:32]


async def render_audiobook(
    book: Book,
    work: Path,
    *,
    speak: Speak,
    voice_key: str,
    preset: AudiobookPreset,
    music: Path | None = None,
    cover: Path | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> AudiobookResult:
    """Speak ``book`` into ``work`` and write the audiobook files; segments already spoken for ``voice_key`` are
    reused. ``speak(text, path)`` writes one WAV (any rate)."""
    cache = work / "segments"
    await asyncio.to_thread(cache.mkdir, parents=True, exist_ok=True)
    pauses = {}
    for name, seconds in (
        ("sentence", preset.sentence_pause),
        ("paragraph", preset.paragraph_pause),
        ("scene", preset.scene_pause),
        ("chapter", preset.chapter_pause),
    ):
        pauses[name] = work / f"pause-{name}.wav"
        await _silence(pauses[name], seconds)

    plan: list[tuple[int, list[tuple[str, str]]]] = []  # (chapter index, [(kind, text)])
    for index, chapter in enumerate(book.chapters):
        items: list[tuple[str, str]] = [("text", chapter.title), ("pause", "chapter")]
        for s, scene in enumerate(chapter.scenes):
            if s:
                items.append(("pause", "scene"))
            for p, paragraph in enumerate(scene):
                if p:
                    items.append(("pause", "paragraph"))
                for k, piece in enumerate(segments(paragraph)):
                    if k:
                        items.append(("pause", "sentence"))
                    items.append(("text", piece))
        plan.append((index, items))
    total = sum(1 for _, items in plan for kind, _t in items if kind == "text")
    done = spoken = cached = 0
    chapter_files: list[Path] = []
    for index, items in plan:
        parts: list[Path] = []
        for kind, value in items:
            if kind == "pause":
                parts.append(pauses[value])
                continue
            digest = segment_digest(value, voice_key)
            ready = cache / f"{digest}.wav"
            if ready.is_file():
                cached += 1
            else:
                raw = cache / f"{digest}.raw.wav"
                await speak(value, raw)
                await _normalize(raw, ready, preset.tempo)
                raw.unlink(missing_ok=True)
                spoken += 1
            parts.append(ready)
            done += 1
            if on_progress is not None:
                on_progress(done, total)
        chapter_wav = work / f"chapter-{index + 1:02d}.wav"
        await _concat([*parts, pauses["chapter"]], chapter_wav)
        chapter_files.append(chapter_wav)

    voice = work / "voice.wav"
    await _concat(chapter_files, voice)
    starts: list[tuple[str, float]] = []
    offset = 0.0
    for chapter, path in zip(book.chapters, chapter_files, strict=True):
        starts.append((chapter.title, offset))
        offset += await _duration(path)
    duration = offset

    master = work / "master.wav"
    fade_start = max(0.0, duration - preset.fade_out)
    if music is not None and await asyncio.to_thread(music.is_file):
        graph = (
            f"[1:a]aresample={SAMPLE_RATE},aloop=loop=-1:size=2e9,atrim=0:{duration:.3f},volume={preset.music_db}dB[bed];"
            f"[0:a][bed]amix=inputs=2:duration=first:normalize=0,"
            f"loudnorm=I={preset.loudness}:TP=-1.5:LRA=11,afade=t=out:st={fade_start:.3f}:d={preset.fade_out:.3f},"
            f"atrim=0:{duration:.3f}[out]"
        )
        await _run(
            _ffmpeg(),
            "-y",
            "-v",
            "error",
            "-i",
            str(voice),
            "-i",
            str(music),
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-ar",
            "44100",
            str(master),
        )
    else:
        await _run(
            _ffmpeg(),
            "-y",
            "-v",
            "error",
            "-i",
            str(voice),
            "-af",
            f"loudnorm=I={preset.loudness}:TP=-1.5:LRA=11,afade=t=out:st={fade_start:.3f}:"
            f"d={preset.fade_out:.3f},atrim=0:{duration:.3f}",
            "-ar",
            "44100",
            str(master),
        )

    metadata = work / "chapters.ffmeta"
    lines = [";FFMETADATA1", f"title={_escape(book.title)}"]
    for i, (title, start) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else duration
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={int(start * 1000)}",
            f"END={int(end * 1000)}",
            f"title={_escape(title)}",
        ]
    metadata.write_text("\n".join(lines) + "\n", encoding="utf-8")
    m4b = work / "audiobook.m4b"
    await _run(
        _ffmpeg(),
        "-y",
        "-v",
        "error",
        "-i",
        str(master),
        "-i",
        str(metadata),
        "-map_metadata",
        "1",
        "-map_chapters",
        "1",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        str(m4b),
    )
    mp3 = work / "audiobook.mp3"
    await _run(_ffmpeg(), "-y", "-v", "error", "-i", str(master), "-c:a", "libmp3lame", "-b:a", "128k", str(mp3))
    mp4: Path | None = None
    if cover is not None and await asyncio.to_thread(cover.is_file):
        mp4 = work / "audiobook.mp4"
        await _run(
            _ffmpeg(),
            "-y",
            "-v",
            "error",
            "-loop",
            "1",
            "-framerate",
            "1",
            "-i",
            str(cover),
            "-i",
            str(master),
            "-vf",
            "scale=1280:-2,format=yuv420p",
            "-c:v",
            "libx264",
            "-tune",
            "stillimage",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(mp4),
        )
    timestamps = work / "chapters.txt"
    timestamps.write_text("".join(f"{_clock(start)} {title}\n" for title, start in starts), encoding="utf-8")
    (work / "audiobook.json").write_text(
        json.dumps(
            {
                "title": book.title,
                "preset": preset.name,
                "duration": round(duration, 3),
                "chapters": [{"title": t, "start": round(s, 3)} for t, s in starts],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return AudiobookResult(
        m4b=m4b,
        mp3=mp3,
        mp4=mp4,
        chapters=starts,
        timestamps=timestamps,
        duration=duration,
        spoken_segments=spoken,
        cached_segments=cached,
    )


def _escape(value: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", value)


def _clock(seconds: float) -> str:
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


__all__ = [
    "PRESETS",
    "AudiobookPreset",
    "AudiobookResult",
    "Book",
    "Chapter",
    "parse_manuscript",
    "render_audiobook",
    "segment_digest",
    "segments",
]
