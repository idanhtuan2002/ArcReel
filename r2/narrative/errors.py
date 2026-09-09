from __future__ import annotations


class CanonError(Exception):
    """Base class for the Canon authority error taxonomy."""


class CanonNotFoundError(CanonError):
    """A scoped Canon identifier does not resolve inside its ``(user_id, project_name)`` scope."""


class CanonIdentityConflictError(CanonError):
    """A Canon identity (branch or delta) was reused with a conflicting definition."""


class CanonBaseVersionConflict(CanonError):
    """A delta's semantic base does not match the branch's current base."""

    def __init__(self, *, expected: str | None, current: str | None) -> None:
        self.expected = expected
        self.current = current
        super().__init__(f"expected Canon base {expected!r}; current base is {current!r}")


class CanonApprovalError(CanonError):
    """A commit approval is missing, malformed, or already bound to another delta identity."""


class CanonValidationError(CanonError):
    """A Canon candidate failed structural validation or is a semantic no-op."""

    def __init__(self, detail: object) -> None:
        self.detail = detail
        super().__init__(str(detail))


class CanonIntegrityError(CanonError):
    """Persisted Canon authority state violates an invariant or names an unsupported selector."""


class CanonOperationError(CanonError):
    """A single delta operation cannot be applied to the ordered base state."""


class NarrativeSchemaVersionError(CanonError):
    """An unsupported Canon content schema selector or an illegal schema transition."""


class EpistemicIdentityError(CanonError):
    """A proposition or KnowledgeState identity was reused with conflicting content."""


class EpistemicIntegrityError(CanonError):
    """Resolved Canon holds more than one active KnowledgeState for a subject/proposition."""


class EpistemicValidationError(CanonError):
    """An invalid epistemic interval, evidence link, or knowledge-state transition."""


class NarrativeError(Exception):
    """Base class for the M5C NarrativePlan schema / relationship / thread error taxonomy.

    Distinct from ``CanonError``: these errors concern authorial-plan schema versioning and
    the v2 relationship / thread semantics, not the Canon authority write path.
    """


class NarrativePlanSchemaVersionError(NarrativeError):
    """An unknown, below-minimum, or illegal SceneContract / NarrativePlan v1/v2 schema transition."""


class NarrativeRelationshipIntegrityError(NarrativeError):
    """A relationship reference or profile is malformed, or exact active relationship state is ambiguous."""
