"""The text-backend vision call sends MASTER then REVERSE as image files and returns UTF-8 bytes."""

from __future__ import annotations

import pytest

from lib.text_backends.base import TextGenerationRequest, TextGenerationResult
from server.services.spatial_execution import text_backend_spatial_vision


class _RecordingBackend:
    def __init__(self) -> None:
        self.images: list[bytes] = []
        self.prompt = ""
        self.execution_id = ""

    async def generate(self, request: TextGenerationRequest, *, execution_id: str) -> TextGenerationResult:
        self.execution_id = execution_id
        self.prompt = request.prompt
        assert request.images is not None
        self.images = [image.path.read_bytes() for image in request.images if image.path is not None]
        return TextGenerationResult(
            text='{"schema_version": "r2-spatial-response-v1"} 空间', provider="fake", model="m"
        )


@pytest.mark.asyncio
async def test_vision_call_orders_images_and_encodes_text() -> None:
    backend = _RecordingBackend()
    call = text_backend_spatial_vision(backend)
    raw = await call(prompt="analyze", master_png=b"master-png", reverse_png=b"reverse-png", execution_id="exec-1")
    assert backend.execution_id == "exec-1"
    assert backend.prompt == "analyze"
    assert backend.images == [b"master-png", b"reverse-png"]
    assert raw == '{"schema_version": "r2-spatial-response-v1"} 空间'.encode()
