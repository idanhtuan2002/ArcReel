"""Offline backend fixture for the proposed silent two-view M8-C route."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from PIL import Image

from lib.video_backends.base import VideoAudioMode, VideoGenerationRequest
from lib.video_backends.kling import KlingVideoBackend
from r2.contracts.fingerprints import canonical_json_bytes
from r2.host_hardening.route_inventory import HOST_VIDEO_ADAPTER_VERSION, require_submit_route


def test_kling_silent_multiview_route_preserves_ordered_frame_bytes(tmp_path: Path) -> None:
    front = tmp_path / "front.png"
    reverse = tmp_path / "reverse.png"
    Image.new("RGB", (4, 4), (240, 20, 20)).save(front)
    Image.new("RGB", (4, 4), (20, 20, 240)).save(reverse)

    backend = KlingVideoBackend(auth_mode="bearer", api_key="offline-fixture", model="kling-v3-omni")
    request = VideoGenerationRequest(
        prompt="two views of one room",
        output_path=tmp_path / "out.mp4",
        reference_images=[front, reverse],
        generate_audio=False,
    )
    subpath, payload = backend._build_payload(request)
    profile = require_submit_route("kling", f"videos.{subpath}", HOST_VIDEO_ADAPTER_VERSION)

    assert subpath == "multi-image2video"
    assert profile.ref == "kling-videos-multi-image2video@host-video-v1"
    assert backend.video_capabilities.audio_track_for_route("r2v") is VideoAudioMode.ALWAYS_OFF
    assert "sound" not in payload
    assert [base64.b64decode(item["image"]) for item in payload["image_list"]] == [
        front.read_bytes(),
        reverse.read_bytes(),
    ]

    request.reference_images = [reverse, front]
    reverse_subpath, reverse_payload = backend._build_payload(request)
    assert reverse_subpath == subpath
    assert (
        hashlib.sha256(canonical_json_bytes(payload)).digest()
        != hashlib.sha256(canonical_json_bytes(reverse_payload)).digest()
    )
