from pydantic import AwareDatetime, Field, field_validator

from .common import NonEmptyStr, R2ContractModel
from .enums import ProvenanceActor


class Provenance(R2ContractModel):
    created_by: ProvenanceActor
    source_refs: list[NonEmptyStr] = Field(default_factory=list)
    tool_or_adapter: NonEmptyStr | None = None
    model: NonEmptyStr | None = None
    model_version: NonEmptyStr | None = None
    created_at: AwareDatetime
    operation_id: NonEmptyStr | None = None
    parent_revision_refs: list[NonEmptyStr] = Field(default_factory=list)

    @field_validator("source_refs", "parent_revision_refs")
    @classmethod
    def normalize_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))
