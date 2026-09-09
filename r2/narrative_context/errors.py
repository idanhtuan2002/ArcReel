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


# Stable finding identifiers carried inside a NarrativeContextValidationError for the
# scene-side omniscient AUTHOR_DRAFT gate. A no-POV AUTHOR_DRAFT request that fails the
# SceneContract half raises with SCENE_OMNISCIENT_AUTHORING_FORBIDDEN; one that passes it
# still terminates with AUTHOR_DRAFT_POLICY_CAPABILITY_UNAVAILABLE until the typed
# CreativePolicy authority exists. No policy prose can enable omniscient authoring.
SCENE_OMNISCIENT_AUTHORING_FORBIDDEN = "SCENE_OMNISCIENT_AUTHORING_FORBIDDEN"
AUTHOR_DRAFT_POLICY_CAPABILITY_UNAVAILABLE = "AUTHOR_DRAFT_POLICY_CAPABILITY_UNAVAILABLE"
