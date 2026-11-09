"""A packaged episode carries publishing metadata made from the project's own records."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lib.publish_metadata import publish_metadata, thumbnail_frame


def _project() -> dict:
    return {
        "title": "Phong thư đỏ",
        "source_language": "vi",
        "overview": {"synopsis": "Lan truy tìm món nợ của cha.", "genre": "Trinh thám", "theme": "Gia đình"},
        "episodes": [{"episode": 2, "title": "Người tên Minh", "hook": "Một cái tên trong sổ"}],
    }


def test_metadata_without_adaptation_uses_the_ledger_and_overview(tmp_path: Path):
    data = publish_metadata(_project(), tmp_path, 2, duration_seconds=44.96)
    assert data["title"] == "Phong thư đỏ – Tập 2 – Người tên Minh"
    assert data["description"] == "Một cái tên trong sổ\n\nLan truy tìm món nợ của cha."
    assert (data["tags"], data["language"], data["duration_seconds"]) == (["Trinh thám", "Gia đình"], "vi", 44.96)


def test_an_adapted_episode_describes_its_logline_and_cliffhanger(tmp_path: Path):
    (tmp_path / "adaptations").mkdir()
    (tmp_path / "adaptations" / "episode_2.json").write_text(
        json.dumps({"draft": {"logline": "Lan tìm Minh.", "cliffhanger": "Minh đã chết?"}}), encoding="utf-8"
    )
    data = publish_metadata(_project(), tmp_path, 2, duration_seconds=45)
    assert data["description"] == "Lan tìm Minh.\n\nMinh đã chết?"


def test_the_thumbnail_is_the_same_bytes_every_time(tmp_path: Path):
    final = tmp_path / "final.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=576x1024:r=24:d=2", str(final)],
        check=True,
    )
    first = thumbnail_frame(final)
    assert first.startswith(b"\xff\xd8")
    assert thumbnail_frame(final) == first


def test_export_accepts_only_metadata_and_a_thumbnail_of_this_episodes_final(tmp_path: Path):
    from server.production_run.packaging_adapter import _publish_matches, _thumbnail_of

    final = tmp_path / "final.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=576x1024:r=24:d=2", str(final)],
        check=True,
    )
    other = tmp_path / "other.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=576x1024:r=24:d=2",
            str(other),
        ],
        check=True,
    )
    manifest = {"duration_seconds": 2.0}
    good = publish_metadata(_project(), tmp_path, 2, duration_seconds=2.0)
    assert _publish_matches(good, 2, manifest)
    assert not _publish_matches({**good, "episode": 3}, 2, manifest)
    assert not _publish_matches({**good, "duration_seconds": 9.0}, 2, manifest)
    assert _thumbnail_of(final.read_bytes()) == thumbnail_frame(final)
    assert _thumbnail_of(final.read_bytes()) != thumbnail_frame(other)
