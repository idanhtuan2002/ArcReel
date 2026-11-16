"""The final's transcript is made once per final, kept beside its reviews, and a failure leaves speech unchecked."""

from __future__ import annotations

import asyncio
from pathlib import Path

from server.production_run.evaluators import FinalEvidence
from server.production_run.quality_adapter import QualityAdapter


def _adapter(transcribe) -> QualityAdapter:
    adapter = QualityAdapter.__new__(QualityAdapter)
    adapter._transcribe = transcribe
    return adapter


def _evidence(tmp_path: Path) -> FinalEvidence:
    final = tmp_path / "episode_1.mp4"
    final.write_bytes(b"film")
    return FinalEvidence(
        unit_key="episode:1",
        final_path=final,
        subtitle_path=final.with_suffix(".srt"),
        narration_text="Ông Ba không trả lời.",
        subject_digest="sha256:" + "a" * 64,
    )


def test_the_transcript_is_made_once_and_reused(tmp_path: Path):
    calls: list[tuple[Path, str]] = []

    async def transcribe(final: Path, language: str) -> str:
        calls.append((final, language))
        return "ông ba không trả lời"

    adapter = _adapter(transcribe)
    evidence = _evidence(tmp_path)
    assert asyncio.run(adapter._transcript(evidence)) == "ông ba không trả lời"
    assert asyncio.run(adapter._transcript(evidence)) == "ông ba không trả lời"
    assert calls == [(evidence.final_path, "vi")]
    assert (tmp_path / "quality" / f"{'a' * 16}.transcript.json").is_file()


def test_a_failed_or_missing_transcription_leaves_speech_unchecked(tmp_path: Path):
    async def broken(final: Path, language: str) -> str:
        raise TimeoutError("transcription endpoint down")

    assert asyncio.run(_adapter(broken)._transcript(_evidence(tmp_path))) is None
    assert asyncio.run(_adapter(None)._transcript(_evidence(tmp_path))) is None
    assert not (tmp_path / "quality").exists()
