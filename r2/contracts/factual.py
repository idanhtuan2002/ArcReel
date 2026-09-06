from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Annotated
from pydantic import Field, field_validator, model_validator
from .common import JSONValue, NonEmptyStr, R2ContractModel


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


def _sorted_unique(values: list[NonEmptyStr]) -> list[NonEmptyStr]:
    return sorted(set(values))


class ClaimStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    RETIRED = "RETIRED"


class SourceRecord(R2ContractModel):
    id: NonEmptyStr
    source_type: NonEmptyStr
    title: NonEmptyStr | None = None
    origin: NonEmptyStr
    captured_at: datetime
    source_fingerprint: NonEmptyStr
    provenance: dict[NonEmptyStr, JSONValue]
    _captured_at_aware = field_validator("captured_at")(_aware)


class EvidenceRecord(R2ContractModel):
    id: NonEmptyStr
    source_ref: NonEmptyStr
    locator: NonEmptyStr
    excerpt_or_structured_fact: JSONValue | None = None
    evidence_type: NonEmptyStr
    captured_at: datetime
    provenance: dict[NonEmptyStr, JSONValue]
    _captured_at_aware = field_validator("captured_at")(_aware)


class ResearchPack(R2ContractModel):
    id: NonEmptyStr
    version: Annotated[int, Field(ge=1)]
    topic: NonEmptyStr
    scope: NonEmptyStr
    source_refs: list[NonEmptyStr]
    evidence_refs: list[NonEmptyStr]
    synthesis: NonEmptyStr
    uncertainties: list[str]
    open_questions: list[str]
    provenance: dict[NonEmptyStr, JSONValue]
    _source_refs_sorted = field_validator("source_refs")(_sorted_unique)
    _evidence_refs_sorted = field_validator("evidence_refs")(_sorted_unique)


class Claim(R2ContractModel):
    id: NonEmptyStr
    version: Annotated[int, Field(ge=1)]
    statement: NonEmptyStr
    evidence_refs: list[NonEmptyStr]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    status: ClaimStatus
    provenance: dict[NonEmptyStr, JSONValue]
    _evidence_refs_sorted = field_validator("evidence_refs")(_sorted_unique)

    @model_validator(mode="after")
    def _verified_has_evidence(self) -> "Claim":
        if self.status is ClaimStatus.VERIFIED and not self.evidence_refs:
            raise ValueError("VERIFIED claim requires evidence")
        return self


class ClaimLedger(R2ContractModel):
    id: NonEmptyStr
    version: Annotated[int, Field(ge=1)]
    research_pack_ref: NonEmptyStr
    claims: list[Claim]

    @model_validator(mode="after")
    def _unique_claim_ids(self) -> "ClaimLedger":
        ids = [claim.id for claim in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("ClaimLedger claim ids must be unique")
        return self
