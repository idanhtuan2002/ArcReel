"""Transcribe one audio file with faster-whisper large-v3 and print OpenAI `verbose_json`-shaped JSON.

Runs under OpenMontage's venv (which has `faster-whisper`): `<openmontage>/.venv/bin/python whisper_local.py <audio>`.
The model is the sponsor-approved `Systran/faster-whisper-large-v3` on drive D.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

MODEL_DIR = os.environ.get("WHISPER_MODEL_DIR", "/mnt/arcreel/D/ArcReel/whisper/faster-whisper-large-v3")


def _pcm(path: str):
    """16 kHz mono float32 decoded by ffmpeg (OpenMontage pins a PyAV older than faster-whisper's decoder expects)."""
    import numpy as np

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def main(path: str) -> None:
    from faster_whisper import WhisperModel  # pyright: ignore[reportMissingImports]

    model = WhisperModel(MODEL_DIR, device="cuda", compute_type="float16")
    segments, info = model.transcribe(_pcm(path), vad_filter=True, beam_size=5)
    out = {
        "language": info.language,
        "segments": [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments],
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
