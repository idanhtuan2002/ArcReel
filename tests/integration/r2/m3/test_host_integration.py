import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lib.version_manager import VersionManager
from r2.contracts import GenerationCandidate
from r2.contracts.enums import (
    CandidateSelectionStatus,
    GenerationLifecycleStatus,
)
from r2.m3.director import FixtureOpenMontageBackend, GoldenAOpenMontageAdapter
from r2.m3.factual_fixture import load_golden_a_factual_bundle
from r2.m3.host_integration import (
    GoldenAHostIntegration,
    RegisteredGoldenACandidate,
    compute_content_fingerprint,
)
from r2.m3.local_production import GoldenALocalProducer
from r2.m3.preparation import GoldenAProductionPreparation
from r2.production import DependencySnapshot


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup_sh01(tmp_path):
    script = load_golden_a_factual_bundle().script
    direction = GoldenAOpenMontageAdapter(FixtureOpenMontageBackend()).direct(script)
    prepared = GoldenAProductionPreparation().prepare(
        direction.shots,
        reused_asset_ref=("r2/m3/fixtures/assets/reused_terminal_frame.svg"),
    )[0]

    resource_type = "video" if "video" in VersionManager.RESOURCE_TYPES else sorted(VersionManager.RESOURCE_TYPES)[0]
    host = GoldenAHostIntegration(
        tmp_path / "project",
        resource_type=resource_type,
        episode=1,
    )
    dep = DependencySnapshot(
        ref="claim:CLAIM-001",
        version="1",
        fingerprint=hashlib.sha256(b"claim-001-v1").hexdigest(),
    )
    fingerprint = compute_content_fingerprint(
        prepared.shot,
        [dep],
    )
    return prepared, host, dep, fingerprint, resource_type


def test_real_host_b_c_d_master_semantics_and_restart(tmp_path):
    prepared, host, dep, fingerprint, resource_type = setup_sh01(tmp_path)
    producer = GoldenALocalProducer()

    produced_b = producer.produce(
        prepared,
        work_dir=tmp_path / "b",
        execution_variant="B",
    )
    b = host.stage_candidate(
        target_ref=prepared.shot.id,
        content_fingerprint=fingerprint,
        produced=produced_b,
        content_basis=prepared.shot.content_basis,
        direct_dependencies=[dep],
        contract_version=prepared.shot.version,
        contract_schema_version=prepared.shot.schema_version,
    )
    promoted_b = host.approve(
        b,
        approval_record="APR-B",
        selected_by="human-showrunner",
        selected_at=datetime.now(UTC),
    )
    assert promoted_b.selected_candidate_id == b.candidate.id
    assert sha(host.current_file_for(prepared.shot.id)) == produced_b.sha256

    failed = GenerationCandidate(
        id="CAND-C-FAILED",
        target_ref=prepared.shot.id,
        content_fingerprint=fingerprint,
        execution_fingerprint="failed-exec",
        provider_execution_ref="local:ffmpeg:failed",
        output_asset_ref="failed://none",
        lifecycle_state=GenerationLifecycleStatus.FAILED,
        selection_state=CandidateSelectionStatus.UNREVIEWED,
    )
    failed_registered = RegisteredGoldenACandidate(
        artifact_key=b.artifact_key,
        candidate=failed,
        host_version_ref="999",
    )
    with pytest.raises(ValueError, match="GENERATED"):
        host.approve(
            failed_registered,
            approval_record="APR-C",
            selected_by="human-showrunner",
            selected_at=datetime.now(UTC),
        )
    assert host.snapshot(prepared.shot.id).approved_master.selected_candidate_id == b.candidate.id
    assert sha(host.current_file_for(prepared.shot.id)) == produced_b.sha256

    produced_d = producer.produce(
        prepared,
        work_dir=tmp_path / "d",
        execution_variant="D",
    )
    assert produced_d.sha256 != produced_b.sha256
    d = host.stage_candidate(
        target_ref=prepared.shot.id,
        content_fingerprint=fingerprint,
        produced=produced_d,
        content_basis=prepared.shot.content_basis,
        direct_dependencies=[dep],
        contract_version=prepared.shot.version,
        contract_schema_version=prepared.shot.schema_version,
    )

    # Successful but unapproved D preserves B.
    assert host.snapshot(prepared.shot.id).approved_master.selected_candidate_id == b.candidate.id
    assert sha(host.current_file_for(prepared.shot.id)) == produced_b.sha256

    host.approve(
        d,
        approval_record="APR-D",
        selected_by="human-showrunner",
        selected_at=datetime.now(UTC),
    )
    assert sha(host.current_file_for(prepared.shot.id)) == produced_d.sha256
    assert host.snapshot(prepared.shot.id).approved_master.selected_candidate_id == d.candidate.id

    restarted = GoldenAHostIntegration(
        tmp_path / "project",
        resource_type=resource_type,
        episode=1,
    )
    assert restarted.snapshot(prepared.shot.id).approved_master.selected_candidate_id == d.candidate.id
    assert sha(restarted.current_file_for(prepared.shot.id)) == produced_d.sha256


def test_manifest_metadata_keeps_factual_basis_and_dependencies(tmp_path):
    prepared, host, dep, fingerprint, _ = setup_sh01(tmp_path)
    produced = GoldenALocalProducer().produce(
        prepared,
        work_dir=tmp_path / "asset",
        execution_variant="metadata",
    )
    host.stage_candidate(
        target_ref=prepared.shot.id,
        content_fingerprint=fingerprint,
        produced=produced,
        content_basis=prepared.shot.content_basis,
        direct_dependencies=[dep],
        contract_version=prepared.shot.version,
        contract_schema_version=prepared.shot.schema_version,
    )
    metadata = host.snapshot(prepared.shot.id)
    assert metadata.content_basis.basis_type.value == "FACTUAL"
    assert metadata.direct_dependencies == [dep]
