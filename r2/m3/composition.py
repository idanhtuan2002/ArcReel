from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Sequence

from r2.contracts.enums import ProductionMethod
from .host_integration import GoldenAHostIntegration


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ffmpeg_version() -> str:
    result = subprocess.run(
        ["ffmpeg", "-version"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()[0]


@dataclass(frozen=True)
class GoldenACompositeAsset:
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
    source_master_refs: tuple[str, ...]


class GoldenAComposer:
    def compose(
        self,
        host: GoldenAHostIntegration,
        shot_refs: Sequence[str],
        *,
        output_path: Path,
    ) -> GoldenACompositeAsset:
        if not shot_refs:
            raise ValueError("Golden A composition requires at least one shot")

        inputs: list[Path] = []
        source_master_refs: list[str] = []
        source_hashes: list[str] = []

        for shot_ref in shot_refs:
            metadata = host.snapshot(shot_ref)
            master = metadata.approved_master
            if master is None:
                raise ValueError(f"{shot_ref} has no approved master")

            current = host.current_file_for(shot_ref)
            if not current.is_file():
                raise FileNotFoundError(current)

            inputs.append(current)
            source_hashes.append(_sha256(current))
            source_master_refs.append(
                f"{shot_ref}:{master.selected_candidate_id}:"
                f"{master.host_version_ref}"
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        concat_file = output_path.with_suffix(".concat.txt")
        concat_file.write_text(
            "".join(
                f"file '{path.resolve().as_posix()}'\n"
                for path in inputs
            ),
            encoding="utf-8",
        )

        tool_version = _ffmpeg_version()
        fingerprint_payload = {
            "tool": "ffmpeg",
            "tool_version": tool_version,
            "method": ProductionMethod.COMPOSITE.value,
            "source_master_refs": source_master_refs,
            "source_hashes": source_hashes,
            "mode": "concat-demuxer-copy",
        }
        execution_fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

        start = time.perf_counter()
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                "-map_metadata", "-1",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        wall = time.perf_counter() - start
        concat_file.unlink(missing_ok=True)

        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        duration = float(probe.stdout.strip())

        return GoldenACompositeAsset(
            target_ref="FINAL-GOLDEN-A",
            method=ProductionMethod.COMPOSITE,
            path=output_path,
            sha256=_sha256(output_path),
            duration_seconds=duration,
            execution_fingerprint=execution_fingerprint,
            tool="ffmpeg",
            tool_version=tool_version,
            wall_time_seconds=wall,
            external_provider_cost=Decimal("0"),
            source_master_refs=tuple(source_master_refs),
        )
