"""M6 adaptation evidence error taxonomy (plan Task 6).

Each class name mirrors one entry of the plan's fixed stable-error catalog
(``AdaptationNotFoundError`` <-> ``ADAPTATION_NOT_FOUND``), the same convention
``r2.narrative.errors.CanonError`` and ``r2.narrative_lifecycle.errors.NarrativeLifecycleError``
already use. A caller catching ``AdaptationError`` catches the whole M6 evidence /
authority / profile / screenplay surface. This file defines only what the append-only
``AdaptationEvidenceService`` (Task 6) raises; later tasks (7, 11, 12, 3) extend the
taxonomy with authority, waiver, screenplay-admission and ShotSpec errors.
"""

from __future__ import annotations


class AdaptationError(Exception):
    """Base class for the M6 adaptation evidence / authority / profile error taxonomy."""


class AdaptationNotFoundError(AdaptationError):
    """An exact adaptation artifact reference does not resolve inside its
    ``(user_id, project_name)`` scope. A foreign-scope id/version is indistinguishable
    from an absent one — the message never discloses which."""


class AdaptationIdentityConflictError(AdaptationError):
    """A branch/map/screenplay id was reused at the same version with a different tuple,
    including a concurrently committed duplicate observed only as a persistence
    constraint violation."""


class AdaptationStaleHeadError(AdaptationError):
    """A branch version transition is not a legal next version of its own lineage
    (``validate_adaptation_transition``): non-sequential version, changed root binding,
    or a second genesis under one branch id."""


class AdaptationStaleDependencyError(AdaptationError):
    """A declared parent reference does not match what is actually stored at that exact
    version: a screenplay's ``adaptation_map_ref`` content hash disagrees with the
    stored map, or its ``adaptation_branch_ref`` disagrees with the map's own branch
    binding."""


class AdaptationProfileMismatchError(AdaptationError):
    """A branch changed its bound profile mid-lineage; a profile change requires a new
    branch id, never a new version of an existing one."""


__all__ = [
    "AdaptationError",
    "AdaptationIdentityConflictError",
    "AdaptationNotFoundError",
    "AdaptationProfileMismatchError",
    "AdaptationStaleDependencyError",
    "AdaptationStaleHeadError",
]
