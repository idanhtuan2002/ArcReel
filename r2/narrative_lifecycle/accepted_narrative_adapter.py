"""M5C's concrete read adapter behind M5B's ``AcceptedNarrativeReader`` protocol.

See spec §8.4 (workflow services and ports) and the Task 25 brief for the full
rationale. ``AcceptedNarrativeReader`` and ``AcceptedNarrativeRecord``
(``r2.narrative_context.ports``) are both ``typing.Protocol`` classes — structural
typing, not nominal — so this module never imports either one: it defines its own
concrete record type and reader class that structurally satisfy them. That keeps this
module clear of ``r2.narrative_context``, which every file under
``r2/narrative_lifecycle/`` is forbidden from importing
(``tests/unit/r2/test_m5c_architecture_boundaries.py``).

``NarrativeSourceDescriptor`` is a real, non-Protocol contract, but it lives in
``r2.contracts.narrative_context`` (the contracts layer) — a different module from the
forbidden ``r2.narrative_context`` business-logic package, so importing it here is
allowed and is exactly the M5C-supplied contract the plan's Base Modules table names.

An ``accepted_narrative_ref`` is a revision-acceptance decision ID, never a revision ID,
prose hash, or mutable head ID. ``get_exact`` never raises for a missing, rejected,
superseded, corrupt, or cross-scope reference: every such case returns ``None``, the
existing indistinguishable not-found result M5B raises as ``NarrativeSourceMetadataError``.
This adapter never raises that error itself and never distinguishes the reason. Historical
audit uses the separate replay port (spec §10.2); this adapter is never injectable as
that port.
"""

from __future__ import annotations

from dataclasses import dataclass

from r2.contracts.narrative_context import (
    ContextDescriptorBasis,
    DescriptorAuthorityClass,
    DescriptorVisibilityPolicy,
    NarrativeSourceDescriptor,
    compute_descriptor_ref,
    compute_source_content_hash,
)
from r2.contracts.narrative_lifecycle import NarrativeRevision, RevisionAcceptanceCommand
from r2.narrative_lifecycle.ports import NarrativeLifecycleUnitOfWorkFactory

_PLACEHOLDER_DESCRIPTOR_REF = "nsd:pending"


@dataclass(frozen=True)
class _AcceptedNarrativeRecord:
    """Structurally satisfies ``r2.narrative_context.ports.AcceptedNarrativeRecord``."""

    accepted_narrative_ref: str
    content: str
    descriptor: NarrativeSourceDescriptor


class AcceptedNarrativeAdapter:
    """Structurally satisfies ``r2.narrative_context.ports.AcceptedNarrativeReader``.

    For a normal M5B context compilation, ``get_exact`` resolves the exact decision and
    revision, verifies the decision is the current effective acceptance for its stable
    work scope, and returns prose plus an authority descriptor binding the exact Canon
    and Plan bases. It never emits ``RECENT_ACCEPTED`` content itself — that channel
    label belongs to M5B's compiler, not this adapter.
    """

    def __init__(self, uow_factory: NarrativeLifecycleUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get_exact(
        self, *, accepted_narrative_ref: str, project_name: str, user_id: str
    ) -> _AcceptedNarrativeRecord | None:
        async with self._uow_factory() as uow:
            repo = uow.repository
            stored = await repo.get_decision_by_id(accepted_narrative_ref, user_id=user_id, project_name=project_name)
            if stored is None:
                return None
            command, _authorization, _decision_generation = stored
            if not isinstance(command, RevisionAcceptanceCommand):
                return None
            scope = command.work_scope
            if scope.user_id != user_id or scope.project_name != project_name:
                return None

            head = await repo.get_revision_head(scope)
            if head is None or head.effective_decision_id != accepted_narrative_ref:
                return None

            revision = await repo.get_exact_revision(
                revision_id=command.selected_revision_id, project_name=project_name, user_id=user_id
            )
            if revision is None or revision.work_scope != scope:
                return None

            return _build_record(accepted_narrative_ref, revision)


def _build_record(accepted_narrative_ref: str, revision: NarrativeRevision) -> _AcceptedNarrativeRecord:
    """Build the authority descriptor binding the exact Canon and Plan bases the accepted
    revision was created against. ``content_hash`` is recomputed with
    ``compute_source_content_hash`` (not copied from ``revision.content_hash``): the two
    hash domains normalize identically but use different prefixes (``pch:`` vs.
    ``nsc:`` — locked together by ``tests/unit/r2/narrative_lifecycle/test_lifecycle_hashing.py``),
    and M5B's compiler recomputes ``compute_source_content_hash(prose)`` to compare
    against ``descriptor.content_hash`` byte-for-byte."""
    scope = revision.work_scope
    source_ref = revision.revision_id
    source_basis_refs = sorted({revision.revision_id, accepted_narrative_ref})
    canon_basis = ContextDescriptorBasis(
        branch_id=scope.canon_branch_id, canon_version_id=revision.base_canon_version_id
    )
    plan_basis = ContextDescriptorBasis(plan_id=scope.plan_id, plan_version=revision.plan_version)
    content_hash = compute_source_content_hash(revision.normalized_content)

    # Two-pass construction (the established pattern for this contract, e.g.
    # tests/unit/r2/contracts/test_narrative_context.py): descriptor_ref is content-
    # addressed over every other field, so build an unvalidated draft first, compute the
    # real ref against it, then construct the real, validated descriptor.
    draft = NarrativeSourceDescriptor.model_construct(
        descriptor_ref=_PLACEHOLDER_DESCRIPTOR_REF,
        source_ref=source_ref,
        user_id=scope.user_id,
        project_name=scope.project_name,
        authority_class=DescriptorAuthorityClass.ACCEPTED_NARRATIVE,
        source_basis_refs=source_basis_refs,
        canon_basis=canon_basis,
        plan_basis=plan_basis,
        effective_from=None,
        effective_until=None,
        visibility_policy=DescriptorVisibilityPolicy.AUTHOR_ONLY,
        content_hash=content_hash,
    )
    descriptor = NarrativeSourceDescriptor(
        descriptor_ref=compute_descriptor_ref(draft),
        source_ref=source_ref,
        user_id=scope.user_id,
        project_name=scope.project_name,
        authority_class=DescriptorAuthorityClass.ACCEPTED_NARRATIVE,
        source_basis_refs=source_basis_refs,
        canon_basis=canon_basis,
        plan_basis=plan_basis,
        effective_from=None,
        effective_until=None,
        visibility_policy=DescriptorVisibilityPolicy.AUTHOR_ONLY,
        content_hash=content_hash,
    )
    return _AcceptedNarrativeRecord(
        accepted_narrative_ref=accepted_narrative_ref,
        content=revision.normalized_content,
        descriptor=descriptor,
    )
