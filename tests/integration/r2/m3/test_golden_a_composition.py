from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import subprocess

import pytest

from r2.contracts.enums import ProductionMethod
from r2.production import DependencySnapshot
from r2.m3.composition import GoldenAComposer
from r2.m3.director import FixtureOpenMontageBackend, GoldenAOpenMontageAdapter
from r2.m3.factual_fixture import load_golden_a_factual_bundle
from r2.m3.host_integration import GoldenAHostIntegration, compute_content_fingerprint
from r2.m3.local_production import GoldenALocalProducer
from r2.m3.preparation import GoldenAProductionPreparation


FIXED_TIME = datetime(2026, 9, 6, 22, 30, tzinfo=timezone.utc)


def dep_for(index: int) -> DependencySnapshot:
    return DependencySnapshot(
        ref=f"claim:CLAIM-{index:03d}",
        version="1",
        fingerprint=hashlib.sha256(
            f"CLAIM-{index:03d}-v1".encode()
        ).hexdigest(),
    )


def approved_host(tmp_path):
    bundle = load_golden_a_factual_bundle()
    direction = GoldenAOpenMontageAdapter(
        FixtureOpenMontageBackend()
    ).direct(bundle.script)
    prepared = GoldenAProductionPreparation().prepare(
        direction.shots,
        reused_asset_ref="r2/m3/fixtures/assets/reused_terminal_frame.svg",
    )
    host = GoldenAHostIntegration(
        tmp_path / "project",
        resource_type="videos",
        episode=1,
    )
    producer = GoldenALocalProducer()
    claim_by_shot = {"SH01": 1, "SH02": 2, "SH03": 2, "SH04": 3}

    for item in prepared:
        dep = dep_for(claim_by_shot[item.shot.id])
        content_fp = compute_content_fingerprint(item.shot, [dep])
        produced = producer.produce(
            item,
            work_dir=tmp_path / "produced" / item.shot.id,
            execution_variant="task7",
        )
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
            selected_at=FIXED_TIME,
        )

    return host


def test_composer_requires_approved_masters(tmp_path):
    host = GoldenAHostIntegration(
        tmp_path / "empty",
        resource_type="videos",
        episode=1,
    )
    with pytest.raises((KeyError, ValueError)):
        GoldenAComposer().compose(
            host,
            ["SH01"],
            output_path=tmp_path / "final.mp4",
        )


def test_ffmpeg_composes_real_approved_masters_into_final_mp4(tmp_path):
    host = approved_host(tmp_path)
    result = GoldenAComposer().compose(
        host,
        ["SH01", "SH02", "SH03", "SH04"],
        output_path=tmp_path / "final.mp4",
    )

    assert result.method is ProductionMethod.COMPOSITE
    assert result.external_provider_cost == Decimal("0")
    assert result.path.is_file()
    assert result.path.stat().st_size > 0
    assert len(result.source_master_refs) == 4
    assert 60.0 <= result.duration_seconds <= 90.0

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type",
            "-of", "default=nw=1:nk=1",
            str(result.path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "video"
