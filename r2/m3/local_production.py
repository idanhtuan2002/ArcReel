from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from r2.contracts.enums import ProductionMethod, ReadinessState

from .preparation import GoldenAPreparedShot


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ffmpeg_version() -> str:
    proc = subprocess.run(
        ["ffmpeg", "-version"],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.splitlines()[0]


@dataclass(frozen=True)
class LocalProducedAsset:
    target_ref: str
    method: ProductionMethod
    path: Path
    sha256: str
    duration_seconds: float
    execution_fingerprint: str
    tool: str
    tool_version: str
    wall_time_seconds: float
    external_provider_cost: Decimal


class GoldenALocalProducer:
    def produce(
        self,
        prepared: GoldenAPreparedShot,
        *,
        work_dir: Path,
        execution_variant: str = "default",
    ) -> LocalProducedAsset:
        if prepared.readiness.state is not ReadinessState.READY:
            raise ValueError(f"{prepared.shot.id} is BLOCKED and cannot be produced")

        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        output = work_dir / f"{prepared.shot.id}.mp4"

        if prepared.method.method is ProductionMethod.REUSE:
            if not prepared.bindings:
                raise ValueError("REUSE requires a resolved binding")
            source = Path(prepared.bindings[0].production_ref)
            if not source.is_file():
                raise FileNotFoundError(source)
            source_hash = _sha256(source)
        else:
            source_hash = "none"

        palette = ["black", "navy", "darkgreen", "maroon", "gray"]
        seed = int(
            hashlib.sha256(f"{prepared.shot.id}:{execution_variant}:{source_hash}".encode()).hexdigest()[:8],
            16,
        )
        color = palette[seed % len(palette)]
        duration = float(prepared.shot.target_duration)

        tool_version = _ffmpeg_version()
        exec_data = {
            "tool": "ffmpeg",
            "tool_version": tool_version,
            "method": prepared.method.method.value,
            "target_ref": prepared.shot.id,
            "duration": duration,
            "resolution": "1280x720",
            "fps": 2,
            "encoder": "mpeg4",
            "execution_variant": execution_variant,
            "source_asset_sha256": source_hash,
        }
        execution_fingerprint = hashlib.sha256(
            json.dumps(
                exec_data,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=1280x720:r=2:d={duration}",
            "-an",
            "-c:v",
            "mpeg4",
            "-q:v",
            "5",
            "-pix_fmt",
            "yuv420p",
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-map_metadata",
            "-1",
            str(output),
        ]
        start = time.perf_counter()
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
        wall = time.perf_counter() - start

        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        actual = float(probe.stdout.strip())
        if abs(actual - duration) > 0.6:
            raise RuntimeError(f"ffmpeg duration drift for {prepared.shot.id}: {actual} vs {duration}")

        return LocalProducedAsset(
            target_ref=prepared.shot.id,
            method=prepared.method.method,
            path=output,
            sha256=_sha256(output),
            duration_seconds=actual,
            execution_fingerprint=execution_fingerprint,
            tool="ffmpeg",
            tool_version=tool_version,
            wall_time_seconds=wall,
            external_provider_cost=Decimal("0"),
        )
