from pydantic import Field, field_validator

from .common import NonEmptyStr, R2ContractModel
from .enums import ContentBasisType


class ContentBasis(R2ContractModel):
    basis_type: ContentBasisType
    basis_version: NonEmptyStr
    refs: list[NonEmptyStr] = Field(min_length=1)

    @field_validator("refs")
    @classmethod
    def normalize_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))
