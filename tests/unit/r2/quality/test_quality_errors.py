"""Only registered error identities cross the M10 outward boundary."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import cast

import pytest

from r2.quality import errors

NAMES = {
    "M10_DESIGN_NOT_ACCEPTED": "DesignNotAcceptedError",
    "M10_PREREQUISITE_NOT_ACCEPTED": "PrerequisiteNotAcceptedError",
    "POST_M8_BASE_SEAM_CHANGED": "PostM8BaseSeamChangedError",
    "M10_SCHEMA_CHANGE_REQUIRED": "SchemaChangeRequiredError",
    "M10_PROFILE_STALE": "ProfileStaleError",
    "M10_PROFILE_PUBLICATION_UNAUTHORIZED": "ProfilePublicationUnauthorizedError",
    "M10_SUBJECT_STALE": "SubjectStaleError",
    "M10_REQUIRED_EVIDENCE_MISSING": "RequiredEvidenceMissingError",
    "M10_REFERENCE_INVALID": "ReferenceInvalidError",
    "M10_PROBE_FAILED": "ProbeFailedError",
    "M10_OPERATIONAL_ENVELOPE_EXCEEDED": "OperationalEnvelopeExceededError",
    "M10_DISPOSITION_UNAUTHORIZED": "DispositionUnauthorizedError",
    "M10_DISPOSITION_STALE": "DispositionStaleError",
    "M10_WAIVER_FORBIDDEN": "WaiverForbiddenError",
    "M10_PACKAGING_TARGET_FORBIDDEN": "PackagingTargetForbiddenError",
    "M10_COMMAND_REPLAY_CONFLICT": "CommandReplayConflictError",
    "M10_STALE_HEAD": "StaleHeadError",
    "M10_EXPORT_INTEGRITY_FAILED": "ExportIntegrityFailedError",
    "M10_NETWORK_SIDE_EFFECT_FORBIDDEN": "NetworkSideEffectForbiddenError",
    "M10_DONOR_PARITY_INCOMPLETE": "DonorParityIncompleteError",
}
FALLBACK = "M10_REQUIRED_EVIDENCE_MISSING"


@pytest.mark.parametrize(("code", "name"), NAMES.items())
def test_registered_errors_discard_details_and_keep_exact_identity(code: str, name: str) -> None:
    exc = errors.error_for_code(code)
    assert type(exc).__name__ == name
    assert isinstance(exc, errors.M10Error)
    assert errors.ERROR_TYPES[code] is type(exc)
    assert errors.ERROR_CODES[type(exc)] == code
    supplied = type(exc)("CANARY_SECRET", {"prompt": "CANARY_SECRET"}, token="CANARY_SECRET")
    supplied.__cause__ = RuntimeError("CANARY_SECRET")
    supplied.__context__ = RuntimeError("CANARY_SECRET")
    assert supplied.args == (code,)
    assert str(supplied) == code
    assert "CANARY_SECRET" not in repr(supplied)
    assert errors.error_payload(supplied) == {"code": code, "message": code}


def test_registry_is_closed_immutable_and_profile_publication_is_distinct() -> None:
    assert set(errors.ERROR_TYPES) == set(NAMES)
    with pytest.raises(TypeError):
        cast(MutableMapping[str, type[errors.M10Error]], errors.ERROR_TYPES)["fake"] = errors.M10Error
    with pytest.raises(TypeError):
        cast(MutableMapping[type[BaseException], str], errors.ERROR_CODES)[errors.M10Error] = "fake"
    assert errors.ProfilePublicationUnauthorizedError is not errors.DispositionUnauthorizedError


@pytest.mark.parametrize("code", [None, [], {}, 1, "", "M10_PROFILE_STALE ", "CANARY_SECRET"])
def test_unknown_factory_input_is_sanitized(code: object) -> None:
    assert type(errors.error_for_code(code)) is errors.RequiredEvidenceMissingError


def test_forged_codes_unknown_subclasses_and_raw_errors_cannot_masquerade() -> None:
    class Forged(RuntimeError):
        @property
        def code(self):
            raise AssertionError("must not access arbitrary code")

    class Unregistered(errors.ProbeFailedError):
        @property
        def code(self) -> str:
            return "M10_PROFILE_STALE"

    for exc in [Forged("CANARY_SECRET"), Unregistered("CANARY_SECRET"), errors.M10Error("CANARY_SECRET")]:
        assert errors.error_payload(exc) == {"code": FALLBACK, "message": FALLBACK}
    direct = errors.M10Error("CANARY_SECRET")
    assert direct.args == (FALLBACK,)
    assert str(direct) == FALLBACK


@pytest.mark.parametrize("hostile_kind", ["alias", "raise"])
def test_error_identity_never_executes_metaclass_hash_or_equality(hostile_kind: str) -> None:
    class HostileMeta(type):
        def __hash__(cls) -> int:
            if hostile_kind == "raise":
                raise AssertionError("untrusted metaclass hash executed")
            return hash(errors.ProbeFailedError)

        def __eq__(cls, other: object) -> bool:
            if hostile_kind == "raise":
                raise AssertionError("untrusted metaclass equality executed")
            return other is errors.ProbeFailedError

    class ForeignError(Exception, metaclass=HostileMeta):
        pass

    class LocalError(errors.M10Error, metaclass=HostileMeta):
        pass

    assert errors.error_payload(ForeignError("CANARY_SECRET")) == {"code": FALLBACK, "message": FALLBACK}
    exc = LocalError("CANARY_SECRET")
    assert exc.args == (FALLBACK,)
    assert exc.code == FALLBACK
    assert str(exc) == FALLBACK
    assert repr(exc) == f"M10Error({FALLBACK!r})"
    assert errors.error_payload(exc) == {"code": FALLBACK, "message": FALLBACK}
