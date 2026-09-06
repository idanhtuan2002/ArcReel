import math

import pytest
from pydantic import ValidationError

from r2.contracts import (
    ArtifactCurrencyStatus,
    CandidateSelectionStatus,
    ContractIdentity,
    CreativeApprovalStatus,
    GenerationLifecycleStatus,
    RuntimeTaskStatus,
    ensure_json_value,
)


def test_contract_identity_requires_non_empty_id_and_positive_version():
    identity = ContractIdentity(id="SH042", schema_version="2.1", version=7)
    assert identity.id == "SH042"
    assert identity.version == 7
    assert identity.schema_version == "2.1"

    with pytest.raises(ValidationError):
        ContractIdentity(id="", schema_version="2.1", version=1)

    with pytest.raises(ValidationError):
        ContractIdentity(id="SH042", schema_version="", version=1)

    with pytest.raises(ValidationError):
        ContractIdentity(id="SH042", schema_version="2.1", version=0)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        ContractIdentity(
            id="SH042",
            schema_version="2.1",
            version=1,
            provider="seedance",
        )


def test_status_families_are_distinct_enum_types():
    assert CreativeApprovalStatus.APPROVED.value == "APPROVED"
    assert ArtifactCurrencyStatus.CURRENT.value == "CURRENT"
    assert RuntimeTaskStatus.RUNNING.value == "RUNNING"
    assert CandidateSelectionStatus.SELECTED.value == "SELECTED"
    assert GenerationLifecycleStatus.GENERATED.value == "GENERATED"

    assert CreativeApprovalStatus is not ArtifactCurrencyStatus
    assert CandidateSelectionStatus is not GenerationLifecycleStatus


def test_ensure_json_value_rejects_arbitrary_python_objects_and_non_finite_floats():
    assert ensure_json_value(
        {"nested": [1, "x", True, None, {"score": 0.5}]}
    ) == {"nested": [1, "x", True, None, {"score": 0.5}]}

    class NotJSON:
        pass

    with pytest.raises(ValueError, match="JSON-compatible"):
        ensure_json_value({"bad": NotJSON()})

    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="finite"):
            ensure_json_value({"bad": value})
