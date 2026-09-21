from pathlib import Path

import pytest

from r2.contracts import ClaimStatus, ContentBasisType
from r2.m3.factual_fixture import load_golden_a_factual_bundle

_H264_FIXTURE = Path(__file__).resolve().parents[4] / "r2" / "m3" / "fixtures" / "golden_a_h264.json"


def test_fixture_cross_references_are_complete():
    bundle = load_golden_a_factual_bundle()
    source_ids = {x.id for x in bundle.sources}
    evidence_ids = {x.id for x in bundle.evidence}
    claims = {x.id: x for x in bundle.claim_ledger.claims}
    assert len(claims) >= 3
    assert all(c.status is ClaimStatus.VERIFIED for c in claims.values())
    assert all(e.source_ref in source_ids for e in bundle.evidence)
    assert all(ref in evidence_ids for c in claims.values() for ref in c.evidence_refs)
    assert bundle.script.content_basis.basis_type is ContentBasisType.FACTUAL
    assert all(ref in claims for section in bundle.script.sections for ref in section.claim_refs)


def test_h264_fixture_cross_references_are_complete():
    bundle = load_golden_a_factual_bundle(_H264_FIXTURE)
    source_ids = {x.id for x in bundle.sources}
    evidence_ids = {x.id for x in bundle.evidence}
    claims = {x.id: x for x in bundle.claim_ledger.claims}
    assert len(claims) >= 2
    assert all(c.status is ClaimStatus.VERIFIED for c in claims.values())
    assert all(e.source_ref in source_ids for e in bundle.evidence)
    assert all(ref in evidence_ids for c in claims.values() for ref in c.evidence_refs)
    assert bundle.script.content_basis.basis_type is ContentBasisType.FACTUAL
    assert all(ref in claims for section in bundle.script.sections for ref in section.claim_refs)


def test_h264_fixture_total_duration_fits_the_golden_a_exit_gate():
    bundle = load_golden_a_factual_bundle(_H264_FIXTURE)
    total = sum(s.target_duration_seconds or 0.0 for s in bundle.script.sections)
    assert 60.0 <= total <= 90.0


@pytest.mark.parametrize("path", [None, _H264_FIXTURE])
def test_fixture_reload_is_deterministic(path):
    assert load_golden_a_factual_bundle(path) == load_golden_a_factual_bundle(path)
