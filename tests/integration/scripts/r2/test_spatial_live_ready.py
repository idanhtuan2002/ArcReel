"""The live-readiness command's offline parts: fixture images, stored key, configured model and ledger."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.config.service import ConfigService
from lib.db.models.api_call import ApiCall
from lib.ledger import Ledger
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult
from lib.text_generator import TextGenerator
from scripts.r2.qualify_route import CANARY_PROJECT
from scripts.r2.render_spatial_fixture import render
from scripts.r2.spatial_live_ready import FIXTURE_DIR, _CanaryLedgeredModel, store_key, vision_model

type Factory = async_sessionmaker[AsyncSession]


def test_the_committed_fixture_is_the_renderer_output(tmp_path: Path) -> None:
    for name, reverse in (("master.png", False), ("reverse.png", True)):
        render(reverse).save(tmp_path / name, optimize=False)
        assert (
            hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
            == hashlib.sha256((FIXTURE_DIR / name).read_bytes()).hexdigest()
        )
    assert (FIXTURE_DIR / "master.png").read_bytes() != (FIXTURE_DIR / "reverse.png").read_bytes()


@pytest.mark.asyncio
async def test_a_stored_key_configures_the_gemini_vision_model(session_factory: Factory) -> None:
    await store_key("gemini-aistudio", "test-key", session_factory=session_factory)

    async with session_factory() as session:
        stored = await ConfigService(session).get_provider_config("gemini-aistudio")
    _model, base_url = await vision_model("gemini-aistudio", "gemini-3-flash-preview", session_factory=session_factory)

    assert stored["api_key"] == "test-key"
    assert base_url == "https://generativelanguage.googleapis.com"


class _Backend:
    model = "gemini-3-flash-preview"

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        return TextGenerationResult(text="{}", provider="gemini", model=self.model)


@pytest.mark.asyncio
async def test_the_smoke_call_is_ledgered_under_the_canary_project(session_factory: Factory) -> None:
    generator = TextGenerator(_Backend(), Ledger(session_factory=session_factory), "gemini-aistudio")

    await _CanaryLedgeredModel(generator).generate(TextGenerationRequest(prompt="p"), execution_id="unused")

    async with session_factory() as session:
        calls = list((await session.execute(select(ApiCall))).scalars())
    assert [(c.project_name, c.call_type, c.status, c.execution_id) for c in calls] == [
        (CANARY_PROJECT, "text", "success", None)
    ]
