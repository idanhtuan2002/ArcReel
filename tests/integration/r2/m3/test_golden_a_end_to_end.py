import json
import subprocess
from decimal import Decimal

from r2.contracts.enums import ArtifactCurrencyStatus, ProductionMethod
from r2.m3.golden_a import GoldenARunner


def test_single_run_produces_real_60_90s_final_and_three_methods(tmp_path):
    result = GoldenARunner().run(tmp_path)

    assert result.final_path.is_file()
    assert result.final_sha256
    assert 60.0 <= result.final_duration_seconds <= 90.0
    assert set(result.methods) == {
        ProductionMethod.REUSE,
        ProductionMethod.DETERMINISTIC,
        ProductionMethod.COMPOSITE,
    }
    assert result.external_provider_cost == Decimal("0")
    assert result.restart_verified is True

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
            str(result.final_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "video"


def test_lineage_reaches_claim_evidence_and_source(tmp_path):
    result = GoldenARunner().run(tmp_path)
    trace = result.lineage

    assert trace["final"]["target_ref"] == "FINAL-GOLDEN-A"
    assert len(trace["shots"]) == 4
    for shot in trace["shots"]:
        assert shot["approved_master"]["selected_candidate_id"]
        assert shot["shot_spec"]
        assert shot["scene_spec"]
        assert shot["script_sections"]
        assert shot["claims"]
        assert shot["evidence"]
        assert shot["sources"]

    by_shot = {item["shot_spec"]: item for item in trace["shots"]}
    assert by_shot["SH01"]["claims"] == ["CLAIM-001"]
    assert by_shot["SH02"]["claims"] == ["CLAIM-002"]
    assert by_shot["SH03"]["claims"] == ["CLAIM-002"]
    assert by_shot["SH04"]["claims"] == ["CLAIM-003"]


def test_claim2_change_selectively_invalidates_expected_shots_and_final(tmp_path):
    result = GoldenARunner().run(tmp_path)

    expected = {
        "SH01": ArtifactCurrencyStatus.CURRENT.value,
        "SH02": ArtifactCurrencyStatus.STALE.value,
        "SH03": ArtifactCurrencyStatus.STALE.value,
        "SH04": ArtifactCurrencyStatus.CURRENT.value,
        "FINAL-GOLDEN-A": ArtifactCurrencyStatus.STALE.value,
    }
    assert result.invalidation == expected


def test_evidence_files_capture_cost_provenance_lineage_and_restart(tmp_path):
    result = GoldenARunner().run(tmp_path)

    evidence = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert evidence["external_provider_cost"] == "0"
    assert set(evidence["methods"]) == {"REUSE", "DETERMINISTIC", "COMPOSITE"}
    assert evidence["restart_verified"] is True
    assert evidence["final"]["sha256"] == result.final_sha256
    assert evidence["invalidation"]["SH02"] == "STALE"
    assert evidence["invalidation"]["SH03"] == "STALE"

    for record in evidence["provenance"]:
        assert record["content_fingerprint"]
        assert record["execution_fingerprint"]
        assert record["tool"]
        assert record["tool_version"]
        assert record["output_sha256"]
        assert record["external_provider_cost"] == "0"
