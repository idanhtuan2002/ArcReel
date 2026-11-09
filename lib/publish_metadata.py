"""Publishing metadata of one finished episode, made from the project's own records without a model call.

The package carries what an uploader needs (OpenMontage's ``export_bundle`` idea): a title, a description, tags,
the language, the duration and a thumbnail frame. Everything comes from the project (title, overview, episode
ledger) and, when the episode was adapted (ADR-0114), from its adaptation (logline, cliffhanger). The same inputs
always give the same bytes, so a package rebuilt from the same run is identical.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lib.episode_adaptation import adaptation_record_relpath

SCHEMA = "r2.publish-metadata.v1"
THUMBNAIL_SECOND = 1.0
_EPISODE_WORD = {"vi": "Tập {n}", "zh": "第{n}集", "en": "Episode {n}"}


def _entry(project: Mapping[str, Any], episode: int) -> Mapping[str, Any]:
    for item in project.get("episodes") or []:
        if isinstance(item, Mapping) and item.get("episode") == episode:
            return item
    return {}


def _adaptation(project_path: Path, episode: int) -> Mapping[str, Any]:
    try:
        record = json.loads((project_path / adaptation_record_relpath(episode)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    draft = record.get("draft") if isinstance(record, Mapping) else None
    return draft if isinstance(draft, Mapping) else {}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def publish_metadata(
    project: Mapping[str, Any], project_path: Path, episode: int, *, duration_seconds: float
) -> dict[str, Any]:
    language = _text(project.get("source_language")) or "vi"
    entry = _entry(project, episode)
    raw_overview = project.get("overview")
    overview: Mapping[str, Any] = raw_overview if isinstance(raw_overview, Mapping) else {}
    adaptation = _adaptation(project_path, episode)
    label = _EPISODE_WORD.get(language, _EPISODE_WORD["en"]).format(n=episode)
    title = " – ".join(part for part in (_text(project.get("title")), label, _text(entry.get("title"))) if part)
    lines = [
        _text(adaptation.get("logline")) or _text(entry.get("hook")),
        _text(adaptation.get("cliffhanger")),
        _text(overview.get("synopsis")) if not adaptation else "",
    ]
    tags = [tag for tag in (_text(overview.get("genre")), _text(overview.get("theme"))) if tag]
    return {
        "schema": SCHEMA,
        "episode": episode,
        "title": title[:100],
        "description": "\n\n".join(line for line in lines if line)[:5000],
        "tags": tags,
        "language": language,
        "duration_seconds": round(duration_seconds, 3),
        "thumbnail": "thumbnail.jpg",
        "thumbnail_second": THUMBNAIL_SECOND,
    }


def thumbnail_frame(final: Path, *, ffmpeg: str = "ffmpeg") -> bytes:
    """One JPEG frame of ``final`` at ``THUMBNAIL_SECOND`` (or its first frame for a shorter film), bit-exact."""
    completed = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-loglevel",
            "error",
            "-ss",
            str(THUMBNAIL_SECOND),
            "-i",
            str(final),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            "-bitexact",
            "-f",
            "image2",
            "-c:v",
            "mjpeg",
            "pipe:1",
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if completed.returncode == 0 and completed.stdout:
        return completed.stdout
    first = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(final),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            "-bitexact",
            "-f",
            "image2",
            "-c:v",
            "mjpeg",
            "pipe:1",
        ],
        capture_output=True,
        timeout=120,
        check=True,
    )
    return first.stdout


__all__ = ["SCHEMA", "publish_metadata", "thumbnail_frame"]
