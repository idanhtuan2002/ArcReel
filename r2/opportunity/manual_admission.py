"""Content-free bindings for independently authenticated manual material."""

from typing import Literal, Self

from pydantic import Field, model_validator

from r2.contracts.advanced_creative import Sha256Digest
from r2.contracts.opportunity import (
    CommandContext,
    EvidenceDataClassClock,
    M9ContractModel,
    Slug,
    SourceDataRule,
)


class SealExpectation(M9ContractModel):
    schema_version: Literal["m9.manual-material-seal.v1"]
    source_kind: Literal["manual-import"]
    source_contract_version: Literal["manual-import.v1"]
    verification_key_id: Slug
    context: CommandContext
    request_digest: Sha256Digest
    query_id: str
    query_revision: int = Field(ge=1, strict=True)
    query_digest: Sha256Digest
    attempt_id: str
    attempt_version: int = Field(ge=1, strict=True)
    publication_key: str
    claim_ref: str
    upload_version: int = Field(ge=1, strict=True)
    descriptor_digest: Sha256Digest
    payload_ref: str
    integrity_ref: str
    attestation_ref: str
    evidence_kind: Slug
    data_classes: tuple[Slug, ...] = Field(min_length=1)
    data_rules: tuple[SourceDataRule, ...] = Field(min_length=1)
    original_clocks: tuple[EvidenceDataClassClock, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_class_closure(self) -> Self:
        classes = set(self.data_classes)
        if len(self.data_rules) != len(classes) or {r.data_class for r in self.data_rules} != classes:
            raise ValueError("material rules must exactly cover the declared classes")
        if len(self.original_clocks) != len(classes) or {c.data_class for c in self.original_clocks} != classes:
            raise ValueError("original clocks must exactly cover the declared classes")
        return self
