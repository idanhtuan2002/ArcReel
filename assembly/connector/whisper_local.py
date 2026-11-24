"""Transcribe one audio file with faster-whisper large-v3 and print OpenAI `verbose_json`-shaped JSON.

Runs under OpenMontage's venv (which has `faster-whisper`): `<openmontage>/.venv/bin/python whisper_local.py <audio>`.
The model is the sponsor-approved `Systran/faster-whisper-large-v3` on drive D.
"""

from __future__ import annotations

import json
import os
import sys

MODEL_DIR = os.environ.get("WHISPER_MODEL_DIR", "/mnt/arcreel/D/ArcReel/whisper/faster-whisper-large-v3")


def main(path: str) -> None:
    from faster_whisper import WhisperModel  # pyright: ignore[reportMissingImports]

    model = WhisperModel(MODEL_DIR, device="cuda", compute_type="float16")
    segments, info = model.transcribe(path, vad_filter=True, beam_size=5)
    out = {
        "language": info.language,
        "segments": [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments],
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
