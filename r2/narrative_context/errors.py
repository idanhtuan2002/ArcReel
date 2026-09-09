from __future__ import annotations


class NarrativeContextError(Exception):
    """Base class for the NarrativeContextCompiler error taxonomy."""


class NarrativeContextInputError(NarrativeContextError):
    """Inconsistent exact versions, mode, POV, story time, or retrieval snapshot."""


class NarrativeSourceMetadataError(NarrativeContextError):
    """Mandatory source metadata is missing, contradictory, or cannot prove visibility."""


class NarrativeContextValidationError(NarrativeContextError):
    """A hard Canon or SceneContract constraint blocks compilation."""

    def __init__(self, detail: object) -> None:
        self.detail = detail
        super().__init__(str(detail))


class NarrativeContextBudgetError(NarrativeContextError):
    """Mandatory context cannot fit the token budget; no partial pack is returned."""
