"""Closed M10 error identities and a payload boundary that discards caller details."""

from __future__ import annotations

from types import MappingProxyType

_FALLBACK = "M10_REQUIRED_EVIDENCE_MISSING"


class M10Error(Exception):
    """Only exact registered classes identify outward failures."""

    def __init__(self, *details: object, **context: object) -> None:
        Exception.__init__(self, ERROR_CODES.get(type(self), _FALLBACK))

    @property
    def code(self) -> str:
        return ERROR_CODES.get(type(self), _FALLBACK)

    def __str__(self) -> str:
        return ERROR_CODES.get(type(self), _FALLBACK)

    def __repr__(self) -> str:
        return f"M10Error({ERROR_CODES.get(type(self), _FALLBACK)!r})"


class DesignNotAcceptedError(M10Error):
    """The bounded design has no accepted authority."""


class PrerequisiteNotAcceptedError(M10Error):
    """A required predecessor is unavailable or unaccepted."""


class PostM8BaseSeamChangedError(M10Error):
    """A protected predecessor seam changed."""


class SchemaChangeRequiredError(M10Error):
    """The operation requires a separately accepted schema change."""


class ProfileStaleError(M10Error):
    """The selected profile is stale."""


class ProfilePublicationUnauthorizedError(M10Error):
    """Profile publication lacks qualified authorization."""


class SubjectStaleError(M10Error):
    """The assessed subject is stale."""


class RequiredEvidenceMissingError(M10Error):
    """Required evidence is unavailable."""


class ReferenceInvalidError(M10Error):
    """An evidence reference is invalid."""


class ProbeFailedError(M10Error):
    """A qualified probe failed."""


class OperationalEnvelopeExceededError(M10Error):
    """An operation exceeded its admitted resource envelope."""


class DispositionUnauthorizedError(M10Error):
    """Disposition lacks qualified authorization."""


class DispositionStaleError(M10Error):
    """The selected disposition is stale."""


class WaiverForbiddenError(M10Error):
    """The requested waiver is forbidden."""


class PackagingTargetForbiddenError(M10Error):
    """The requested packaging target is forbidden."""


class CommandReplayConflictError(M10Error):
    """A command replay conflicts with its durable identity."""


class StaleHeadError(M10Error):
    """The expected head has changed."""


class ExportIntegrityFailedError(M10Error):
    """Export integrity could not be verified."""


class NetworkSideEffectForbiddenError(M10Error):
    """The operation attempted a forbidden network side effect."""


class DonorParityIncompleteError(M10Error):
    """Required integrated donor parity is incomplete."""


ERROR_TYPES: MappingProxyType[str, type[M10Error]] = MappingProxyType(
    {
        "M10_DESIGN_NOT_ACCEPTED": DesignNotAcceptedError,
        "M10_PREREQUISITE_NOT_ACCEPTED": PrerequisiteNotAcceptedError,
        "POST_M8_BASE_SEAM_CHANGED": PostM8BaseSeamChangedError,
        "M10_SCHEMA_CHANGE_REQUIRED": SchemaChangeRequiredError,
        "M10_PROFILE_STALE": ProfileStaleError,
        "M10_PROFILE_PUBLICATION_UNAUTHORIZED": ProfilePublicationUnauthorizedError,
        "M10_SUBJECT_STALE": SubjectStaleError,
        "M10_REQUIRED_EVIDENCE_MISSING": RequiredEvidenceMissingError,
        "M10_REFERENCE_INVALID": ReferenceInvalidError,
        "M10_PROBE_FAILED": ProbeFailedError,
        "M10_OPERATIONAL_ENVELOPE_EXCEEDED": OperationalEnvelopeExceededError,
        "M10_DISPOSITION_UNAUTHORIZED": DispositionUnauthorizedError,
        "M10_DISPOSITION_STALE": DispositionStaleError,
        "M10_WAIVER_FORBIDDEN": WaiverForbiddenError,
        "M10_PACKAGING_TARGET_FORBIDDEN": PackagingTargetForbiddenError,
        "M10_COMMAND_REPLAY_CONFLICT": CommandReplayConflictError,
        "M10_STALE_HEAD": StaleHeadError,
        "M10_EXPORT_INTEGRITY_FAILED": ExportIntegrityFailedError,
        "M10_NETWORK_SIDE_EFFECT_FORBIDDEN": NetworkSideEffectForbiddenError,
        "M10_DONOR_PARITY_INCOMPLETE": DonorParityIncompleteError,
    }
)
ERROR_CODES: MappingProxyType[type[BaseException], str] = MappingProxyType(
    {
        DesignNotAcceptedError: "M10_DESIGN_NOT_ACCEPTED",
        PrerequisiteNotAcceptedError: "M10_PREREQUISITE_NOT_ACCEPTED",
        PostM8BaseSeamChangedError: "POST_M8_BASE_SEAM_CHANGED",
        SchemaChangeRequiredError: "M10_SCHEMA_CHANGE_REQUIRED",
        ProfileStaleError: "M10_PROFILE_STALE",
        ProfilePublicationUnauthorizedError: "M10_PROFILE_PUBLICATION_UNAUTHORIZED",
        SubjectStaleError: "M10_SUBJECT_STALE",
        RequiredEvidenceMissingError: "M10_REQUIRED_EVIDENCE_MISSING",
        ReferenceInvalidError: "M10_REFERENCE_INVALID",
        ProbeFailedError: "M10_PROBE_FAILED",
        OperationalEnvelopeExceededError: "M10_OPERATIONAL_ENVELOPE_EXCEEDED",
        DispositionUnauthorizedError: "M10_DISPOSITION_UNAUTHORIZED",
        DispositionStaleError: "M10_DISPOSITION_STALE",
        WaiverForbiddenError: "M10_WAIVER_FORBIDDEN",
        PackagingTargetForbiddenError: "M10_PACKAGING_TARGET_FORBIDDEN",
        CommandReplayConflictError: "M10_COMMAND_REPLAY_CONFLICT",
        StaleHeadError: "M10_STALE_HEAD",
        ExportIntegrityFailedError: "M10_EXPORT_INTEGRITY_FAILED",
        NetworkSideEffectForbiddenError: "M10_NETWORK_SIDE_EFFECT_FORBIDDEN",
        DonorParityIncompleteError: "M10_DONOR_PARITY_INCOMPLETE",
    }
)


def error_for_code(code: object) -> M10Error:
    """Return only registered failure classes; unknown inputs have a fixed fallback."""
    error_type = (
        ERROR_TYPES.get(code, RequiredEvidenceMissingError) if type(code) is str else RequiredEvidenceMissingError
    )
    return error_type()


def error_payload(exc: BaseException) -> dict[str, str]:
    """Never inspect an arbitrary exception's code, details, cause or traceback."""
    code = ERROR_CODES.get(type(exc), _FALLBACK)
    return {"code": code, "message": code}
