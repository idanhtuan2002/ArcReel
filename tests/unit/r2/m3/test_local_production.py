import hashlib
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from r2.contracts.enums import ProductionMethod
from r2.m3.director import FixtureOpenMontageBackend, GoldenAOpenMontageAdapter
from r2.m3.factual_fixture import load_golden_a_factual_bundle
from r2.m3.local_production import GoldenALocalProducer
from r2.m3.preparation import GoldenAProductionPreparation


def prepared(reused_asset_ref: str | None):
    script = load_golden_a_factual_bundle().script
    shots = GoldenAOpenMontageAdapter(FixtureOpenMontageBackend()).direct(script).shots
    return GoldenAProductionPreparation().prepare(
        shots,
        reused_asset_ref=reused_asset_ref,
    )


def test_blocked_shot_cannot_enter_local_producer(tmp_path):
    sh01 = prepared(None)[0]
    with pytest.raises(ValueError, match="BLOCKED"):
        GoldenALocalProducer().produce(sh01, work_dir=tmp_path)


def test_reuse_production_preserves_source_and_emits_valid_mp4(tmp_path):
    source = Path("r2/m3/fixtures/assets/reused_terminal_frame.svg")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    sh01 = prepared(str(source))[0]
    asset = GoldenALocalProducer().produce(sh01, work_dir=tmp_path)
    after = hashlib.sha256(source.read_bytes()).hexdigest()

    assert before == after
    assert asset.method is ProductionMethod.REUSE
    assert asset.external_provider_cost == Decimal("0")
    assert asset.path.is_file()
    assert asset.path.stat().st_size > 0
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


def test_deterministic_output_is_byte_stable_for_same_execution_variant(tmp_path):
    sh02 = prepared("r2/m3/fixtures/assets/reused_terminal_frame.svg")[1]
    producer = GoldenALocalProducer()
    a = producer.produce(sh02, work_dir=tmp_path / "a", execution_variant="same")
    b = producer.produce(sh02, work_dir=tmp_path / "b", execution_variant="same")
    assert a.sha256 == b.sha256
    assert a.execution_fingerprint == b.execution_fingerprint
    assert a.external_provider_cost == Decimal("0")


def test_execution_variant_changes_execution_fingerprint_not_method(tmp_path):
    sh02 = prepared("r2/m3/fixtures/assets/reused_terminal_frame.svg")[1]
    producer = GoldenALocalProducer()
    a = producer.produce(sh02, work_dir=tmp_path / "a", execution_variant="A")
    b = producer.produce(sh02, work_dir=tmp_path / "b", execution_variant="B")
    assert a.method is b.method is ProductionMethod.DETERMINISTIC
    assert a.execution_fingerprint != b.execution_fingerprint
