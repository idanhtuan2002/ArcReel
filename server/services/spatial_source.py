"""Bounded extraction of a pinned decoded video ordinal into one PNG source frame."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lib.candidate_store import prepare_candidate
from r2.advanced_creative.digests import digest_canonical
from r2.contracts.host_hardening import CandidateIdentity, VerifiedCandidateObject

FRAME_RECIPE_VERSION = "m8c-frame-rgb24-png-v1"
MAX_DECODED_FRAME_INDEX = 100_000
MAX_FRAME_BYTES = 32 * 1024 * 1024
MAX_FRAME_DIMENSION = 4096
DECODE_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class FrameProbe:
    byte_size: int
    content_digest: str
    probe_digest: str
    width: int
    height: int


def ffmpeg_decoder_identity() -> str:
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True, timeout=5)
    return "ffmpeg:" + hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()


def _probe_png(path: Path) -> tuple[int, int, str]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,width,height,nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    streams = json.loads(result.stdout).get("streams", [])
    if len(streams) != 1:
        raise ValueError("decoded output is not one video frame")
    stream = streams[0]
    width, height = stream.get("width"), stream.get("height")
    if (
        stream.get("codec_name") != "png"
        or stream.get("pix_fmt") != "rgb24"
        or stream.get("nb_read_frames") != "1"
        or not isinstance(width, int)
        or not isinstance(height, int)
        or not 1 <= width <= MAX_FRAME_DIMENSION
        or not 1 <= height <= MAX_FRAME_DIMENSION
    ):
        raise ValueError("decoded PNG has invalid format or dimensions")
    return (
        width,
        height,
        digest_canonical({"codec_name": "png", "pixel_format": "rgb24", "width": width, "height": height, "frames": 1}),
    )


def decode_frame(
    *,
    parent_path: Path,
    decoded_frame_index: int,
    recipe_version: str,
    decoder_identity: str,
    output_temp: Path,
) -> FrameProbe:
    if type(decoded_frame_index) is not int or not 0 <= decoded_frame_index <= MAX_DECODED_FRAME_INDEX:
        raise ValueError("decoded frame index is out of range")
    if recipe_version != FRAME_RECIPE_VERSION:
        raise ValueError("unsupported frame recipe version")
    if decoder_identity != ffmpeg_decoder_identity():
        raise ValueError("frame decoder identity differs from current build")
    if output_temp.exists() or output_temp.is_symlink():
        raise ValueError("output temp already exists")
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(parent_path),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-vf",
            f"select=eq(n\\,{decoded_frame_index}),format=rgb24",
            "-fps_mode",
            "passthrough",
            "-frames:v",
            "1",
            "-f",
            "image2",
            "-fs",
            str(MAX_FRAME_BYTES),
            "-n",
            str(output_temp),
        ],
        capture_output=True,
        check=False,
        timeout=DECODE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise ValueError("frame decoder failed")
    if not output_temp.is_file() or output_temp.is_symlink():
        raise ValueError("decoder produced no frame")
    size = output_temp.stat().st_size
    if not 0 < size <= MAX_FRAME_BYTES:
        raise ValueError("decoded frame exceeds size limit")
    with output_temp.open("rb") as source:
        if source.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError("decoded frame is not PNG")
        hasher = hashlib.sha256()
        hasher.update(b"\x89PNG\r\n\x1a\n")
        while chunk := source.read(1024 * 1024):
            hasher.update(chunk)
    width, height, probe_digest = _probe_png(output_temp)
    return FrameProbe(size, "sha256:" + hasher.hexdigest(), probe_digest, width, height)


def publish_frame(
    *, temp: Path, final: Path, media_root: Path, identity: CandidateIdentity, probe: FrameProbe
) -> VerifiedCandidateObject:
    if identity.expected_content_digest != probe.content_digest:
        raise ValueError("frame identity digest differs from decoded bytes")
    verified = prepare_candidate(
        identity=identity,
        source_file=temp,
        final_path=final,
        media_root=media_root,
        media_probe=lambda path: _probe_png(path)[2],
    )
    if verified.byte_size != probe.byte_size or verified.media_probe_digest != probe.probe_digest:
        raise ValueError("published frame differs from decoded probe")
    return verified


__all__ = ["FrameProbe", "decode_frame", "ffmpeg_decoder_identity", "publish_frame"]
