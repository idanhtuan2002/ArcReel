"""``NarrativeAcceptanceService`` — the authenticated public facade for the Narrative
decision authority.

Exposes exactly: ``decide_revision``, ``review_change_set``, ``resolve_change_set_conflict``,
``admit_canon_handoff``, and the read-only ``get_current_*`` /
``verify_exact_current_selection`` observations. No generic ``save_decision``,
``set_head``, ``approve``, ``latest``, or raw repository method is public. The public
surface never accepts a caller-supplied ``NarrativeDecisionAuthorization`` — every
command takes only ``command`` and ``authenticated_principal`` (plus, for the handoff
admission, the exact existing M5A ``CanonCommitApproval``); the injected
``NarrativeShowrunnerAuthorityPort`` decides who may act, and the ``AuthorityKernel`` or
``admit_canon_handoff`` itself calls it.

The three decision commands share the ``AuthorityKernel``. ``admit_canon_handoff`` does
not: it advances no head, so it has its own transaction body (spec section 11.2) that only
*reads under lock* the heads the kernel would advance, and appends a separate immutable
``NarrativeHandoffAdmission`` receipt. It writes no Canon row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import ConfigDict, Field

from r2.contracts.common import NonEmptyStr, R2ContractModel
from r2.contracts.narrative import CanonCommitApproval, CanonDelta
from r2.contracts.narrative_lifecycle import (
    ChangeSetReviewCommand,
    ChangeSetReviewHead,
    CompilationAttempt,
    ConflictResolutionCommand,
    ConflictResolutionHead,
    ConflictResolutionLineage,
    NarrativeChangeSet,
    NarrativeDecisionCommand,
    NarrativeDecisionFamily,
    NarrativeDecisionReceipt,
    NarrativeHandoffAdmission,
    NarrativeWorkScope,
    ObservedNarrativeHead,
    RevisionAcceptanceCommand,
    RevisionAcceptanceHead,
)
from r2.narrative.hashing import compute_canon_delta_hash
from r2.narrative_lifecycle.authority_kernel import AuthorityKernel, head_lock_sort_key
from r2.narrative_lifecycle.coverage import minimal_conflict_subject
from r2.narrative_lifecycle.errors import (
    NarrativeConflictLineageConflict,
    NarrativeDecisionApplicabilityError,
    NarrativeDecisionAuthorizationError,
    NarrativeDecisionIdentityConflictError,
    NarrativeEvidenceIntegrityError,
    NarrativeHandoffConflict,
)
from r2.narrative_lifecycle.hashing import (
    compute_canon_approval_binding_fingerprint,
    compute_conflict_subject_fingerprint,
    compute_handoff_admission_identity_hash,
)
from r2.narrative_lifecycle.ports import (
    NarrativeLifecycleRepositoryPort,
    NarrativeLifecycleUnitOfWorkFactory,
    NarrativeShowrunnerAuthorityPort,
)

_AnyHead = RevisionAcceptanceHead | ChangeSetReviewHead | ConflictResolutionHead

# One head this admission must hold: its family, its logical subject key, and the exact
# decision the compilation attempt named as effective for it.
type _HandoffLockTarget = tuple[NarrativeDecisionFamily, tuple[str, ...], str]

# One selected change set as the attempt named it, resolved to its own review lineage.
type _ResolvedReview = tuple[str, str, str]  # (review_decision_id, change_set_lineage_id, change_set_id)

# One lock target paired with whatever the locked read found for it.
type _LockedHead = tuple[_HandoffLockTarget, _AnyHead | None]


class CanonHandoffAdmissionCommand(R2ContractModel):
    """The request to admit one ``SUCCEEDED`` compilation result for the existing M5A
    handoff (spec section 11.2). Deliberately narrow: everything the receipt binds — the
    delta and its payload hash, the revision/review/resolution decisions, the exact
    Canon base, the observed heads — is derived from the persisted compilation attempt,
    result, and compiled-delta evidence, never caller-supplied, exactly as
    ``CompilationAdmissionCommand``'s shared-basis fields are read from the named
    revision. ``admission_id`` is caller-chosen, opaque, and globally unique: the same id
    with the exact same tuple replays the original immutable receipt, and with any
    different field is an identity conflict.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    admission_id: NonEmptyStr
    work_scope: NarrativeWorkScope
    compilation_attempt_id: NonEmptyStr
    generation: Annotated[int, Field(ge=0)]
    compilation_result_id: NonEmptyStr


class AdmittedNarrativeHandoff(R2ContractModel):
    """The application result of one admission: the immutable receipt plus exact deep
    copies of the *persisted* ``CanonDelta`` and ``CanonCommitApproval`` it binds. A
    convenience result, not another durable authority contract — the facade never
    substitutes a caller-held, recompiled, reconstructed, or freshly issued tuple after
    admission, so both payloads here are reloaded from the durable rows, never echoed
    back from the caller's own input.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    admission: NarrativeHandoffAdmission
    canon_delta: CanonDelta
    canon_commit_approval: CanonCommitApproval

    @property
    def admission_id(self) -> str:
        return self.admission.admission_id

    @property
    def revision_acceptance_decision_id(self) -> str:
        return self.admission.revision_acceptance_decision_id


async def _resolve_admission_reviews(
    repo: NarrativeLifecycleRepositoryPort, attempt: CompilationAttempt
) -> list[_ResolvedReview]:
    """Resolve every review decision the attempt selected against its typed authoritative
    chain: it must be a ``ChangeSetReviewCommand`` naming the exact change set, in this
    attempt's exact scope and under its exact revision acceptance. Unlocked here — the
    lock and the currentness proof come next; this only says what must be locked."""
    scope = attempt.work_scope
    resolved: list[_ResolvedReview] = []
    for selected in attempt.selected_change_sets:
        stored = await repo.get_decision_by_id(
            selected.review_decision_id, user_id=scope.user_id, project_name=scope.project_name
        )
        if stored is None:
            raise NarrativeEvidenceIntegrityError(
                f"review decision {selected.review_decision_id!r} named by this attempt does not resolve"
            )
        review_command = stored[0]
        if (
            not isinstance(review_command, ChangeSetReviewCommand)
            or review_command.selected_change_set_id != selected.change_set_id
            or review_command.work_scope != scope
            or review_command.revision_acceptance_decision_id != attempt.revision_acceptance_decision_id
        ):
            raise NarrativeEvidenceIntegrityError(
                f"review decision {selected.review_decision_id!r} does not select change set "
                f"{selected.change_set_id!r} under this attempt's exact scope and revision acceptance"
            )
        resolved.append((selected.review_decision_id, review_command.change_set_lineage_id, selected.change_set_id))
    return resolved


async def _resolve_admission_resolutions(
    repo: NarrativeLifecycleRepositoryPort, attempt: CompilationAttempt
) -> dict[str, ConflictResolutionCommand]:
    scope = attempt.work_scope
    resolutions: dict[str, ConflictResolutionCommand] = {}
    for decision_id in attempt.conflict_resolution_decision_ids:
        stored = await repo.get_decision_by_id(decision_id, user_id=scope.user_id, project_name=scope.project_name)
        if stored is None:
            raise NarrativeEvidenceIntegrityError(
                f"conflict resolution {decision_id!r} named by this attempt does not resolve"
            )
        resolution_command = stored[0]
        if (
            not isinstance(resolution_command, ConflictResolutionCommand)
            or resolution_command.action != "RESOLVE"
            or resolution_command.work_scope != scope
            or resolution_command.revision_acceptance_decision_id != attempt.revision_acceptance_decision_id
        ):
            raise NarrativeEvidenceIntegrityError(
                f"conflict resolution {decision_id!r} is not an applicable RESOLVE decision under this "
                "attempt's exact scope and revision acceptance"
            )
        resolutions[decision_id] = resolution_command
    return resolutions


async def _require_revision_chain(repo: NarrativeLifecycleRepositoryPort, attempt: CompilationAttempt) -> None:
    scope = attempt.work_scope
    stored = await repo.get_decision_by_id(
        attempt.revision_acceptance_decision_id, user_id=scope.user_id, project_name=scope.project_name
    )
    if stored is None:
        raise NarrativeEvidenceIntegrityError(
            f"revision acceptance {attempt.revision_acceptance_decision_id!r} does not resolve"
        )
    revision_command = stored[0]
    if (
        not isinstance(revision_command, RevisionAcceptanceCommand)
        or revision_command.work_scope != scope
        or revision_command.selected_revision_id != attempt.revision_id
    ):
        raise NarrativeEvidenceIntegrityError(
            f"revision acceptance {attempt.revision_acceptance_decision_id!r} does not select revision "
            f"{attempt.revision_id!r} in this attempt's exact scope"
        )


def _handoff_lock_targets(
    attempt: CompilationAttempt, reviews: list[_ResolvedReview], resolutions: dict[str, ConflictResolutionCommand]
) -> list[_HandoffLockTarget]:
    """Every head this admission must hold, sorted by the one canonical cross-family lock
    order the kernel and the compilation guard already use — never by the attempt's own
    listing order, so a concurrent decision cannot deadlock against it."""
    scope = attempt.work_scope
    revision_key = (scope.plan_id, scope.scene_contract_id, scope.canon_branch_id)
    targets: list[_HandoffLockTarget] = [("REVISION_ACCEPTANCE", revision_key, attempt.revision_acceptance_decision_id)]
    for review_decision_id, lineage_id, _change_set_id in reviews:
        targets.append(("CHANGE_SET_REVIEW", (attempt.revision_acceptance_decision_id, lineage_id), review_decision_id))
    for decision_id, resolution in resolutions.items():
        targets.append(
            (
                "CONFLICT_RESOLUTION",
                (attempt.revision_acceptance_decision_id, resolution.conflict_resolution_lineage_id),
                decision_id,
            )
        )
    return sorted(
        targets,
        key=lambda target: head_lock_sort_key(
            target[0], user_id=scope.user_id, project_name=scope.project_name, logical_key=target[1]
        ),
    )


def _observe_locked_heads(locked: list[_LockedHead]) -> tuple[ObservedNarrativeHead, ...]:
    """Judge the already-locked projections: each must exist and must still name the exact
    decision the compilation attempt recorded as effective. Separate from the locking pass
    so an exact admission that landed concurrently can replay first."""
    observed: list[ObservedNarrativeHead] = []
    for (family, logical_key, expected_decision_id), head in locked:
        if head is None or head.effective_decision_id != expected_decision_id:
            raise NarrativeHandoffConflict(
                f"decision {expected_decision_id!r} is no longer the current effective selection "
                "for its head at the admission instant"
            )
        observed.append(
            ObservedNarrativeHead(
                head_family=family,
                logical_key=logical_key,
                effective_decision_id=head.effective_decision_id,
                effective_generation=head.effective_generation,
                decision_generation=head.decision_generation,
            )
        )
    return tuple(observed)


async def _require_resolutions_remain_applicable(
    repo: NarrativeLifecycleRepositoryPort,
    attempt: CompilationAttempt,
    resolutions: dict[str, ConflictResolutionCommand],
) -> None:
    """A resolution stays applicable only while every review decision it named is still
    the effective selection for that review's own lineage. Read, not locked: the
    resolution's own head is already held, and taking a fresh rank-1 lock after a rank-2
    one would break the canonical order."""
    scope = attempt.work_scope
    for decision_id, resolution in resolutions.items():
        for review_decision_id in resolution.competing_review_decision_ids:
            stored = await repo.get_decision_by_id(
                review_decision_id, user_id=scope.user_id, project_name=scope.project_name
            )
            if stored is None or not isinstance(stored[0], ChangeSetReviewCommand):
                raise NarrativeEvidenceIntegrityError(
                    f"conflict resolution {decision_id!r} names review decision {review_decision_id!r}, "
                    "which does not resolve"
                )
            review_head = await repo.get_change_set_review_head(
                revision_acceptance_decision_id=attempt.revision_acceptance_decision_id,
                change_set_lineage_id=stored[0].change_set_lineage_id,
                user_id=scope.user_id,
                project_name=scope.project_name,
            )
            if review_head is None or review_head.effective_decision_id != review_decision_id:
                raise NarrativeHandoffConflict(
                    f"conflict resolution {decision_id!r} names review decision {review_decision_id!r}, "
                    "which is no longer the current effective selection for its lineage"
                )


def _require_delta_matches_the_attempt(
    delta: CanonDelta, attempt: CompilationAttempt, reviews: list[_ResolvedReview]
) -> None:
    """The persisted payload must be exactly the one the pure compiler seals for this
    attempt: the attempt's Canon branch and base, its exact selection, and every
    effective decision it named — the accepted revision plus every review and
    resolution."""
    scope = attempt.work_scope
    expected_authors = sorted(
        {
            attempt.revision_acceptance_decision_id,
            *(review_decision_id for review_decision_id, _, _ in reviews),
            *attempt.conflict_resolution_decision_ids,
        }
    )
    expected_change_sets = sorted({selected.change_set_id for selected in attempt.selected_change_sets})
    if delta.target_branch_id != scope.canon_branch_id:
        raise NarrativeEvidenceIntegrityError("the compiled delta targets another Canon branch than this attempt")
    if delta.base_canon_version_id != attempt.base_canon_version_id:
        raise NarrativeEvidenceIntegrityError("the compiled delta names another Canon base than this attempt")
    if delta.canon_delta_id != attempt.requested_canon_delta_id:
        raise NarrativeEvidenceIntegrityError("the compiled delta is not the delta this attempt requested")
    if sorted(set(delta.author_decision_refs)) != expected_authors:
        raise NarrativeEvidenceIntegrityError(
            "the compiled delta does not name exactly this attempt's effective decisions"
        )
    if sorted(set(delta.source_change_set_refs)) != expected_change_sets:
        raise NarrativeEvidenceIntegrityError("the compiled delta does not name exactly this attempt's selection")


def _require_approval_binds_the_delta(
    approval: CanonCommitApproval, delta: CanonDelta, *, delta_payload_hash: str, actor_id: str, completed_at: datetime
) -> None:
    """Spec section 11.2 step 6: the exact existing M5A approval must bind this exact
    delta, scope, hash/schema versions, actor, status, and timestamp. ``status`` is a
    contract-level ``Literal["APPROVED"]``, so an unapproved tuple cannot reach here at
    all. The actor rule is M5C v1's single Human Showrunner authority (section 6.2):
    the Human who approved the Canon commit is the Human who admits it; splitting those
    two roles would need an ADR amendment, not a looser check here.
    """
    if approval.canon_delta_id != delta.canon_delta_id:
        raise NarrativeEvidenceIntegrityError("the Canon commit approval binds another canon delta id")
    if approval.payload_hash != delta_payload_hash:
        raise NarrativeEvidenceIntegrityError("the Canon commit approval binds another canon delta payload hash")
    if (
        approval.payload_hash_algorithm != delta.payload_hash_algorithm
        or approval.payload_hash_version != delta.payload_hash_version
        or approval.content_schema_version != delta.content_schema_version
    ):
        raise NarrativeEvidenceIntegrityError(
            "the Canon commit approval binds another payload-hash algorithm/version or content-schema version"
        )
    if approval.approved_by != actor_id:
        raise NarrativeEvidenceIntegrityError(
            "the Canon commit approval was issued by another actor than the admitting Human Showrunner"
        )
    if approval.approved_at < completed_at:
        raise NarrativeEvidenceIntegrityError(
            "the Canon commit approval predates the compilation result it claims to approve"
        )


class NarrativeAcceptanceService:
    """One authority adapter per service instance; constructed without one, it raises
    rather than defaulting to a permissive stub."""

    def __init__(
        self,
        uow_factory: NarrativeLifecycleUnitOfWorkFactory,
        authority: NarrativeShowrunnerAuthorityPort | None,
    ) -> None:
        if authority is None:
            raise ValueError(
                "NarrativeAcceptanceService requires a NarrativeShowrunnerAuthorityPort; "
                "it never defaults to a permissive stub"
            )
        self._uow_factory = uow_factory
        # The three decision commands reach the port through the kernel; the handoff
        # admission runs its own transaction body and calls the same port directly.
        self._authority = authority
        self._kernel = AuthorityKernel(uow_factory, authority)

    async def decide_revision(
        self, command: RevisionAcceptanceCommand, *, authenticated_principal: str
    ) -> NarrativeDecisionReceipt:
        return await self._kernel.run(command, authenticated_principal=authenticated_principal)

    async def review_change_set(
        self, command: ChangeSetReviewCommand, *, authenticated_principal: str
    ) -> NarrativeDecisionReceipt:
        return await self._kernel.run(command, authenticated_principal=authenticated_principal)

    async def resolve_change_set_conflict(
        self, command: ConflictResolutionCommand, *, authenticated_principal: str
    ) -> NarrativeDecisionReceipt:
        """The only conflict-lineage creation interface. A genesis command
        (``expected_latest_decision_id is None``) atomically derives the canonical
        conflict subject from the exact currently-effective competing change-set
        reviews, creates the lineage + its zero-generation head, and appends the first
        decision; a non-genesis command acts on an already-existing lineage/head."""
        prepare_genesis = self._prepare_conflict_genesis if command.expected_latest_decision_id is None else None
        return await self._kernel.run(
            command,
            authenticated_principal=authenticated_principal,
            verify_applicability=self._verify_conflict_applicability,
            prepare_genesis=prepare_genesis,
        )

    async def admit_canon_handoff(
        self,
        command: CanonHandoffAdmissionCommand,
        *,
        authenticated_principal: str,
        canon_commit_approval: CanonCommitApproval,
    ) -> AdmittedNarrativeHandoff:
        """The single point at which a Narrative decision becomes eligible to become real
        Canon state (spec section 11.2). One fresh short transaction, in this order:

        1. validate and deep-copy the exact existing M5A ``CanonCommitApproval`` input;
        2. begin the transaction;
        3. resolve an exact admission retry **before** testing currentness;
        4. lock the revision, selected change-set, and required conflict heads in
           canonical order;
        5. load the exact persisted ``CompiledCanonDeltaEvidence`` and verify it against
           the successful compilation result, attempt, scope, exact bases, and all
           effective decisions;
        6. recompute the delta payload hash **and** the complete approval fingerprint and
           require the approval to bind that exact delta, scope, hash/schema versions,
           actor, status, and timestamp;
        7. verify each locked projection against its typed authoritative chain, prove
           every recorded effective pointer still equals the named decision, and prove
           every resolution remains applicable;
        8. append the immutable receipt and the exact approval payload atomically; and
        9. commit once.

        No Canon row is locked or written here. Currentness is frozen at the admission
        instant (section 11.3): a Narrative decision committing before receipt insertion
        is observed under the locked heads and blocks admission; a supersession
        committing afterwards never retroactively invalidates the receipt.
        """
        scope = command.work_scope
        # (1) The caller's approval is copied, never aliased: nothing downstream can
        # mutate the tuple this receipt binds.
        approval = canon_commit_approval.model_copy(deep=True)
        if approval.user_id != scope.user_id or approval.project_name != scope.project_name:
            raise NarrativeEvidenceIntegrityError(
                "the Canon commit approval belongs to another tenant or project than this admission"
            )
        approval_fingerprint = compute_canon_approval_binding_fingerprint(approval)

        # (2) One fresh short Narrative transaction.
        async with self._uow_factory() as uow:
            repo = uow.repository
            # The Human Showrunner capability check fails closed before anything is read
            # or locked. ``authenticate_scoped_showrunner``, deliberately: not
            # ``authorize_initial_decision``, which mints a typed family's persisted
            # authorization this receipt has nowhere to store, and not
            # ``authenticate_exact_retry``, whose precondition is an already-stored
            # decision and whose ``decision_id`` is a different id space from
            # ``admission_id``. It resolves a capability rather than a decision, so it can
            # run first, and both the retry and the initial path need its ``actor_id``.
            authentication = await self._authority.authenticate_scoped_showrunner(
                authenticated_principal, command.admission_id, scope
            )
            if (
                authentication.decision_id != command.admission_id
                or authentication.user_id != scope.user_id
                or authentication.project_name != scope.project_name
            ):
                raise NarrativeDecisionAuthorizationError(
                    "the authority port's authentication is not bound to this exact admission and scope"
                )
            actor_id = authentication.actor_id

            # (3) Exact admission retry, resolved before any currentness test — mirroring
            # the kernel's own "retry check runs before any head write" ordering.
            existing = await repo.get_exact_handoff_admission(
                admission_id=command.admission_id, project_name=scope.project_name, user_id=scope.user_id
            )
            if existing is None:
                stray = await repo.get_handoff_admission_by_id(admission_id=command.admission_id)
                if stray is not None:
                    raise NarrativeDecisionIdentityConflictError(
                        f"handoff admission {command.admission_id!r} conflicts with an existing admission"
                    )
            if existing is not None:
                replay = await self._replay_exact_admission(
                    repo, command, existing, approval, approval_fingerprint, actor_id
                )
                await uow.commit()
                return replay

            attempt = await repo.get_exact_compilation_attempt(
                attempt_id=command.compilation_attempt_id,
                project_name=scope.project_name,
                user_id=scope.user_id,
            )
            if attempt is None or attempt.generation != command.generation or attempt.work_scope != scope:
                raise NarrativeEvidenceIntegrityError(
                    f"compilation attempt {command.compilation_attempt_id!r} at generation "
                    f"{command.generation} does not resolve in this exact scope"
                )
            await _require_revision_chain(repo, attempt)
            reviews = await _resolve_admission_reviews(repo, attempt)
            resolutions = await _resolve_admission_resolutions(repo, attempt)

            # (4) Lock every head this admission depends on, in canonical order.
            locked = await self._lock_admission_heads(
                repo, attempt, _handoff_lock_targets(attempt, reviews, resolutions)
            )

            # Resolve a concurrently-landed exact admission before any currentness
            # rejection — the same second lookup ``AuthorityKernel.run`` performs after
            # locking its head. Two identical admissions serialize on these locks; the
            # loser's step-3 lookup ran before the winner committed, so without this it
            # would fall through to a unique violation instead of replaying the original
            # receipt. Placed before the rejection below, not after, because section 11.3
            # forbids a supersession from retroactively invalidating a receipt that is
            # already committed.
            landed = await repo.get_exact_handoff_admission(
                admission_id=command.admission_id, project_name=scope.project_name, user_id=scope.user_id
            )
            if landed is not None:
                replay = await self._replay_exact_admission(
                    repo, command, landed, approval, approval_fingerprint, actor_id
                )
                await uow.commit()
                return replay

            # Every locked projection must still name the exact decision the attempt
            # recorded as effective.
            observed_heads = _observe_locked_heads(locked)

            # (5) + (6) The persisted compiled delta, then the approval that binds it.
            delta, completed_at = await self._load_admitted_delta(repo, command, attempt, reviews)
            payload_hash = compute_canon_delta_hash(delta)
            if payload_hash != delta.payload_hash:
                raise NarrativeEvidenceIntegrityError(
                    "the recomputed canon delta payload hash does not match the persisted payload"
                )
            _require_approval_binds_the_delta(
                approval, delta, delta_payload_hash=payload_hash, actor_id=actor_id, completed_at=completed_at
            )

            # (7) The rest of the typed authoritative chain: every effective pointer is
            # already proven under lock above; a resolution must additionally still cover
            # reviews that are themselves still effective.
            await _require_resolutions_remain_applicable(repo, attempt, resolutions)
            recorded = {head.decision_id for head in attempt.observed_effective_heads}
            still_effective = {head.effective_decision_id for head in observed_heads}
            if not recorded <= still_effective:
                raise NarrativeHandoffConflict(
                    "a decision this compilation attempt observed as effective is no longer effective"
                )

            # (8) Append the immutable receipt and the exact approval payload atomically.
            draft = NarrativeHandoffAdmission(
                admission_id=command.admission_id,
                work_scope=scope,
                compilation_attempt_id=attempt.attempt_id,
                generation=attempt.generation,
                compilation_result_id=command.compilation_result_id,
                canon_delta_id=delta.canon_delta_id,
                canon_delta_payload_hash=payload_hash,
                canon_commit_approval_ref=approval.approval_ref,
                canon_commit_approval=approval,
                canon_commit_approval_fingerprint=approval_fingerprint,
                canon_commit_approval_fingerprint_algorithm="sha256",
                revision_acceptance_decision_id=attempt.revision_acceptance_decision_id,
                review_decision_ids=tuple(review_decision_id for review_decision_id, _, _ in reviews),
                conflict_resolution_decision_ids=attempt.conflict_resolution_decision_ids,
                observed_heads=observed_heads,
                base_canon_version_id=attempt.base_canon_version_id,
                actor_id=actor_id,
                admitted_at=datetime.now(UTC),
                canonical_identity_hash="pending",
            )
            admission = draft.model_copy(
                update={"canonical_identity_hash": compute_handoff_admission_identity_hash(draft)}
            )
            await repo.insert_handoff_admission(admission)

            # (9) Commit once.
            await uow.commit()
            return AdmittedNarrativeHandoff(
                admission=admission,
                canon_delta=delta.model_copy(deep=True),
                canon_commit_approval=admission.canon_commit_approval.model_copy(deep=True),
            )

    async def _replay_exact_admission(
        self,
        repo: NarrativeLifecycleRepositoryPort,
        command: CanonHandoffAdmissionCommand,
        existing: NarrativeHandoffAdmission,
        approval: CanonCommitApproval,
        approval_fingerprint: str,
        actor_id: str,
    ) -> AdmittedNarrativeHandoff:
        """An exact retry returns the original immutable receipt with the delta and
        approval reloaded from their durable rows — never the caller's own copies, and
        never a fresh currentness judgement (section 11.3: a supersession after the
        admission transaction does not retroactively invalidate the receipt).

        Every degree of freedom the caller has is compared: the admission's own
        attempt/generation/result identity, the complete approval payload, its binding
        fingerprint (so a changed hash algorithm or version fails closed rather than
        matching by coincidence), and the admitting actor.
        """
        if (
            existing.compilation_attempt_id != command.compilation_attempt_id
            or existing.generation != command.generation
            or existing.compilation_result_id != command.compilation_result_id
            or existing.work_scope != command.work_scope
            or existing.canon_commit_approval != approval
            or existing.canon_commit_approval_ref != approval.approval_ref
            or existing.canon_commit_approval_fingerprint != approval_fingerprint
            or existing.canon_commit_approval_fingerprint_algorithm != "sha256"
            or existing.actor_id != actor_id
        ):
            raise NarrativeDecisionIdentityConflictError(
                f"handoff admission {command.admission_id!r} conflicts with an existing admission"
            )
        scope = existing.work_scope
        evidence = await repo.get_exact_compiled_canon_delta(
            compilation_result_id=existing.compilation_result_id,
            project_name=scope.project_name,
            user_id=scope.user_id,
        )
        if evidence is None or evidence.canon_delta_payload_hash != existing.canon_delta_payload_hash:
            raise NarrativeEvidenceIntegrityError(
                f"the delta admitted by {existing.admission_id!r} no longer resolves to its exact persisted payload"
            )
        return AdmittedNarrativeHandoff(
            admission=existing,
            canon_delta=evidence.canon_delta.model_copy(deep=True),
            canon_commit_approval=existing.canon_commit_approval.model_copy(deep=True),
        )

    async def _lock_admission_heads(
        self,
        repo: NarrativeLifecycleRepositoryPort,
        attempt: CompilationAttempt,
        targets: list[_HandoffLockTarget],
    ) -> list[_LockedHead]:
        """Acquire every lock, reject nothing. Judging what the locked heads say is
        ``_observe_locked_heads``' job, and it must not run until a concurrently-landed
        exact admission has had its chance to replay."""
        scope = attempt.work_scope
        # A comprehension, but a strictly sequential one: ``targets`` is already in the
        # canonical order and this is the order the locks are actually taken in.
        return [(target, await self._lock_existing_head(repo, target[0], target[1], scope)) for target in targets]

    async def _lock_existing_head(
        self,
        repo: NarrativeLifecycleRepositoryPort,
        family: NarrativeDecisionFamily,
        logical_key: tuple[str, ...],
        scope: NarrativeWorkScope,
    ) -> _AnyHead | None:
        """``lock_existing_*`` only — an admission never creates a head it did not find,
        and never advances one."""
        if family == "REVISION_ACCEPTANCE":
            return await repo.lock_existing_revision_head(scope)
        if family == "CHANGE_SET_REVIEW":
            return await repo.lock_existing_change_set_review_head(
                revision_acceptance_decision_id=logical_key[0],
                change_set_lineage_id=logical_key[1],
                user_id=scope.user_id,
                project_name=scope.project_name,
            )
        return await repo.lock_existing_conflict_resolution_head(
            revision_acceptance_decision_id=logical_key[0],
            conflict_resolution_lineage_id=logical_key[1],
            user_id=scope.user_id,
            project_name=scope.project_name,
        )

    async def _load_admitted_delta(
        self,
        repo: NarrativeLifecycleRepositoryPort,
        command: CanonHandoffAdmissionCommand,
        attempt: CompilationAttempt,
        reviews: list[_ResolvedReview],
    ) -> tuple[CanonDelta, datetime]:
        """Spec section 11.2 step 5. Only the one ``SUCCEEDED`` result recorded for this
        attempt generation can be admitted: a stale result id, an outcome-only result, or
        a compiled payload that does not reproduce this attempt's exact scope, bases, and
        effective decisions all fail closed with no write."""
        scope = attempt.work_scope
        result = await repo.get_exact_compilation_result(
            attempt_id=attempt.attempt_id,
            generation=attempt.generation,
            project_name=scope.project_name,
            user_id=scope.user_id,
        )
        if result is None or result.result_id != command.compilation_result_id:
            raise NarrativeEvidenceIntegrityError(
                f"compilation result {command.compilation_result_id!r} is not the result recorded for "
                f"attempt {attempt.attempt_id!r} generation {attempt.generation}"
            )
        if result.outcome != "SUCCEEDED":
            raise NarrativeEvidenceIntegrityError(
                f"a {result.outcome} compilation result proposes no canon delta and cannot be admitted"
            )
        evidence = await repo.get_exact_compiled_canon_delta(
            compilation_result_id=result.result_id, project_name=scope.project_name, user_id=scope.user_id
        )
        if evidence is None:
            raise NarrativeEvidenceIntegrityError(
                f"compilation result {result.result_id!r} has no persisted compiled canon delta"
            )
        if evidence.compilation_attempt_id != attempt.attempt_id or evidence.generation != attempt.generation:
            raise NarrativeEvidenceIntegrityError(
                "the persisted compiled delta belongs to another compilation attempt or generation"
            )
        if evidence.canon_delta_payload_hash != result.canon_delta_payload_hash:
            raise NarrativeEvidenceIntegrityError(
                "the persisted compiled delta and its result disagree on the payload hash"
            )
        _require_delta_matches_the_attempt(evidence.canon_delta, attempt, reviews)
        return evidence.canon_delta, result.completed_at

    async def _verify_conflict_applicability(
        self, repo: NarrativeLifecycleRepositoryPort, command: NarrativeDecisionCommand
    ) -> None:
        assert isinstance(command, ConflictResolutionCommand)
        # Read-only here: the kernel already holds this decision's own conflict-
        # resolution head (rank 2) by this point, so taking a fresh lock on rank-1
        # change-set-review heads now would violate the canonical lock order and risk a
        # deadlock against a genesis on the same heads. Genesis (below) runs before any
        # head is locked, so it can safely lock in order.
        await self._verify_competitors(repo, command, lock=False)

    async def _prepare_conflict_genesis(
        self, repo: NarrativeLifecycleRepositoryPort, command: NarrativeDecisionCommand
    ) -> None:
        assert isinstance(command, ConflictResolutionCommand)
        scope = command.work_scope
        revision_head = await repo.lock_or_insert_revision_head(scope)
        if revision_head.effective_decision_id != command.revision_acceptance_decision_id:
            raise NarrativeDecisionApplicabilityError(
                f"revision acceptance {command.revision_acceptance_decision_id!r} is not the current effective revision"
            )
        change_sets = await self._verify_competitors(repo, command, lock=True)
        subject = minimal_conflict_subject(change_sets)
        fingerprint = compute_conflict_subject_fingerprint(subject)
        proposed = ConflictResolutionLineage(
            conflict_resolution_lineage_id=command.conflict_resolution_lineage_id,
            revision_acceptance_decision_id=command.revision_acceptance_decision_id,
            conflict_subject=subject,
            conflict_subject_fingerprint=fingerprint,
            created_at=datetime.now(UTC),
            created_by=command.actor_id,
        )
        winner = await repo.insert_conflict_lineage(proposed, user_id=scope.user_id, project_name=scope.project_name)
        if winner.conflict_resolution_lineage_id != command.conflict_resolution_lineage_id:
            raise NarrativeConflictLineageConflict(
                f"this conflict subject already belongs to lineage {winner.conflict_resolution_lineage_id!r}"
            )

    async def _verify_competitors(
        self, repo: NarrativeLifecycleRepositoryPort, command: ConflictResolutionCommand, *, lock: bool
    ) -> list[NarrativeChangeSet]:
        """Resolve and verify every named competitor: its review decision must resolve,
        must select exactly the named change set, and must still be the current
        effective selection for its own lineage. Returns the exact evidence rows so a
        genesis caller can derive the conflict subject from the same verified read.

        ``lock=True`` (genesis only) additionally holds each competing change-set-review
        head for the rest of this transaction, in the canonical order — sorted by
        ``head_lock_sort_key``, never by the caller's own listing order — so two genesis
        commands naming the same lineages in opposite order cannot deadlock.
        """
        scope = command.work_scope
        resolved: list[tuple[str, str, str]] = []  # (change_set_id, review_decision_id, change_set_lineage_id)
        for change_set_id, review_decision_id in zip(
            command.competing_change_set_ids, command.competing_review_decision_ids, strict=True
        ):
            stored = await repo.get_decision_by_id(
                review_decision_id, user_id=scope.user_id, project_name=scope.project_name
            )
            if stored is None:
                raise NarrativeDecisionApplicabilityError(f"review decision {review_decision_id!r} does not resolve")
            review_command, _, _ = stored
            if (
                not isinstance(review_command, ChangeSetReviewCommand)
                or review_command.selected_change_set_id != change_set_id
            ):
                raise NarrativeDecisionApplicabilityError(
                    f"review decision {review_decision_id!r} does not select change set {change_set_id!r}"
                )
            resolved.append((change_set_id, review_decision_id, review_command.change_set_lineage_id))

        order = resolved
        if lock:
            order = sorted(
                resolved,
                key=lambda item: head_lock_sort_key(
                    "CHANGE_SET_REVIEW",
                    user_id=scope.user_id,
                    project_name=scope.project_name,
                    logical_key=(command.revision_acceptance_decision_id, item[2]),
                ),
            )
        for _change_set_id, review_decision_id, lineage_id in order:
            get_head = repo.lock_existing_change_set_review_head if lock else repo.get_change_set_review_head
            review_head = await get_head(
                revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                change_set_lineage_id=lineage_id,
                user_id=scope.user_id,
                project_name=scope.project_name,
            )
            if review_head is None or review_head.effective_decision_id != review_decision_id:
                raise NarrativeDecisionApplicabilityError(
                    f"review decision {review_decision_id!r} is not the current effective selection for its lineage"
                )

        change_sets: list[NarrativeChangeSet] = []
        for change_set_id, _review_decision_id, _ in resolved:  # preserve the caller's own order for the subject
            change_set = await repo.get_exact_change_set(
                change_set_id=change_set_id, project_name=scope.project_name, user_id=scope.user_id
            )
            if change_set is None:
                raise NarrativeDecisionApplicabilityError(f"change set {change_set_id!r} does not resolve")
            change_sets.append(change_set)
        return change_sets

    async def is_conflict_resolution_applicable(self, decision_id: str, *, user_id: str, project_name: str) -> bool:
        """A resolution is applicable only while it is the effective resolution for its
        own head *and* every review decision it named remains effective for its own
        lineage. Returns ``False`` — never raises — the moment either
        condition fails, including for an absent or non-conflict-resolution id."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            stored = await repo.get_decision_by_id(decision_id, user_id=user_id, project_name=project_name)
            if stored is None:
                return False
            command, _, _ = stored
            if not isinstance(command, ConflictResolutionCommand):
                return False
            head = await repo.get_conflict_resolution_head(
                revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                conflict_resolution_lineage_id=command.conflict_resolution_lineage_id,
                user_id=user_id,
                project_name=project_name,
            )
            if head is None or head.effective_decision_id != decision_id:
                return False
            for review_decision_id in command.competing_review_decision_ids:
                review_stored = await repo.get_decision_by_id(
                    review_decision_id, user_id=user_id, project_name=project_name
                )
                if review_stored is None:
                    return False
                review_command, _, _ = review_stored
                if not isinstance(review_command, ChangeSetReviewCommand):
                    return False
                review_head = await repo.get_change_set_review_head(
                    revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                    change_set_lineage_id=review_command.change_set_lineage_id,
                    user_id=user_id,
                    project_name=project_name,
                )
                if review_head is None or review_head.effective_decision_id != review_decision_id:
                    return False
            return True

    async def get_current_revision_selection(self, exact_scope: NarrativeWorkScope) -> RevisionAcceptanceHead | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_revision_head(exact_scope)

    async def get_current_change_set_selection(
        self, exact_revision_decision: str, exact_lineage: str, *, user_id: str, project_name: str
    ) -> ChangeSetReviewHead | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_change_set_review_head(
                revision_acceptance_decision_id=exact_revision_decision,
                change_set_lineage_id=exact_lineage,
                user_id=user_id,
                project_name=project_name,
            )

    async def get_current_conflict_resolution(
        self, exact_revision_decision: str, exact_resolution_lineage: str, *, user_id: str, project_name: str
    ) -> ConflictResolutionHead | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_conflict_resolution_head(
                revision_acceptance_decision_id=exact_revision_decision,
                conflict_resolution_lineage_id=exact_resolution_lineage,
                user_id=user_id,
                project_name=project_name,
            )

    async def verify_exact_current_selection(self, decision_id: str, *, user_id: str, project_name: str) -> bool:
        """True iff ``decision_id`` is currently the effective decision for whichever
        head/family it belongs to. Returns ``False`` — never raises — for an absent,
        rejected, or superseded decision."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            stored = await repo.get_decision_by_id(decision_id, user_id=user_id, project_name=project_name)
            if stored is None:
                return False
            command, _, _ = stored
            head = await self._current_head_for(repo, command)
            return head is not None and head.effective_decision_id == decision_id

    async def _current_head_for(
        self, repo: NarrativeLifecycleRepositoryPort, command: NarrativeDecisionCommand
    ) -> _AnyHead | None:
        scope = command.work_scope
        if isinstance(command, RevisionAcceptanceCommand):
            return await repo.get_revision_head(scope)
        if isinstance(command, ChangeSetReviewCommand):
            return await repo.get_change_set_review_head(
                revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                change_set_lineage_id=command.change_set_lineage_id,
                user_id=scope.user_id,
                project_name=scope.project_name,
            )
        assert isinstance(command, ConflictResolutionCommand)
        return await repo.get_conflict_resolution_head(
            revision_acceptance_decision_id=command.revision_acceptance_decision_id,
            conflict_resolution_lineage_id=command.conflict_resolution_lineage_id,
            user_id=scope.user_id,
            project_name=scope.project_name,
        )
