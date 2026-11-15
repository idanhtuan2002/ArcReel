"""Join speech clips into one track with a fixed silence between them (ADR-0166 character lines)."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Sequence
from pathlib import Path

SAMPLE_RATE = 24000


async def join_with_gaps(parts: Sequence[Path], output: Path, *, gap_seconds: float) -> None:
    """Write ``parts`` in order into ``output`` (format from its suffix), mono at ``SAMPLE_RATE`` Hz, with
    ``gap_seconds`` of silence between two parts."""
    if not parts:
        raise ValueError("nothing to join")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is not installed")
    args: list[str] = [ffmpeg, "-y", "-v", "error"]
    for part in parts:
        args += ["-i", str(part)]
    if len(parts) == 1:
        args += ["-ar", str(SAMPLE_RATE), "-ac", "1", str(output)]
    else:
        gaps = len(parts) - 1
        args += ["-f", "lavfi", "-t", f"{gap_seconds:.3f}", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=mono"]
        chains = [f"[{i}:a]aresample={SAMPLE_RATE},aformat=channel_layouts=mono[a{i}]" for i in range(len(parts))]
        split = f"[{len(parts)}:a]asplit={gaps}" + "".join(f"[g{i}]" for i in range(gaps))
        order = "".join(f"[a{i}]" + (f"[g{i}]" if i < gaps else "") for i in range(len(parts)))
        graph = ";".join([*chains, split, f"{order}concat=n={len(parts) + gaps}:v=0:a=1[out]"])
        args += ["-filter_complex", graph, "-map", "[out]", str(output)]
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, err = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg join failed: {err.decode(errors='replace')[-300:]}")


__all__ = ["SAMPLE_RATE", "join_with_gaps"]
