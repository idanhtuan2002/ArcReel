from __future__ import annotations

from pydantic import AwareDatetime, Field, field_validator

from r2.contracts import ContentBasis, NonEmptyStr, R2ContractModel


class R2ContractRef(R2ContractModel):
    contract_type: NonEmptyStr
    id: NonEmptyStr
    version: int = Field(ge=1)
    schema_version: NonEmptyStr


class DependencySnapshot(R2ContractModel):
    ref: NonEmptyStr
    version: NonEmptyStr
    fingerprint: NonEmptyStr


class ApprovedMasterMetadata(R2ContractModel):
    selected_candidate_id: NonEmptyStr
    host_version_ref: NonEmptyStr
    approval_record: NonEmptyStr
    selected_at: AwareDatetime
    selected_by: NonEmptyStr


class R2ArtifactMetadata(R2ContractModel):
    metadata_schema_version: NonEmptyStr
    contract_ref: R2ContractRef
    content_basis: ContentBasis
    direct_dependencies: list[DependencySnapshot] = Field(default_factory=list)
    content_fingerprint: NonEmptyStr
    approved_master: ApprovedMasterMetadata | None = None

    @field_validator("direct_dependencies")
    @classmethod
    def normalize_dependencies(
        cls,
        value: list[DependencySnapshot],
    ) -> list[DependencySnapshot]:
        by_ref: dict[str, DependencySnapshot] = {}
        for item in value:
            existing = by_ref.get(item.ref)
            if existing is not None and existing != item:
                raise ValueError(f"conflicting dependency snapshots for {item.ref}")
            by_ref[item.ref] = item
        return [by_ref[key] for key in sorted(by_ref)]
