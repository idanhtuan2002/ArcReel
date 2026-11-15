"""Audiobook: manuscript parsing, segmenting and the rendered files (ADR-0159)."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.audiobook import PRESETS, parse_manuscript, render_audiobook, segments

MANUSCRIPT = """# Chuyến đò cuối

> Một ông lái đò và chuyến cuối cùng.

## Chương 1: Bến sông

Ông Bảy lau mái chèo. Trời chạng vạng.

Cô Hòa bước xuống bến.

* * *

Con đò rời bờ.

## Chương 2: Bờ bên kia

Cây cầu sáng đèn. Ông mỉm cười.
"""


def test_the_manuscript_becomes_chapters_of_scenes_and_the_blurb_is_not_read():
    book = parse_manuscript(MANUSCRIPT)
    assert book.title == "Chuyến đò cuối"
    assert [c.title for c in book.chapters] == ["Chương 1: Bến sông", "Chương 2: Bờ bên kia"]
    assert book.chapters[0].scenes == (
        ("Ông Bảy lau mái chèo. Trời chạng vạng.", "Cô Hòa bước xuống bến."),
        ("Con đò rời bờ.",),
    )
    assert "Một ông lái đò" not in json.dumps([c.scenes for c in book.chapters], ensure_ascii=False)


def test_a_paragraph_is_cut_at_sentences_within_the_limit():
    text = "Một câu ngắn. " * 10 + "Câu cuối."
    pieces = segments(text, limit=40)
    assert all(len(p) <= 40 for p in pieces)
    assert " ".join(pieces) == text.strip()
    assert segments("Một câu rất dài không có dấu chấm nào cả " * 3, limit=20) == [
        ("Một câu rất dài không có dấu chấm nào cả " * 3).strip()
    ]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_the_book_is_spoken_once_cached_and_written_with_chapter_marks(tmp_path: Path):
    spoken: list[str] = []

    async def speak(text: str, path: Path) -> None:
        spoken.append(text)
        await asyncio.to_thread(
            subprocess.run,
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=22050",
                "-t",
                "0.4",
                str(path),
            ],
            check=True,
        )

    cover = tmp_path / "cover.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=320x480", "-frames:v", "1", str(cover)],
        check=True,
    )
    book = parse_manuscript(MANUSCRIPT)
    result = asyncio.run(
        render_audiobook(book, tmp_path / "ab", speak=speak, voice_key="v1", preset=PRESETS["standard"], cover=cover)
    )

    assert result.m4b.is_file()
    assert result.mp3.is_file()
    assert result.mp4 is not None
    assert result.mp4.is_file()
    assert [t for t, _ in result.chapters] == ["Chương 1: Bến sông", "Chương 2: Bờ bên kia"]
    assert result.chapters[0][1] == 0.0
    assert result.chapters[1][1] > 0.0
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_chapters", "-of", "json", str(result.m4b)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert len(json.loads(probe.stdout)["chapters"]) == 2
    assert result.timestamps is not None
    assert result.timestamps.read_text(encoding="utf-8").splitlines()[1].endswith("Chương 2: Bờ bên kia")
    first = len(spoken)
    assert first == result.spoken_segments

    again = asyncio.run(
        render_audiobook(book, tmp_path / "ab", speak=speak, voice_key="v1", preset=PRESETS["standard"])
    )
    assert len(spoken) == first
    assert again.cached_segments == first
