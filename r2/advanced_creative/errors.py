"""M8 domain errors; each carries the stable API error key it maps to (plan A3 fixed API surface)."""

from __future__ import annotations


class M8Error(RuntimeError):
    """Base of every M8 domain failure."""

    code = "m8_error"


class ExplorationNotFoundError(M8Error):
    """An unknown or foreign identity; the two are indistinguishable to callers."""

    code = "m8_exploration_not_found"


class CommandConflictError(M8Error):
    """A command id already used in this scope with a different semantic digest."""

    code = "m8_command_conflict"


class CandidateConflictError(M8Error):
    """The candidate head or its predecessor no longer matches the caller's expectation."""

    code = "m8_candidate_conflict"


class PromotionBindingStaleError(M8Error):
    """A preview or authorization binding is stale, expired or no longer matches current state."""

    code = "m8_promotion_binding_stale"


class PromotionTargetUnavailableError(M8Error):
    """The promotion target, or the authority seam behind it, is unavailable."""

    code = "m8_promotion_target_unavailable"


class ObservationNotFoundError(M8Error):
    """An unknown or foreign learning observation; the two are indistinguishable to callers."""

    code = "m8_observation_not_found"


class ObservationConflictError(M8Error):
    """The observation's identity or correction chain already holds different content."""

    code = "m8_observation_conflict"


class RecommendationNotFoundError(M8Error):
    """An unknown or foreign recommendation; the two are indistinguishable to callers."""

    code = "m8_recommendation_not_found"


class RecommendationConflictError(M8Error):
    """The recommendation id, proposal or decision conflicts with what is already recorded."""

    code = "m8_recommendation_conflict"


class RecommendationStaleError(M8Error):
    """The recommendation expired, changed, or its evidence is no longer current."""

    code = "m8_recommendation_stale"


class FormatNotFoundError(M8Error):
    """An unknown or foreign format profile, overlay set or plan."""

    code = "m8_format_not_found"


class FormatConflictError(M8Error):
    """The format ref or report id already holds different content."""

    code = "m8_format_conflict"


class FormatRenderIncompleteError(M8Error):
    """The render was accepted but its success could not be recorded; resend the same command."""

    code = "m8_format_render_incomplete"


class FormatMediaMissingError(M8Error):
    """A media file a format operation needs is no longer on disk."""

    code = "m8_format_media_missing"


__all__ = [
    "CandidateConflictError",
    "CommandConflictError",
    "ExplorationNotFoundError",
    "FormatConflictError",
    "FormatMediaMissingError",
    "FormatNotFoundError",
    "FormatRenderIncompleteError",
    "M8Error",
    "ObservationConflictError",
    "ObservationNotFoundError",
    "PromotionBindingStaleError",
    "PromotionTargetUnavailableError",
    "RecommendationConflictError",
    "RecommendationNotFoundError",
    "RecommendationStaleError",
]
