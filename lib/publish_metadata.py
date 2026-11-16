"""Publishing metadata of one finished episode, made from the project's own records without a model call.

The package carries what an uploader needs (OpenMontage's ``export_bundle`` idea): a title, a description, tags,
hashtags, the series and the episode's place in it, the language, the duration and a thumbnail frame. The hashtags
(at most three, the number a platform shows with the title) end the description too. Everything comes from the project (title, overview, episode
ledger) and, when the episode was adapted (ADR-0114), from its adaptation (logline, cliffhanger). The same inputs
always give the same bytes, so a package rebuilt from the same run is identical.
"""

from __future__ import annotations

import json
import subprocess
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lib.episode_adaptation import adaptation_record_relpath
from lib.text_attestation import has_cjk

SCHEMA = "r2.publish-metadata.v1"
THUMBNAIL_SECOND = 1.0
EPISODE_WORD = {"vi": "Tập {n}", "zh": "第{n}集", "en": "Episode {n}"}
MAX_HASHTAGS = 3
#: Languages written with Han characters; in any other language a text that has them is left out of the metadata.
CJK_LANGUAGES = frozenset({"zh", "ja", "ko"})


def episode_entry(project: Mapping[str, Any], episode: int) -> Mapping[str, Any]:
    for item in project.get("episodes") or []:
        if isinstance(item, Mapping) and item.get("episode") == episode:
            return item
    return {}


def episode_adaptation(project_path: Path, episode: int) -> Mapping[str, Any]:
    try:
        record = json.loads((project_path / adaptation_record_relpath(episode)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    draft = record.get("draft") if isinstance(record, Mapping) else None
    return draft if isinstance(draft, Mapping) else {}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def hashtag(text: str) -> str:
    """``text`` as one hashtag: its letters and digits (any script) with the words joined, or ``""``."""
    words = "".join(ch if unicodedata.category(ch)[0] in "LN" else " " for ch in unicodedata.normalize("NFC", text))
    joined = "".join(word[:1].upper() + word[1:] for word in words.split())
    return f"#{joined}" if joined else ""


def _hashtags(*texts: str) -> list[str]:
    tags: list[str] = []
    for text in texts:
        tag = hashtag(text)
        if tag and tag.casefold() not in {t.casefold() for t in tags}:
            tags.append(tag)
    return tags[:MAX_HASHTAGS]


def _episode_count(project: Mapping[str, Any]) -> int:
    return sum(1 for item in project.get("episodes") or [] if isinstance(item, Mapping))


def _in_language(record: Mapping[str, Any], language: str) -> Mapping[str, Any]:
    """``record`` without the texts that are not in ``language``: a Vietnamese film's metadata never carries a title
    an older planner wrote in Chinese."""
    if language.split("-")[0] in CJK_LANGUAGES:
        return record
    return {key: value for key, value in record.items() if not (isinstance(value, str) and has_cjk(value))}


def publish_metadata(
    project: Mapping[str, Any], project_path: Path, episode: int, *, duration_seconds: float
) -> dict[str, Any]:
    language = _text(project.get("source_language")) or "vi"
    entry = _in_language(episode_entry(project, episode), language)
    raw_overview = project.get("overview")
    overview: Mapping[str, Any] = _in_language(raw_overview, language) if isinstance(raw_overview, Mapping) else {}
    adaptation = _in_language(episode_adaptation(project_path, episode), language)
    project = _in_language(project, language)
    label = EPISODE_WORD.get(language, EPISODE_WORD["en"]).format(n=episode)
    title = " – ".join(part for part in (_text(project.get("title")), label, _text(entry.get("title"))) if part)
    lines = [
        _text(adaptation.get("logline")) or _text(entry.get("hook")),
        _text(adaptation.get("cliffhanger")),
        _text(overview.get("synopsis")) if not adaptation else "",
    ]
    tags = [tag for tag in (_text(overview.get("genre")), _text(overview.get("theme"))) if tag]
    series = _text(project.get("title"))
    hashtags = _hashtags(series, *tags)
    body = "\n\n".join(line for line in lines if line)
    tail = " ".join(hashtags)
    description = (body[: 5000 - len(tail) - 2] + "\n\n" + tail if body else tail) if tail else body[:5000]
    return {
        "schema": SCHEMA,
        "episode": episode,
        "title": title[:100],
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "series": {"title": series, "episode": episode, "episodes": max(_episode_count(project), episode)},
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


__all__ = [
    "EPISODE_WORD",
    "SCHEMA",
    "episode_adaptation",
    "episode_entry",
    "hashtag",
    "publish_metadata",
    "thumbnail_frame",
]
