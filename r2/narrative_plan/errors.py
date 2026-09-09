from __future__ import annotations


class NarrativePlanError(Exception):
    """Base class for the Authorial Intent (NarrativePlan) error taxonomy."""


class NarrativePlanNotFoundError(NarrativePlanError):
    """Unknown and cross-scope plan/version identifiers, deliberately collapsed."""


class NarrativePlanIdentityConflictError(NarrativePlanError):
    """A plan revision or SceneContract ID/version was reused with a different identity."""


class NarrativePlanVersionConflict(NarrativePlanError):
    """The expected plan head is stale; M5B never auto-rebases approved authorial intent."""

    def __init__(self, *, expected: int | None, current: int | None) -> None:
        self.expected = expected
        self.current = current
        super().__init__(f"expected plan head {expected!r}; current head is {current!r}")


class NarrativePlanApprovalError(NarrativePlanError):
    """An incomplete or mismatched approval receipt."""


class NarrativePlanValidationError(NarrativePlanError):
    """A plan revision failed pure hierarchy / SceneContract / Canon-basis validation."""

    def __init__(self, detail: object) -> None:
        self.detail = detail
        super().__init__(str(detail))
