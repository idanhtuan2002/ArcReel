"""The internal per-command authority-kernel transaction body (spec §7.2).

Shared by all three decision families (``decide_revision`` / ``review_change_set`` /
``resolve_change_set_conflict``): canonical identity, exact-retry resolution, head
locking, OCC predecessor checks, append, commit. Not public API — only
``NarrativeAcceptanceService`` (Task 18) constructs and calls this.

**Isolation precondition (spec §7.2).** Every kernel transaction must run at
``READ COMMITTED``. The step-2/step-5 double ``get_decision_by_id`` lookup is correct
only under a fresh per-statement snapshot; the injected unit-of-work factory must not
open its transaction through any session/engine configuration that raises the
isolation level. Asserted in Task 21, not re-derived here.

The kernel — not its caller — calls ``NarrativeShowrunnerAuthorityPort`` itself: once a
fresh ``decision_id`` is confirmed genuinely new (steps 2 and 5 found nothing),
``authorize_initial_decision`` is called to obtain the one original
``NarrativeDecisionAuthorization``; once an already-stored ``decision_id`` is found,
``authenticate_exact_retry`` is called to obtain fresh, unpersisted
``NarrativeDecisionRetryAuthentication``. This keeps the public decision surface
(Task 18) free of any caller-supplied authorization object.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from r2.contracts.narrative_lifecycle import (
    ChangeSetReviewCommand,
    ChangeSetReviewHead,
    ConflictResolutionCommand,
    ConflictResolutionHead,
    NarrativeDecisionAuthorization,
    NarrativeDecisionCommand,
    NarrativeDecisionFamily,
    NarrativeDecisionReceipt,
    NarrativeDecisionRetryAuthentication,
    RevisionAcceptanceCommand,
    RevisionAcceptanceHead,
)
from r2.narrative_lifecycle.errors import (
    NarrativeAuthorityIntegrityError,
    NarrativeDecisionAuthorizationError,
    NarrativeDecisionIdentityConflictError,
    NarrativeDecisionPredecessorConflict,
)
from r2.narrative_lifecycle.hashing import compute_decision_canonical_identity_hash
from r2.narrative_lifecycle.ports import (
    NarrativeLifecycleRepositoryPort,
    NarrativeLifecycleUnitOfWorkFactory,
    NarrativeShowrunnerAuthorityPort,
)

ApplicabilityCheck = Callable[[NarrativeDecisionCommand], Awaitable[None]]

# §6.4: the family's "select a new effective candidate" action. REJECT is never in this
# map — it never changes the effective pointer, regardless of family.
_ACCEPTING_ACTION: dict[NarrativeDecisionFamily, str] = {
    "REVISION_ACCEPTANCE": "ACCEPT",
    "CHANGE_SET_REVIEW": "ACCEPT",
    "CONFLICT_RESOLUTION": "RESOLVE",
}

_AnyHead = RevisionAcceptanceHead | ChangeSetReviewHead | ConflictResolutionHead


def _canonical_tuple_matches(
    command: NarrativeDecisionCommand,
    stored_command: NarrativeDecisionCommand,
    stored_authorization: NarrativeDecisionAuthorization,
) -> bool:
    """§6.3 exact-retry comparison: the incoming command must canonically identify the
    same decision as the one already stored, judged against the *original* stored
    authorization — never a fresh one. Each side's own ``retry_authentication`` is
    already excluded by the hash function itself."""
    return compute_decision_canonical_identity_hash(
        command, stored_authorization
    ) == compute_decision_canonical_identity_hash(stored_command, stored_authorization)


def _verify_authorization_binding(
    command: NarrativeDecisionCommand, authorization: NarrativeDecisionAuthorization
) -> None:
    scope = command.work_scope
    if (
        authorization.decision_id != command.decision_id
        or authorization.decision_family != command.decision_family
        or authorization.action != command.action
        or authorization.user_id != scope.user_id
        or authorization.project_name != scope.project_name
    ):
        raise NarrativeDecisionAuthorizationError(
            "the authority port's authorization is not bound to this exact command"
        )


def _verify_retry_authentication_binding(
    command: NarrativeDecisionCommand,
    stored_authorization: NarrativeDecisionAuthorization,
    retry: NarrativeDecisionRetryAuthentication,
) -> None:
    scope = command.work_scope
    if (
        retry.decision_id != command.decision_id
        or retry.user_id != scope.user_id
        or retry.project_name != scope.project_name
        or retry.actor_id != stored_authorization.actor_id
    ):
        raise NarrativeDecisionAuthorizationError(
            "the authority port's retry authentication is not bound to this exact decision and actor"
        )


class AuthorityKernel:
    """Owns one fresh authority transaction per ``run()`` call. Family-specific
    business validation (evidence existence, basis, current-effectiveness — spec §7.2
    step 7) is not this kernel's concern: the caller supplies it as
    ``verify_applicability``, run once the head is locked and predecessors are proven
    fresh, before any write.
    """

    def __init__(
        self,
        uow_factory: NarrativeLifecycleUnitOfWorkFactory,
        authority: NarrativeShowrunnerAuthorityPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._authority = authority

    async def run(
        self,
        command: NarrativeDecisionCommand,
        *,
        authenticated_principal: str,
        verify_applicability: ApplicabilityCheck | None = None,
    ) -> NarrativeDecisionReceipt:
        scope = command.work_scope
        async with self._uow_factory() as uow:
            repo = uow.repository

            # Step 2: retry before any head write.
            stored = await repo.get_decision_by_id(
                command.decision_id, user_id=scope.user_id, project_name=scope.project_name
            )
            if stored is not None:
                receipt = await self._resolve_exact_retry(repo, command, stored, authenticated_principal)
                await uow.commit()
                return receipt

            # Step 4: a genuinely new id -- lock or insert the typed head by its
            # complete stable key (null pointers, zero generations).
            head = await self._lock_or_insert_head(repo, command)

            # Step 5: resolve a concurrently-landed exact retry before any
            # stale-predecessor rejection.
            stored = await repo.get_decision_by_id(
                command.decision_id, user_id=scope.user_id, project_name=scope.project_name
            )
            if stored is not None:
                receipt = await self._resolve_exact_retry(repo, command, stored, authenticated_principal)
                await uow.commit()
                return receipt

            # Step 6: compare both expected predecessors against the authoritative head.
            if command.expected_latest_decision_id != head.latest_decision_id:
                raise NarrativeDecisionPredecessorConflict(
                    f"decision {command.decision_id!r} expected a stale latest predecessor"
                )
            if command.expected_effective_decision_id != head.effective_decision_id:
                raise NarrativeDecisionPredecessorConflict(
                    f"decision {command.decision_id!r} expected a stale effective predecessor"
                )

            # Step 7: family-specific applicability (evidence existence, basis,
            # current-effectiveness, mutual applicability). Never re-derived here.
            if verify_applicability is not None:
                await verify_applicability(command)

            # Step 8: obtain and verify the one original authorization, then insert
            # the identity registry row and the typed decision atomically.
            authorization = await self._authority.authorize_initial_decision(authenticated_principal, command)
            _verify_authorization_binding(command, authorization)
            new_generation = head.decision_generation + 1
            canonical_hash = compute_decision_canonical_identity_hash(command, authorization)
            await repo.insert_identity_and_decision(
                command,
                authorization,
                canonical_identity_hash=canonical_hash,
                decision_generation=new_generation,
                stored_at=datetime.now(UTC),
            )

            # Step 9: advance the head. effective_generation bumps only in this same
            # update, and only when the effective selection actually changes.
            if command.action == _ACCEPTING_ACTION[command.decision_family] or command.action == "SUPERSEDE":
                new_effective_decision_id: str | None = command.decision_id
                new_effective_generation = new_generation
            else:
                new_effective_decision_id = head.effective_decision_id
                new_effective_generation = head.effective_generation
            await self._advance_head(
                repo,
                command,
                expected_latest_decision_id=command.expected_latest_decision_id,
                expected_effective_decision_id=command.expected_effective_decision_id,
                new_latest_decision_id=command.decision_id,
                new_decision_generation=new_generation,
                new_effective_decision_id=new_effective_decision_id,
                new_effective_generation=new_effective_generation,
            )

            # Step 10: flush once (already done by the two writes above via the
            # repository), commit once.
            await uow.commit()
            return NarrativeDecisionReceipt(
                decision_id=command.decision_id,
                decision_family=command.decision_family,
                action=command.action,
                decision_generation=new_generation,
                effective_decision_id=new_effective_decision_id,
                effective_generation=new_effective_generation,
            )

    async def _resolve_exact_retry(
        self,
        repo: NarrativeLifecycleRepositoryPort,
        command: NarrativeDecisionCommand,
        stored: tuple[NarrativeDecisionCommand, NarrativeDecisionAuthorization, int],
        authenticated_principal: str,
    ) -> NarrativeDecisionReceipt:
        stored_command, stored_authorization, stored_generation = stored
        if not _canonical_tuple_matches(command, stored_command, stored_authorization):
            raise NarrativeDecisionIdentityConflictError(
                f"decision {command.decision_id!r} conflicts with an existing decision"
            )
        retry = await self._authority.authenticate_exact_retry(
            authenticated_principal, command.decision_id, command.work_scope
        )
        _verify_retry_authentication_binding(command, stored_authorization, retry)
        effective_decision_id, effective_generation = await self._effective_pointer_of(
            repo, stored_command, stored_generation
        )
        return NarrativeDecisionReceipt(
            decision_id=stored_command.decision_id,
            decision_family=stored_command.decision_family,
            action=stored_command.action,
            decision_generation=stored_generation,
            effective_decision_id=effective_decision_id,
            effective_generation=effective_generation,
        )

    async def _effective_pointer_of(
        self, repo: NarrativeLifecycleRepositoryPort, command: NarrativeDecisionCommand, decision_generation: int
    ) -> tuple[str | None, int]:
        """The effective pointer that resulted immediately from appending ``command``
        (never the head's current value, which may have moved on since). Derived, not
        stored: an accepting/superseding decision always becomes its own effective
        selection; a rejection leaves whatever it named as ``expected_effective``
        unchanged, and that referenced decision's own generation is one more lookup."""
        if command.action == _ACCEPTING_ACTION[command.decision_family] or command.action == "SUPERSEDE":
            return command.decision_id, decision_generation
        if command.expected_effective_decision_id is None:
            return None, 0
        referenced = await repo.get_decision_by_id(
            command.expected_effective_decision_id,
            user_id=command.work_scope.user_id,
            project_name=command.work_scope.project_name,
        )
        if referenced is None:
            raise NarrativeAuthorityIntegrityError(
                f"decision {command.decision_id!r} names an effective predecessor that no longer resolves"
            )
        return command.expected_effective_decision_id, referenced[2]

    async def _lock_or_insert_head(
        self, repo: NarrativeLifecycleRepositoryPort, command: NarrativeDecisionCommand
    ) -> _AnyHead:
        scope = command.work_scope
        if isinstance(command, RevisionAcceptanceCommand):
            return await repo.lock_or_insert_revision_head(scope)
        if isinstance(command, ChangeSetReviewCommand):
            return await repo.lock_or_insert_change_set_review_head(
                revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                change_set_lineage_id=command.change_set_lineage_id,
                user_id=scope.user_id,
                project_name=scope.project_name,
            )
        assert isinstance(command, ConflictResolutionCommand)
        return await repo.lock_or_insert_conflict_resolution_head(
            revision_acceptance_decision_id=command.revision_acceptance_decision_id,
            conflict_resolution_lineage_id=command.conflict_resolution_lineage_id,
            user_id=scope.user_id,
            project_name=scope.project_name,
        )

    async def _advance_head(
        self,
        repo: NarrativeLifecycleRepositoryPort,
        command: NarrativeDecisionCommand,
        *,
        expected_latest_decision_id: str | None,
        expected_effective_decision_id: str | None,
        new_latest_decision_id: str,
        new_decision_generation: int,
        new_effective_decision_id: str | None,
        new_effective_generation: int,
    ) -> None:
        if isinstance(command, RevisionAcceptanceCommand):
            await repo.advance_revision_head(
                command.work_scope,
                expected_latest_decision_id=expected_latest_decision_id,
                expected_effective_decision_id=expected_effective_decision_id,
                new_latest_decision_id=new_latest_decision_id,
                new_decision_generation=new_decision_generation,
                new_effective_decision_id=new_effective_decision_id,
                new_effective_generation=new_effective_generation,
            )
        elif isinstance(command, ChangeSetReviewCommand):
            await repo.advance_change_set_review_head(
                revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                change_set_lineage_id=command.change_set_lineage_id,
                expected_latest_decision_id=expected_latest_decision_id,
                expected_effective_decision_id=expected_effective_decision_id,
                new_latest_decision_id=new_latest_decision_id,
                new_decision_generation=new_decision_generation,
                new_effective_decision_id=new_effective_decision_id,
                new_effective_generation=new_effective_generation,
            )
        else:
            assert isinstance(command, ConflictResolutionCommand)
            await repo.advance_conflict_resolution_head(
                revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                conflict_resolution_lineage_id=command.conflict_resolution_lineage_id,
                expected_latest_decision_id=expected_latest_decision_id,
                expected_effective_decision_id=expected_effective_decision_id,
                new_latest_decision_id=new_latest_decision_id,
                new_decision_generation=new_decision_generation,
                new_effective_decision_id=new_effective_decision_id,
                new_effective_generation=new_effective_generation,
            )
