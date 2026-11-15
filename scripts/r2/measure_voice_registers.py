"""Measure the register (low / high median pitch) of an audio route's voices for the voice cast (ADR-0166).

Each voice speaks one fixed line; the median fundamental frequency of its voiced frames decides the register
(below ``SPLIT_HZ`` low, else high). Results merge into ``lib/voice_registers.json`` under the route key
``<endpoint>`` (voices are shared by every model of one endpoint). Credentials come from the environment.

    GEM=... uv run python scripts/r2/measure_voice_registers.py --endpoint gemini-tts --model gemini-3.8-flash-tts
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from lib.audio_backends.base import AudioSynthesisRequest
from lib.custom_provider.endpoints import ENDPOINT_REGISTRY
from lib.voice_registers import REGISTRY_PATH, SPLIT_HZ

LINE = "Buổi sáng hôm ấy, bà cụ mở cửa quán và mỉm cười chào người khách đầu tiên."
RATE = 16000


def median_pitch(wav: Path) -> float:
    """Median F0 (Hz) of the voiced 40 ms frames, by autocorrelation between 70 and 400 Hz."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(wav), "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    signal = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    frame, hop = int(0.04 * RATE), int(0.01 * RATE)
    low_lag, high_lag = RATE // 400, RATE // 70
    pitches: list[float] = []
    loudness = np.sqrt(np.mean(signal**2)) if signal.size else 0.0
    for start in range(0, signal.size - frame, hop):
        chunk = signal[start : start + frame]
        chunk = chunk - chunk.mean()
        if np.sqrt(np.mean(chunk**2)) < 0.5 * loudness:
            continue
        corr = np.correlate(chunk, chunk, mode="full")[frame - 1 :]
        lag = low_lag + int(np.argmax(corr[low_lag:high_lag]))
        if corr[0] > 0 and corr[lag] / corr[0] > 0.45:
            pitches.append(RATE / lag)
    if not pitches:
        raise RuntimeError(f"no voiced frames in {wav.name}")
    return float(np.median(pitches))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="https://generativelanguage.googleapis.com")
    parser.add_argument("--key-env", default="GEM")
    args = parser.parse_args()
    backend = ENDPOINT_REGISTRY[args.endpoint].build_backend(
        SimpleNamespace(provider_id="measure", base_url=args.base_url, api_key=os.environ.get(args.key_env, "")),
        args.model,
    )
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8")) if REGISTRY_PATH.exists() else {}
    found = registry.setdefault(args.endpoint, {})
    with tempfile.TemporaryDirectory() as tmp:
        for voice in backend.list_voices():
            if voice.id in found:
                continue
            path = Path(tmp) / f"{voice.id}.wav"
            try:
                await backend.synthesize(AudioSynthesisRequest(text=LINE, output_path=path, voice=voice.id))
            except Exception as error:
                print(voice.id, "failed", type(error).__name__, str(error)[:120], flush=True)
                continue
            hz = median_pitch(path)
            found[voice.id] = {"median_hz": round(hz, 1), "register": "low" if hz < SPLIT_HZ else "high"}
            print(voice.id, found[voice.id], flush=True)
            REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
