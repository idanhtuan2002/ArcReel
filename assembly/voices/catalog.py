"""VieNeu's own preset voices, read from its asset file (VieNeu-TTS @ 36c4b50, ``assets/voices_v3_turbo.json``)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PRESETS = Path.home() / "VieNeu-TTS/src/vieneu/assets/voices_v3_turbo.json"
_REGIONS = {"Bắc": "north", "Trung": "central", "Nam": "south"}


@dataclass(frozen=True)
class Voice:
    name: str
    gender: str  # "male" | "female"
    region: str  # "north" | "central" | "south"
    style: str  # VieNeu style key, e.g. "tu_nhien", "doc_truyen", "tin_tuc"


def _region(entry: dict[str, object]) -> str:
    """VieNeu records the region in ``region`` for most presets and always in ``description`` ("Nam · Bắc · …")."""
    raw = entry.get("region")
    if isinstance(raw, str) and raw in _REGIONS:
        return _REGIONS[raw]
    parts = [p.strip() for p in str(entry.get("description") or "").split("·")]
    return _REGIONS.get(parts[1], "north") if len(parts) > 1 else "north"


def load_voices(path: Path | None = None) -> list[Voice]:
    source = path or Path(os.environ.get("VIENEU_PRESETS_JSON", str(DEFAULT_PRESETS)))
    presets = json.loads(source.read_text(encoding="utf-8"))["presets"]
    return [
        Voice(name=name, gender=str(e.get("gender") or "male"), region=_region(e), style=str(e.get("style") or ""))
        for name, e in presets.items()
    ]
