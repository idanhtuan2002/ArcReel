from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from r2.contracts import (
    ClaimLedger,
    ClaimStatus,
    ContentBasisType,
    EvidenceRecord,
    ResearchPack,
    ScriptArtifact,
    SourceRecord,
)


@dataclass(frozen=True)
class GoldenAFactualBundle:
    sources: tuple[SourceRecord, ...]
    evidence: tuple[EvidenceRecord, ...]
    research_pack: ResearchPack
    claim_ledger: ClaimLedger
    script: ScriptArtifact


def _default_fixture() -> Path:
    return Path(__file__).with_name("fixtures") / "golden_a_git.json"


def load_golden_a_factual_bundle(fixture_path: Path | None = None) -> GoldenAFactualBundle:
    data = json.loads((fixture_path or _default_fixture()).read_text(encoding="utf-8"))
    sources = tuple(SourceRecord.model_validate(x) for x in data["sources"])
    evidence = tuple(EvidenceRecord.model_validate(x) for x in data["evidence"])
    research_pack = ResearchPack.model_validate(data["research_pack"])
    claim_ledger = ClaimLedger.model_validate(data["claim_ledger"])
    script = ScriptArtifact.model_validate(data["script"])
    source_ids = {x.id for x in sources}
    evidence_ids = {x.id for x in evidence}
    claims = {x.id: x for x in claim_ledger.claims}
    if not all(x.source_ref in source_ids for x in evidence):
        raise ValueError("unresolved evidence source")
    if not set(research_pack.source_refs) <= source_ids:
        raise ValueError("unresolved research sources")
    if not set(research_pack.evidence_refs) <= evidence_ids:
        raise ValueError("unresolved research evidence")
    for claim in claims.values():
        if claim.status is not ClaimStatus.VERIFIED:
            raise ValueError("fixture claims must be VERIFIED")
        if not set(claim.evidence_refs) <= evidence_ids:
            raise ValueError("unresolved claim evidence")
    for section in script.sections:
        if not set(section.claim_refs) <= set(claims):
            raise ValueError("unresolved script claim")
    if script.content_basis.basis_type is not ContentBasisType.FACTUAL:
        raise ValueError("script basis must be FACTUAL")
    return GoldenAFactualBundle(
        sources=sources, evidence=evidence, research_pack=research_pack, claim_ledger=claim_ledger, script=script
    )
