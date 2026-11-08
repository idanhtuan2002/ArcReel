"""A media route outside the launch profile is admitted by one checked sample made through it."""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from typing import ClassVar

import pytest
from PIL import Image

from lib.image_backends.base import ImageGenerationResult
from r2.automation.profiles import route_digest
from r2.contracts.automation import ModelRoute
from server.production_run import media_probe
from server.production_run.media_probe import passed_probes, probe_evidence, probe_media_route, probe_path
from server.production_run.unit_checks import clip_problem

ROUTE = ModelRoute(
    role="image",
    provider_id="custom-12",
    model_id="cloud-painter",
    model_identity="cloud/cloud-painter",
    config_digest="sha256:" + "4" * 64,
    local=False,
    paid=True,
    currency="USD",
    max_cost_per_call=10,
)


class _Resolver:
    def __init__(self, _sessions) -> None:
        pass

    @contextlib.asynccontextmanager
    async def session(self):
        yield self


class _Ledger:
    calls: ClassVar[list[dict]] = []

    def __init__(self, **_kwargs) -> None:
        pass

    def record(self, **kwargs):
        _Ledger.calls.append(kwargs)
        ledger = self

        class _Call:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def success(self, result) -> None:
                ledger.result = result

        return _Call()


class _Painter:
    def __init__(self, colour) -> None:
        self.colour = colour

    async def generate(self, request):
        picture = _noisy() if self.colour is None else Image.new("RGB", (576, 1024), self.colour)
        picture.save(request.output_path)
        return ImageGenerationResult(image_path=request.output_path, provider="custom-12", model="cloud-painter")


def _noisy(size=(576, 1024)) -> Image.Image:
    return Image.effect_noise(size, 60).convert("RGB")


@pytest.fixture
def backend(monkeypatch):
    chosen: dict = {}

    async def assemble(**kwargs):
        chosen.update(kwargs)
        return chosen["backend"]

    monkeypatch.setattr(media_probe, "assemble_backend", assemble)
    monkeypatch.setattr(media_probe, "Ledger", _Ledger)
    monkeypatch.setattr(media_probe, "ConfigResolver", _Resolver)
    return chosen


async def test_a_passing_sample_admits_exactly_its_route(backend, tmp_path: Path) -> None:
    backend["backend"] = _Painter(None)
    evidence = await probe_media_route(
        None, route=ROUTE, receipts=tmp_path, voice="v", width=576, height=1024, user_id="u"
    )
    assert evidence["passed"] is True
    assert backend["media_type"] == "image"
    assert _Ledger.calls[-1]["call_type"] == "image"
    assert passed_probes(tmp_path, (ROUTE,)) == {route_digest(ROUTE)}
    changed = ROUTE.model_copy(update={"config_digest": "sha256:" + "5" * 64})
    assert passed_probes(tmp_path, (changed,)) == frozenset()
    sample = probe_path(tmp_path, ROUTE).with_suffix("") / "sample.png"
    Image.new("RGB", (576, 1024), (0, 0, 0)).save(sample)
    assert probe_evidence(tmp_path, ROUTE) is None


async def test_a_blank_sample_or_a_failing_backend_is_recorded_as_not_passed(backend, tmp_path: Path) -> None:
    backend["backend"] = _Painter((255, 255, 255))
    evidence = await probe_media_route(
        None, route=ROUTE, receipts=tmp_path, voice="v", width=576, height=1024, user_id="u"
    )
    assert (evidence["passed"], evidence["problem"]) == (False, "IMAGE_BLANK")

    class Broken:
        async def generate(self, request):
            raise RuntimeError("provider refused")

    backend["backend"] = Broken()
    evidence = await probe_media_route(
        None, route=ROUTE, receipts=tmp_path, voice="v", width=576, height=1024, user_id="u"
    )
    assert (evidence["problem"], evidence["error"]) == ("GENERATION_FAILED", "RuntimeError")
    assert passed_probes(tmp_path, (ROUTE,)) == frozenset()
    assert passed_probes(None, (ROUTE,)) == frozenset()


def _clip(path: Path, size: str, seconds: float) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=s={size}:r=24:d={seconds}",
            str(path),
        ],
        check=True,
    )
    return path


def test_a_clip_must_decode_in_the_projects_orientation_and_last_a_second(tmp_path: Path) -> None:
    assert clip_problem(_clip(tmp_path / "ok.mp4", "576x1024", 2), portrait=True) is None
    assert clip_problem(_clip(tmp_path / "wide.mp4", "1024x576", 2), portrait=True) == "VIDEO_WRONG_ORIENTATION"
    assert clip_problem(_clip(tmp_path / "short.mp4", "576x1024", 0.5), portrait=True) == "VIDEO_TOO_SHORT"
    assert clip_problem(tmp_path / "missing.mp4", portrait=True) == "VIDEO_UNREADABLE"
