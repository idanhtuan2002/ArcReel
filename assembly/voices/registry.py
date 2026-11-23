"""Which VieNeu preset produced a voice sample, keyed by the sample's SHA-256.

The connector uploads each cast sample to DramaClaw, which stores the bytes unchanged and sends them back inline as a
``data:`` URL when it asks for speech (``seedance2_i2v/voice_clone.py:402-417``); the voice adapter looks the hash up
here to speak in the same preset.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

DEFAULT_REGISTRY = Path.home() / "assembly-data/voices.json"


def registry_path() -> Path:
    return Path(os.environ.get("ASSEMBLY_VOICE_REGISTRY", str(DEFAULT_REGISTRY)))


def sample_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path | None = None) -> dict[str, str]:
    target = path or registry_path()
    if not target.is_file():
        return {}
    data = json.loads(target.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def register(sample: bytes, preset: str, path: Path | None = None) -> str:
    """Record ``preset`` for ``sample`` and return the sample's digest (atomic write)."""
    target = path or registry_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    entries = load(target)
    digest = sample_digest(sample)
    entries[digest] = preset
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".voices-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, target)
    return digest
