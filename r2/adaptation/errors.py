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
    branch id, never a new version of an existing one. Also raised (Task 7) when a
    decision command's ``profile_ref.profile_id`` disagrees with its branch's bound
    profile."""


class AdaptationPolicyDigestMismatchError(AdaptationError):
    """A decision command's ``profile_ref`` names the branch's correct ``profile_id``
    but a stale or wrong ``profile_version``/``policy_pack_digest`` (Task 7)."""


class AdaptationAuthorityDeniedError(AdaptationError):
    """The authenticated principal does not hold the Human Showrunner grant this
    decision action requires (Task 7). Raised by a concrete
    ``AdaptationShowrunnerAuthorityPort`` implementation, never fabricated by the
    kernel or service."""


class AdaptationAuthorityIntegrityError(AdaptationError):
    """The stored ``AdaptationHead`` projection disagrees with the pure fold of its own
    complete decision chain (Task 7): a stale/ghost predecessor, a generation that does
    not equal the chain's length, an effective selection that does not name an
    accepting decision, or a selected artifact that does not match the accepting
    decision's own command. Never repaired automatically — the online guard that raises
    this stops the write; only a Human-directed correction fixes the stored row."""


__all__ = [
    "AdaptationAuthorityDeniedError",
    "AdaptationAuthorityIntegrityError",
    "AdaptationError",
    "AdaptationIdentityConflictError",
    "AdaptationNotFoundError",
    "AdaptationPolicyDigestMismatchError",
    "AdaptationProfileMismatchError",
    "AdaptationStaleDependencyError",
    "AdaptationStaleHeadError",
]
