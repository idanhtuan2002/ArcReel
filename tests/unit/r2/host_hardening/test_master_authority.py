"""Pure pieces of the master authority unification (ADR-0096)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from lib.candidate_store import CandidateMediaProbeMismatchError
from r2.host_hardening.master_authority import (
    FileMasterProjection,
    m7_candidate_id,
    stream_probe_digest,
)


def test_the_candidate_id_is_stable_and_scoped_by_artifact() -> None:
    first = m7_candidate_id("episode_video:1:S01", "CAND-S01-V2")

    assert first == m7_candidate_id("episode_video:1:S01", "CAND-S01-V2")
    assert first.startswith("m7c:")
    assert len(first) == len("m7c:") + 40
    assert first != m7_candidate_id("episode_video:2:S01", "CAND-S01-V2")
    assert first != m7_candidate_id("episode_video:1:S01", "CAND-S01-V3")


def _video(path: Path, *, size: str = "64x36") -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={size}:d=0.2", "-y", str(path)],
        check=True,
    )
    return path


def test_the_probe_digest_follows_the_stream_layout(tmp_path: Path) -> None:
    small = stream_probe_digest(_video(tmp_path / "a.mp4"))

    assert small.startswith("sha256:")
    assert small == stream_probe_digest(_video(tmp_path / "b.mp4"))
    assert small != stream_probe_digest(_video(tmp_path / "c.mp4", size="128x72"))


def test_unreadable_media_fails_the_probe(tmp_path: Path) -> None:
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not media")

    with pytest.raises(CandidateMediaProbeMismatchError):
        stream_probe_digest(junk)


async def test_the_projection_maps_the_file_master_to_its_candidate_id() -> None:
    selected = {("demo", "episode_video:1:S01"): "CAND-S01-V2"}
    projection = FileMasterProjection(lambda project, key: selected.get((project, key)))

    mapped = await projection.get_selected_candidate_id(
        user_id="u", project_name="demo", artifact_key="episode_video:1:S01"
    )
    absent = await projection.get_selected_candidate_id(
        user_id="u", project_name="demo", artifact_key="episode_video:1:S02"
    )

    assert mapped == m7_candidate_id("episode_video:1:S01", "CAND-S01-V2")
    assert absent is None
