"""Seam: ArcReel projects are always on DramaClaw's structured pipeline (no knowledge graph)."""

from __future__ import annotations

from pathlib import Path


def is_structured_pipeline(state_dir: str | Path | None) -> bool:
    return True
