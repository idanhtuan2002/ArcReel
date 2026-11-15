"""A video becomes a story source: chunks, transcript stitching, paragraphs and the origin record (ADR-0161)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.video_ingest import (
    Segment,
    SourceInfo,
    Transcript,
    audio_chunks,
    origin_record,
    paragraphs,
    source_text,
    transcribe,
)

INFO = SourceInfo(
    url="https://example.com/v/1", title="Chuyện ông lái đò", uploader="Kênh A", duration=95.0, extractor="Youtube"
)


def test_segments_join_into_paragraphs_at_pauses():
    transcript = Transcript(
        language="vi",
        segments=[
            Segment(0.0, 2.0, "Ông Bảy lau mái chèo."),
            Segment(2.2, 4.0, "Trời đã chạng vạng."),
            Segment(7.0, 9.0, "Cô Hòa bước xuống bến."),
        ],
    )
    assert paragraphs(transcript) == ["Ông Bảy lau mái chèo. Trời đã chạng vạng.", "Cô Hòa bước xuống bến."]
    text = source_text(INFO, transcript)
    assert text.splitlines()[0] == "Chuyện ông lái đò"
    record = origin_record(INFO, transcript)
    assert record["url"] == "https://example.com/v/1"
    assert record["segments"] == 3
    assert "no footage reused" in record["use"]


def test_chunk_transcripts_are_stitched_on_one_timeline():
    replies = [
        {"language": "vi", "segments": [{"start": 1.0, "end": 2.0, "text": " Một. "}]},
        {"text": "Hai."},
    ]

    async def call(_path: Path) -> dict:
        return replies.pop(0)

    transcript = asyncio.run(transcribe([Path("a.mp3"), Path("b.mp3")], call, chunk_seconds=600))
    assert transcript.language == "vi"
    assert [(s.start, s.text) for s in transcript.segments] == [(1.0, "Một."), (600.0, "Hai.")]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_the_sound_is_cut_into_mono_chunks(tmp_path: Path):
    source = tmp_path / "source.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "5",
            str(source),
        ],
        check=True,
    )
    chunks = asyncio.run(audio_chunks(source, tmp_path, chunk_seconds=2))
    assert len(chunks) == 3
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=channels,sample_rate", "-of", "csv=p=0", str(chunks[0])],
        capture_output=True,
        text=True,
        check=True,
    )
    assert probe.stdout.strip() == "16000,1"
