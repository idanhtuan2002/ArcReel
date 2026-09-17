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


class AdaptationPolicyPackIntegrityError(AdaptationError):
    """An immutable policy-pack manifest is structurally invalid (Task 8): malformed
    JSON, an unrecognized disposition/applicability value, a duplicate rule ID, or a
    rule whose declared applicability names a different profile than the pack it lives
    in. Never raised for a digest mismatch alone — that is
    ``AdaptationPolicyDigestMismatchError``, checked only after structural validation
    passes."""


class AdaptationWaiverNotApplicableError(AdaptationError):
    """A waiver decision does not apply (Task 11): it names a finding whose
    disposition is ``INTEGRITY_BLOCK`` (never waivable), a finding id/rule version
    the referenced report does not actually contain, or a report whose own
    ``artifact_hash``/``profile_ref`` no longer matches the exact artifact/profile the
    waiver command names — the "semantic change launders an old waiver" case. Also
    raised (Task 12) when a screenplay admission command names a waiver decision that
    does not resolve, is not itself a ``WAIVE`` decision, is not the currently
    effective decision for its own head, or does not target the exact admitted
    proposal's content/profile."""


class AdaptationBlockingFindingUnresolvedError(AdaptationError):
    """A screenplay admission's dependency reports carry a blocking finding that
    admission cannot proceed past (Task 12): any ``INTEGRITY_BLOCK`` finding (never
    waivable, regardless of ``waiver_refs``), or a ``PROFILE_BLOCK`` finding with no
    currently effective waiver covering its exact finding id."""


__all__ = [
    "AdaptationAuthorityDeniedError",
    "AdaptationAuthorityIntegrityError",
    "AdaptationBlockingFindingUnresolvedError",
    "AdaptationError",
    "AdaptationIdentityConflictError",
    "AdaptationNotFoundError",
    "AdaptationPolicyDigestMismatchError",
    "AdaptationPolicyPackIntegrityError",
    "AdaptationProfileMismatchError",
    "AdaptationStaleDependencyError",
    "AdaptationStaleHeadError",
    "AdaptationWaiverNotApplicableError",
]
