from datetime import datetime
import pytest
from pydantic import ValidationError
from r2.contracts import Claim, ClaimLedger, ClaimStatus, EvidenceRecord, ResearchPack, SourceRecord


def provenance():
    return {"fixture": "golden-a"}


def test_verified_claim_requires_evidence():
    with pytest.raises(ValidationError):
        Claim(id="CLAIM-001", version=1, statement="x", evidence_refs=[], confidence=1.0,
              status=ClaimStatus.VERIFIED, provenance=provenance())


def test_claim_confidence_is_bounded():
    with pytest.raises(ValidationError):
        Claim(id="CLAIM-001", version=1, statement="x", evidence_refs=["E1"], confidence=1.1,
              status=ClaimStatus.PROPOSED, provenance=provenance())


def test_claim_ledger_rejects_duplicate_claim_ids():
    claim = Claim(id="CLAIM-001", version=1, statement="x", evidence_refs=["E1"], confidence=1.0,
                  status=ClaimStatus.VERIFIED, provenance=provenance())
    with pytest.raises(ValidationError):
        ClaimLedger(id="LEDGER-1", version=1, research_pack_ref="RP-1", claims=[claim, claim.model_copy()])


def test_research_pack_deduplicates_refs_deterministically():
    pack = ResearchPack(id="RP-1", version=1, topic="Git staging", scope="Golden A",
                        source_refs=["SRC-2", "SRC-1", "SRC-2"], evidence_refs=["E2", "E1", "E2"],
                        synthesis="Frozen factual snapshot.", uncertainties=[], open_questions=[], provenance=provenance())
    assert pack.source_refs == ["SRC-1", "SRC-2"]
    assert pack.evidence_refs == ["E1", "E2"]


def test_source_and_evidence_require_aware_timestamps():
    naive = datetime(2026, 9, 6, 12, 0, 0)
    with pytest.raises(ValidationError):
        SourceRecord(id="SRC-1", source_type="OFFICIAL_DOC", origin="https://git-scm.com/docs/git-add",
                     captured_at=naive, source_fingerprint="a" * 64, provenance=provenance())
    with pytest.raises(ValidationError):
        EvidenceRecord(id="E1", source_ref="SRC-1", locator="snapshot:git-add",
                       excerpt_or_structured_fact="git add updates the index", evidence_type="TEXT",
                       captured_at=naive, provenance=provenance())
