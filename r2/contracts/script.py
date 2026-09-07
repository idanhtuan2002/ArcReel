from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from .common import NonEmptyStr, R2ContractModel
from .content_basis import ContentBasis
from .enums import ContentBasisType, CreativeApprovalStatus


class ScriptSection(R2ContractModel):
    id: NonEmptyStr
    text: NonEmptyStr
    claim_refs: list[NonEmptyStr]
    target_duration_seconds: Annotated[float, Field(gt=0)] | None = None


class ScriptArtifact(R2ContractModel):
    id: NonEmptyStr
    version: Annotated[int, Field(ge=1)]
    content_basis: ContentBasis
    sections: list[ScriptSection]
    participants: list[NonEmptyStr]
    timing_intent: NonEmptyStr
    creative_constraints: list[NonEmptyStr]
    approval_status: CreativeApprovalStatus

    @model_validator(mode="after")
    def _factual_claim_refs_are_declared(self) -> ScriptArtifact:
        if self.content_basis.basis_type is not ContentBasisType.FACTUAL:
            raise ValueError("ScriptArtifact in M3 requires FACTUAL ContentBasis")
        declared = set(self.content_basis.refs)
        for section in self.sections:
            for ref in section.claim_refs:
                if ref not in declared and f"claim:{ref}" not in declared:
                    raise ValueError(f"section claim ref {ref!r} is absent from ContentBasis")
        return self
