"""GoldenALocalProducer's real per-shot rendering. Moved from tests/unit/ to
tests/integration/ when the color-stub was replaced by a real Remotion
render (M3 real-media closure Task 3) -- a real `npx remotion render`
subprocess is not a unit-tier operation (not fast, not I/O-free), unlike the
near-instant `ffmpeg color=...` it replaced."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from r2.contracts.enums import ProductionMethod
from r2.m3.director import FixtureOpenMontageBackend, GoldenAOpenMontageAdapter
from r2.m3.factual_fixture import load_golden_a_factual_bundle
from r2.m3.local_production import GoldenALocalProducer
from r2.m3.preparation import GoldenAProductionPreparation
from r2.m3.render_projection import UnimplementedRenderMethodError


def prepared(reused_asset_ref: str | None):
    script = load_golden_a_factual_bundle().script
    shots = GoldenAOpenMontageAdapter(FixtureOpenMontageBackend()).direct(script).shots
    return GoldenAProductionPreparation().prepare(
        shots,
        reused_asset_ref=reused_asset_ref,
    )


def test_blocked_shot_cannot_enter_local_producer(tmp_path: Path) -> None:
    sh01 = prepared(None)[0]
    with pytest.raises(ValueError, match="BLOCKED"):
        GoldenALocalProducer().produce(sh01, work_dir=tmp_path)


@pytest.mark.timeout(300)  # one real ~22s-shot Remotion render; see pyproject.toml note
def test_reuse_production_preserves_source_and_emits_valid_mp4(tmp_path: Path) -> None:
    source = Path("r2/m3/fixtures/assets/reused_terminal_frame.svg")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    sh01 = prepared(str(source))[0]
    asset = GoldenALocalProducer().produce(sh01, work_dir=tmp_path)
    after = hashlib.sha256(source.read_bytes()).hexdigest()

    assert before == after  # the real source file is only ever read, never mutated
    assert asset.method is ProductionMethod.REUSE
    assert asset.external_provider_cost == Decimal("0")
    assert asset.path.is_file()
    assert asset.path.stat().st_size > 0
    assert asset.source_master_refs
    assert asset.source_master_refs[0].endswith(f":{before}")
    subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=nw=1",
            str(asset.path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_deterministic_requires_real_display_text(tmp_path: Path) -> None:
    sh02 = prepared("r2/m3/fixtures/assets/reused_terminal_frame.svg")[1]
    with pytest.raises(ValueError, match="requires real display text"):
        GoldenALocalProducer().produce(sh02, work_dir=tmp_path, display_text=None)


@pytest.mark.timeout(500)  # two real ~25s-shot Remotion renders; see pyproject.toml note
def test_deterministic_output_is_byte_stable_for_the_same_display_text(tmp_path: Path) -> None:
    sh02 = prepared("r2/m3/fixtures/assets/reused_terminal_frame.svg")[1]
    producer = GoldenALocalProducer()
    claim_text = "git commit records the current index contents as a new commit."
    a = producer.produce(sh02, work_dir=tmp_path / "a", display_text=claim_text)
    b = producer.produce(sh02, work_dir=tmp_path / "b", display_text=claim_text)
    assert a.sha256 == b.sha256
    assert a.execution_fingerprint == b.execution_fingerprint
    assert a.external_provider_cost == Decimal("0")


@pytest.mark.timeout(500)  # two real ~25s-shot Remotion renders; see pyproject.toml note
def test_different_display_text_changes_the_rendered_output(tmp_path: Path) -> None:
    sh02 = prepared("r2/m3/fixtures/assets/reused_terminal_frame.svg")[1]
    producer = GoldenALocalProducer()
    a = producer.produce(sh02, work_dir=tmp_path / "a", display_text="the first claim statement")
    b = producer.produce(sh02, work_dir=tmp_path / "b", display_text="a completely different claim statement")
    assert a.method is b.method
    assert a.sha256 != b.sha256
    assert a.execution_fingerprint != b.execution_fingerprint


def test_an_out_of_scope_method_raises_explicitly(tmp_path: Path) -> None:
    # STOCK is a real ProductionMethod but has no real content source wired
    # in this closure (spec section 1) -- GoldenAProductionPreparation never
    # assigns it today, so this test constructs the case directly rather
    # than relying on preparation to produce it.
    sh01 = prepared("r2/m3/fixtures/assets/reused_terminal_frame.svg")[0]
    stock_assigned = replace(sh01, method=replace(sh01.method, method=ProductionMethod.STOCK))
    with pytest.raises(UnimplementedRenderMethodError):
        GoldenALocalProducer().produce(stock_assigned, work_dir=tmp_path)
