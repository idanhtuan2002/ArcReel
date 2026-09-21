"""M3 real-media closure Task 5: the H.264 factual-product fixture (Task 4)
through the full real chain -- director -> preparation -> real Remotion
render -> host -> composite. Proves the second Golden A topic renders real,
non-solid-color media and exercises all three production methods with
visibly distinct output, mirroring test_golden_a_composition.py's shape for
the original Git topic."""

import hashlib
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from r2.contracts.enums import ProductionMethod
from r2.m3.composition import GoldenAComposer
from r2.m3.director import FixtureOpenMontageBackendH264, GoldenAOpenMontageAdapter
from r2.m3.factual_fixture import load_golden_a_factual_bundle
from r2.m3.host_integration import GoldenAHostIntegration, compute_content_fingerprint
from r2.m3.local_production import GoldenALocalProducer
from r2.m3.preparation import GoldenAProductionPreparation
from r2.production import DependencySnapshot
from tests.fixtures.r2.m3_media_assertions import frame_pixel_stddev

_FIXTURE = Path(__file__).resolve().parents[4] / "r2" / "m3" / "fixtures" / "golden_a_h264.json"
_REUSED_ASSET = "r2/m3/fixtures/assets/reused_terminal_frame.svg"
_FIXED_TIME = datetime(2026, 9, 22, 0, 0, tzinfo=UTC)
_CLAIM_BY_SHOT = {"SH01": 1, "SH02": 2, "SH03": 3}


def _dep_for(index: int) -> DependencySnapshot:
    return DependencySnapshot(
        ref=f"claim:CLAIM-H264-{index:03d}",
        version="1",
        fingerprint=hashlib.sha256(f"CLAIM-H264-{index:03d}-v1".encode()).hexdigest(),
    )


def _statement_for(index: int) -> str:
    bundle = load_golden_a_factual_bundle(_FIXTURE)
    claims_by_id = {claim.id: claim for claim in bundle.claim_ledger.claims}
    return claims_by_id[f"CLAIM-H264-{index:03d}"].statement


def _produced_host(tmp_path: Path):
    bundle = load_golden_a_factual_bundle(_FIXTURE)
    direction = GoldenAOpenMontageAdapter(FixtureOpenMontageBackendH264()).direct(bundle.script)
    prepared = GoldenAProductionPreparation().prepare(direction.shots, reused_asset_ref=_REUSED_ASSET)

    host = GoldenAHostIntegration(tmp_path / "project", resource_type="videos", episode=1)
    producer = GoldenALocalProducer()
    produced_by_shot = {}

    for item in prepared:
        dep = _dep_for(_CLAIM_BY_SHOT[item.shot.id])
        content_fp = compute_content_fingerprint(item.shot, [dep])
        display_text = (
            None if item.method.method is ProductionMethod.REUSE else _statement_for(_CLAIM_BY_SHOT[item.shot.id])
        )
        produced = producer.produce(
            item,
            work_dir=tmp_path / "produced" / item.shot.id,
            display_text=display_text,
        )
        produced_by_shot[item.shot.id] = produced
        registered = host.stage_candidate(
            target_ref=item.shot.id,
            content_fingerprint=content_fp,
            produced=produced,
            content_basis=item.shot.content_basis,
            direct_dependencies=[dep],
            contract_version=item.shot.version,
            contract_schema_version=item.shot.schema_version,
        )
        host.approve(
            registered,
            approval_record=f"APR-{item.shot.id}",
            selected_by="human-showrunner",
            selected_at=_FIXED_TIME,
        )

    return host, produced_by_shot


@pytest.mark.timeout(600)  # 3 real ~22-25s-shot Remotion renders + a compose; see pyproject.toml note
def test_h264_factual_product_renders_real_media_with_three_distinct_methods(tmp_path: Path) -> None:
    host, produced_by_shot = _produced_host(tmp_path)

    result = GoldenAComposer().compose(
        host,
        ["SH01", "SH02", "SH03"],
        output_path=tmp_path / "final.mp4",
    )

    assert result.method is ProductionMethod.COMPOSITE
    assert result.external_provider_cost == Decimal("0")
    assert result.path.is_file()
    assert result.path.stat().st_size > 0
    assert len(result.source_master_refs) == 3
    assert 60.0 <= result.duration_seconds <= 180.0

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=nw=1:nk=1",
            str(result.path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "video"

    # Method-diversity proof: REUSE, DETERMINISTIC (x2), and COMPOSITE are all
    # present, and every one of the four real outputs is byte-distinct.
    shot_methods = {asset.method for asset in produced_by_shot.values()}
    assert shot_methods == {ProductionMethod.REUSE, ProductionMethod.DETERMINISTIC}
    all_hashes = {asset.sha256 for asset in produced_by_shot.values()} | {result.sha256}
    assert len(all_hashes) == len(produced_by_shot) + 1

    assert produced_by_shot["SH01"].source_master_refs  # REUSE: real source hash recorded

    # Every real render is content-bearing, not a solid color -- checked on
    # each shot's own asset, not just the final concat.
    for shot_id, asset in produced_by_shot.items():
        frame_dir = tmp_path / f"frame-{shot_id}"
        frame_dir.mkdir()
        stddev = frame_pixel_stddev(asset.path, frame_dir)
        assert stddev > 5.0, f"{shot_id} frame looks solid-color (pixel stddev={stddev})"
