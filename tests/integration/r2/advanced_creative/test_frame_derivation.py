"""Bounded ordinal decoding and no-overwrite publication for spatial source frames."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from lib.candidate_store import CandidateDuplicateConflictError
from r2.contracts.host_hardening import CandidateIdentity
from server.services import spatial_source as service


@pytest.fixture
def three_frame_video(tmp_path: Path) -> Path:
    path = tmp_path / "three.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x48:rate=3:duration=1",
            "-frames:v",
            "3",
            "-y",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return path


def test_decode_three_distinct_frames_and_reject_out_of_range(three_frame_video: Path, tmp_path: Path) -> None:
    decoder = service.ffmpeg_decoder_identity()
    probes = [
        service.decode_frame(
            parent_path=three_frame_video,
            decoded_frame_index=index,
            recipe_version="m8c-frame-rgb24-png-v1",
            decoder_identity=decoder,
            output_temp=tmp_path / f"frame-{index}.png",
        )
        for index in range(3)
    ]
    assert len({probe.content_digest for probe in probes}) == 3
    assert all(probe.byte_size > 0 and probe.width == 64 and probe.height == 48 for probe in probes)

    with pytest.raises(ValueError, match="no frame"):
        service.decode_frame(
            parent_path=three_frame_video,
            decoded_frame_index=3,
            recipe_version="m8c-frame-rgb24-png-v1",
            decoder_identity=decoder,
            output_temp=tmp_path / "missing.png",
        )


def test_decode_rejects_negative_ordinal_and_wrong_decoder(three_frame_video: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="index"):
        service.decode_frame(
            parent_path=three_frame_video,
            decoded_frame_index=-1,
            recipe_version="m8c-frame-rgb24-png-v1",
            decoder_identity=service.ffmpeg_decoder_identity(),
            output_temp=tmp_path / "negative.png",
        )
    with pytest.raises(ValueError, match="decoder"):
        service.decode_frame(
            parent_path=three_frame_video,
            decoded_frame_index=0,
            recipe_version="m8c-frame-rgb24-png-v1",
            decoder_identity="wrong-build",
            output_temp=tmp_path / "wrong.png",
        )


def test_decode_rejects_malformed_png_even_when_decoder_exits_zero(
    three_frame_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoder = service.ffmpeg_decoder_identity()
    real_run = subprocess.run

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        if args[:2] == ["ffmpeg", "-nostdin"]:
            Path(args[-1]).write_bytes(b"not-png")
            return subprocess.CompletedProcess(args, 0, b"", b"")
        return real_run(args, **kwargs)

    monkeypatch.setattr(service.subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="not PNG"):
        service.decode_frame(
            parent_path=three_frame_video,
            decoded_frame_index=0,
            recipe_version=service.FRAME_RECIPE_VERSION,
            decoder_identity=decoder,
            output_temp=tmp_path / "invalid.png",
        )


def test_decode_rejects_oversized_output(
    three_frame_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoder = service.ffmpeg_decoder_identity()
    real_run = subprocess.run

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        if args[:2] == ["ffmpeg", "-nostdin"]:
            with Path(args[-1]).open("wb") as frame:
                frame.truncate(service.MAX_FRAME_BYTES + 1)
            return subprocess.CompletedProcess(args, 0, b"", b"")
        return real_run(args, **kwargs)

    monkeypatch.setattr(service.subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="size limit"):
        service.decode_frame(
            parent_path=three_frame_video,
            decoded_frame_index=0,
            recipe_version=service.FRAME_RECIPE_VERSION,
            decoder_identity=decoder,
            output_temp=tmp_path / "large.png",
        )


def test_publish_frame_preserves_unequal_existing_destination(three_frame_video: Path, tmp_path: Path) -> None:
    temp = tmp_path / "decoded.png"
    probe = service.decode_frame(
        parent_path=three_frame_video,
        decoded_frame_index=0,
        recipe_version=service.FRAME_RECIPE_VERSION,
        decoder_identity=service.ffmpeg_decoder_identity(),
        output_temp=temp,
    )
    media_root = tmp_path / "media"
    final = media_root / "frames" / "m8f-test.png"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"competitor")
    identity = CandidateIdentity(
        candidate_id="m8f-test",
        user_id="u1",
        project_name="demo",
        artifact_key="frame:test",
        expected_content_digest=probe.content_digest,
    )
    with pytest.raises(CandidateDuplicateConflictError):
        service.publish_frame(temp=temp, final=final, media_root=media_root, identity=identity, probe=probe)
    assert final.read_bytes() == b"competitor"


def test_publish_frame_admits_equal_byte_replay_without_replacing_file(three_frame_video: Path, tmp_path: Path) -> None:
    temp = tmp_path / "decoded.png"
    probe = service.decode_frame(
        parent_path=three_frame_video,
        decoded_frame_index=1,
        recipe_version=service.FRAME_RECIPE_VERSION,
        decoder_identity=service.ffmpeg_decoder_identity(),
        output_temp=temp,
    )
    media_root = tmp_path / "media"
    final = media_root / "frames" / "m8f-test.png"
    identity = CandidateIdentity(
        candidate_id="m8f-test",
        user_id="u1",
        project_name="demo",
        artifact_key="frame:test",
        expected_content_digest=probe.content_digest,
    )
    first = service.publish_frame(temp=temp, final=final, media_root=media_root, identity=identity, probe=probe)
    inode = final.stat().st_ino
    replay = service.publish_frame(temp=temp, final=final, media_root=media_root, identity=identity, probe=probe)

    assert first == replay
    assert final.stat().st_ino == inode
    assert first.content_digest == probe.content_digest
    assert first.media_probe_digest == probe.probe_digest
