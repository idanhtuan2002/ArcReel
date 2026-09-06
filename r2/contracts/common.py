from __future__ import annotations

import math
from typing import Annotated, Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class R2ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        frozen=False,
        use_enum_values=False,
    )


class ContractIdentity(R2ContractModel):
    id: NonEmptyStr
    schema_version: NonEmptyStr
    version: int = Field(ge=1)


def ensure_json_value(value: Any) -> JSONValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON-compatible floats must be finite")
        return value
    if isinstance(value, list):
        return [ensure_json_value(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON-compatible mappings require string keys")
            result[key] = ensure_json_value(item)
        return result
    raise ValueError(f"value is not JSON-compatible: {type(value).__name__}")
