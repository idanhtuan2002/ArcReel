"""The live smoke runs the production prompt, parse and normalizer on the model's exact response."""

from __future__ import annotations

import json
from typing import Any

import pytest

from lib.text_backends.base import TextGenerationRequest, TextGenerationResult
from scripts.r2.spatial_live_smoke import run
from tests.integration.server.routers.test_spatial_execution import _response


class _Model:
    def __init__(self, text: str) -> None:
        self.text = text
        self.images: list[bytes] = []

    async def generate(self, request: TextGenerationRequest, *, execution_id: str) -> TextGenerationResult:
        assert request.images is not None
        self.images = [image.path.read_bytes() for image in request.images if image.path is not None]
        return TextGenerationResult(text=self.text, provider="gemini", model="m")


async def _run(model: _Model) -> dict[str, Any]:
    return await run(
        master=b"master-png",
        reverse=b"reverse-png",
        scene="Lobby",
        model_name="m",
        model=model,
        submitted_base_url="https://example.test",
    )


@pytest.mark.asyncio
async def test_a_valid_response_passes_and_records_only_digests() -> None:
    model = _Model(json.dumps(_response()))

    evidence = await _run(model)

    assert model.images == [b"master-png", b"reverse-png"]
    assert (evidence["parse"], evidence["normalize"], evidence["result"]) == ("PASS", "PASS", "PASS")
    assert evidence["assertions_by_class"] == {"GAP": 1, "INFERRED": 1, "VISIBLE": 2}
    assert "master-png" not in json.dumps(evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize(("text", "failed_step"), [("not json", "parse"), ('{"schema_version": "v0"}', "normalize")])
async def test_an_unusable_response_fails_at_its_step(text: str, failed_step: str) -> None:
    evidence = await _run(_Model(text))

    assert evidence["result"] == "FAIL"
    assert evidence[failed_step].startswith("FAIL")
