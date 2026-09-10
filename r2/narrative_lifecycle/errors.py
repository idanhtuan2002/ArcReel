"""M5C Narrative-lifecycle failure taxonomy (design Section 13).

Every error is a ``NarrativeError`` subclass, so a caller catching ``NarrativeError``
catches the whole M5 relationship / thread / lifecycle surface. Validation and identity
errors write nothing; a decision failure leaves both history and head unchanged; a
compilation failure returns no partial ``CanonDelta``; a handoff failure creates no
admission receipt and no Canon write.
"""

from __future__ import annotations

from r2.narrative.errors import NarrativeError


class NarrativeLifecycleError(NarrativeError):
    """Base class for the M5C evidence / decision / compilation / handoff taxonomy."""


class NarrativeEvidenceNotFoundError(NarrativeLifecycleError):
    """Exact evidence is absent, or resolves outside its ``(user_id, project_name)`` scope."""


class NarrativeEvidenceIdentityConflictError(NarrativeLifecycleError):
    """An evidence identity was reused with a different full tuple."""


class NarrativeEvidenceIntegrityError(NarrativeLifecycleError):
    """A hash, lineage, attempt/result binding, or reference is corrupt or inconsistent."""


class NarrativeDecisionNotFoundError(NarrativeLifecycleError):
    """An exact decision is absent or resolves outside its scope."""


class NarrativeDecisionAuthorizationError(NarrativeLifecycleError):
    """The authenticated actor lacks the explicit project-scoped Human Showrunner grant,
    the original command authorization, or exact-retry authentication."""


class NarrativeDecisionIdentityConflictError(NarrativeLifecycleError):
    """A caller-supplied global decision/admission id collides with a different tuple.

    The public detail reveals no owning scope, family, subject, actor, or content.
    """


class NarrativeDecisionPredecessorConflict(NarrativeLifecycleError):
    """An expected latest or effective predecessor is stale."""


class NarrativeDecisionApplicabilityError(NarrativeLifecycleError):
    """Selected evidence or a selected decision is rejected, superseded, mismatched, or mutually invalid."""


class NarrativeAuthorityIntegrityError(NarrativeLifecycleError):
    """The authoritative decision chain and the mutable projection disagree or contain an invalid link."""


class NarrativeConflictCoverageError(NarrativeLifecycleError):
    """An overlap is unresolved, partially resolved, multiply resolved, or outside its lineage subject."""


class NarrativeConflictLineageConflict(NarrativeLifecycleError):
    """The canonical conflict subject already belongs to another opaque lineage."""


class NarrativeAttemptGenerationConflict(NarrativeLifecycleError):
    """A stale or duplicate attempt generation, or a mismatched completion for one generation."""


class CanonDeltaCompilationError(NarrativeLifecycleError):
    """An unsupported or invalid exact compiler input. No partial delta is produced."""


class NarrativeHandoffConflict(NarrativeLifecycleError):
    """Compilation inputs are no longer currently effective at the admission instant."""


class NarrativeThreadPayoffApplicabilityError(NarrativeLifecycleError):
    """A thread-payoff proof is absent, stale, rejected, mismatched, or incompletely resolved."""
