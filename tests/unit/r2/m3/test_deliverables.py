"""Export eligibility is bound to the bytes selected by Gate C."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from lib.version_manager import PaidVersionCommit
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import ProductionMethod
from r2.m3.deliverables import (
    COMPOSITE_CONTRACT_TYPE,
    SourceMasterMismatchError,
    composite_dependencies,
    current_deliverables,
    exportable_deliverable,
    verified_export_snapshot,
    write_export_copy,
)
from r2.m3.host_integration import GoldenAHostIntegration
from r2.m3.render_plan import RenderedCutAsset
from server.routers import gates


def _approved_final(project_dir: Path, *, claimed_data: bytes = b"approved final") -> GoldenAHostIntegration:
    host = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1)
    candidate = project_dir / "candidate.mp4"
    candidate.write_bytes(b"approved final")
    digest = hashlib.sha256(claimed_data).hexdigest()
    registered = host.stage_candidate(
        target_ref="FINAL",
        content_fingerprint="semantic-final-v1",
        produced=RenderedCutAsset(
            target_ref="FINAL",
            method=ProductionMethod.COMPOSITE,
            path=candidate,
            sha256="sha256:" + digest,
            duration_seconds=1,
            execution_fingerprint="execution-final-v1",
            tool="ffmpeg",
            tool_version="7",
            wall_time_seconds=1,
            external_provider_cost=Decimal(0),
            source_master_refs=(),
        ),
        content_basis=ContentBasis(basis_type="FACTUAL", basis_version="v1", refs=["research:RP-1"]),
        direct_dependencies=[],
        contract_version=1,
        contract_schema_version="1",
        contract_type=COMPOSITE_CONTRACT_TYPE,
    )
    host.approve(registered, approval_record="APR-FINAL", selected_by="operator", selected_at=datetime.now(UTC))
    write_export_copy(host, "FINAL")
    return host


def test_replacing_both_final_and_export_cannot_authorize_new_bytes(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    host = _approved_final(project_dir)
    replacement = b"unapproved replacement"
    host.current_file_for("FINAL").write_bytes(replacement)
    (project_dir / "output" / "ep1-FINAL.mp4").write_bytes(replacement)

    new_digest = "sha256:" + hashlib.sha256(replacement).hexdigest()
    assert current_deliverables(project_dir)[0].exportable is False
    assert exportable_deliverable(project_dir, new_digest) is None


def test_token_listing_only_includes_exportable_deliverables(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    host = _approved_final(project_dir)
    assert len(gates._deliverable_view(project_dir)) == 1

    host.current_file_for("FINAL").write_bytes(b"unapproved replacement")
    assert gates._deliverable_view(project_dir) == []


def test_staged_bytes_must_match_the_verified_candidate_digest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="staged candidate does not match"):
        _approved_final(tmp_path / "project", claimed_data=b"different bytes")


def test_gate_d_digest_must_use_the_canonical_sha256_form(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    _approved_final(project_dir)
    digest = current_deliverables(project_dir)[0].approved_sha256
    assert digest is not None
    assert exportable_deliverable(project_dir, digest) is None


def test_export_copy_rejects_a_changed_promoted_final(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    host = _approved_final(project_dir)
    host.current_file_for("FINAL").write_bytes(b"unapproved replacement")
    with pytest.raises(ValueError, match="approved final"):
        write_export_copy(host, "FINAL")


def test_a_composite_cannot_masquerade_as_a_source_shot(tmp_path: Path) -> None:
    host = _approved_final(tmp_path / "project")
    approved = host.snapshot("FINAL").approved_master
    assert approved is not None
    source_ref = f"FINAL:{approved.selected_candidate_id}:{approved.host_version_ref}"
    with pytest.raises(SourceMasterMismatchError):
        composite_dependencies(host, [source_ref])


def test_current_file_rejects_a_symlinked_managed_directory(tmp_path: Path) -> None:
    host = GoldenAHostIntegration(tmp_path / "project", resource_type="videos", episode=1)
    (tmp_path / "outside").mkdir()
    (host.project_dir / "r2_m3_current").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(ValueError, match="project"):
        host.current_file_for("FINAL")


@pytest.mark.parametrize("linked_path", ["versions", "versions/videos", "versions/versions.json"])
def test_gate_c_rejects_symlinked_version_storage(tmp_path: Path, linked_path: str) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = project_dir / linked_path
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=linked_path != "versions/versions.json")

    with pytest.raises(ValueError, match="project"):
        GoldenAHostIntegration(project_dir, resource_type="videos", episode=1)


def test_download_uses_the_bytes_verified_before_path_replacement(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    _approved_final(project_dir)
    digest = current_deliverables(project_dir)[0].approved_sha256
    assert digest is not None
    result = verified_export_snapshot(project_dir, "sha256:" + digest)
    assert result is not None
    _deliverable, snapshot = result
    try:
        (project_dir / "output" / "ep1-FINAL.mp4").write_bytes(b"replaced after verification")
        assert snapshot.read() == b"approved final"
    finally:
        snapshot.close()


def test_staged_candidates_get_distinct_paths_even_with_the_same_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "project"
    host = _approved_final(project_dir)
    candidate = project_dir / "candidate.mp4"
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    staged_paths: list[Path] = []

    def capture_commit(_resource_type: str, _target_ref: str, _prompt: str, **kwargs: object) -> PaidVersionCommit:
        staged_paths.append(Path(kwargs["staged_file"]))
        return PaidVersionCommit(version=42, selected=False)

    monkeypatch.setattr(host.versions, "commit_staged_paid_version", capture_commit)
    produced = RenderedCutAsset(
        target_ref="FINAL",
        method=ProductionMethod.COMPOSITE,
        path=candidate,
        sha256=digest,
        duration_seconds=1,
        execution_fingerprint="same-fingerprint",
        tool="ffmpeg",
        tool_version="7",
        wall_time_seconds=1,
        external_provider_cost=Decimal(0),
        source_master_refs=(),
    )
    for _ in range(2):
        host.stage_candidate(
            target_ref="FINAL",
            content_fingerprint="semantic-final-v1",
            produced=produced,
            content_basis=ContentBasis(basis_type="FACTUAL", basis_version="v1", refs=["research:RP-1"]),
            direct_dependencies=[],
            contract_version=1,
            contract_schema_version="1",
            contract_type=COMPOSITE_CONTRACT_TYPE,
        )
    assert len(staged_paths) == 2
    assert staged_paths[0] != staged_paths[1]
    assert all(path.read_bytes() == b"approved final" for path in staged_paths)
