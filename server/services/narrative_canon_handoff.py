"""Authenticated facade connecting an admitted Narrative handoff to the existing M5A
Canon commit path (spec section 11.4).

``NarrativeAcceptanceService.admit_canon_handoff`` (Task 28, ``r2/narrative_lifecycle/
acceptance.py``) produces a durable ``NarrativeHandoffAdmission`` receipt but never
writes Canon. This module is the thin production wrapper that reloads the exact
durable delta and approval a committed admission bound and calls the existing
``CanonTransactionService.commit()`` with that exact tuple — never a caller-held,
recomputed, or freshly issued one. It creates no second Canon approval authority and no
second Canon write path; every M5A exception (``CanonBaseVersionConflict``,
``CanonApprovalError``, ``CanonValidationError``, ...) propagates unchanged.

Reloading from the admission id plus its authenticated exact scope — not from an
in-memory ``AdmittedNarrativeHandoff`` handed back at admission time — is what makes
the initial call and every retry after a lost response or a process restart resolve to
the same tuple without exposing a cross-tenant id-only capability.
"""

from __future__ import annotations

from datetime import datetime

from r2.contracts import CanonCommitApproval, CanonCommitResult, CanonDelta
from r2.contracts.narrative_lifecycle import NarrativeWorkScope
from r2.narrative.canon_transaction import CanonTransactionService
from r2.narrative_lifecycle.errors import (
    NarrativeDecisionAuthorizationError,
    NarrativeEvidenceIntegrityError,
    NarrativeEvidenceNotFoundError,
)
from r2.narrative_lifecycle.ports import (
    NarrativeLifecycleRepositoryPort,
    NarrativeLifecycleUnitOfWorkFactory,
    NarrativeShowrunnerAuthorityPort,
)


class NarrativeCanonHandoffFacade:
    """Calls M5A on behalf of one already-admitted Narrative handoff.

    Never admits a handoff itself — ``admit_canon_handoff`` is
    ``NarrativeAcceptanceService``'s job — and never constructs its own
    ``CanonCommitApproval``: it only reloads the exact one an admission already bound.
    """

    def __init__(
        self,
        narrative_uow_factory: NarrativeLifecycleUnitOfWorkFactory,
        canon: CanonTransactionService,
        authority: NarrativeShowrunnerAuthorityPort,
    ) -> None:
        self._uow_factory = narrative_uow_factory
        self._canon = canon
        self._authority = authority

    async def commit_from_admission(
        self,
        *,
        admission_id: str,
        scope: NarrativeWorkScope,
        authenticated_principal: str,
        now: datetime,
    ) -> CanonCommitResult:
        """Reload the exact durable delta and approval bound by ``admission_id`` and call
        M5A with them. Safe to call repeatedly for the same admission: M5A's own exact
        retry (keyed on the delta's identity and payload) governs whether this mints a
        new Canon version or replays the one it already committed.
        """
        authentication = await self._authority.authenticate_scoped_showrunner(
            authenticated_principal, admission_id, scope
        )
        if (
            authentication.decision_id != admission_id
            or authentication.user_id != scope.user_id
            or authentication.project_name != scope.project_name
        ):
            raise NarrativeDecisionAuthorizationError(
                "the authority port's authentication is not bound to this exact admission and scope"
            )
        delta, approval = await self._reload_admitted_tuple(admission_id, scope)
        return await self._canon.commit(
            delta=delta,
            approval=approval,
            project_name=scope.project_name,
            user_id=scope.user_id,
            now=now,
        )

    async def _reload_admitted_tuple(
        self, admission_id: str, scope: NarrativeWorkScope
    ) -> tuple[CanonDelta, CanonCommitApproval]:
        async with self._uow_factory() as uow:
            repo: NarrativeLifecycleRepositoryPort = uow.repository
            admission = await repo.get_exact_handoff_admission(
                admission_id=admission_id,
                project_name=scope.project_name,
                user_id=scope.user_id,
            )
            if admission is None:
                raise NarrativeEvidenceNotFoundError(f"handoff admission {admission_id!r} does not resolve")
            evidence = await repo.get_exact_compiled_canon_delta(
                compilation_result_id=admission.compilation_result_id,
                project_name=scope.project_name,
                user_id=scope.user_id,
            )
            if evidence is None or evidence.canon_delta_payload_hash != admission.canon_delta_payload_hash:
                raise NarrativeEvidenceIntegrityError(
                    f"the delta admitted by {admission_id!r} no longer resolves to its exact persisted payload"
                )
            delta = evidence.canon_delta.model_copy(deep=True)
            approval = admission.canon_commit_approval.model_copy(deep=True)
            return delta, approval


__all__ = ["NarrativeCanonHandoffFacade"]
