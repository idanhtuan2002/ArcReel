from r2.contracts import ClaimStatus, ContentBasisType
from r2.m3.factual_fixture import load_golden_a_factual_bundle


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


def test_fixture_reload_is_deterministic():
    assert load_golden_a_factual_bundle() == load_golden_a_factual_bundle()
