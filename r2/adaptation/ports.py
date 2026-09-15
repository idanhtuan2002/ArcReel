"""Structural ports for the M6 adaptation evidence and authority layers (plan Tasks 6-7).

Pure ``Protocol`` seams — import only adaptation contracts, never a concrete
repository, session, ORM row, clock or provider. The concrete adapter
(``lib.db.repositories.adaptation.AdaptationRepository``) implements the combined
shape; ``AdaptationEvidenceService`` and ``AdaptationAuthorityService`` each depend
only on the narrower protocol they actually use.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

from r2.contracts.adaptation import (
    AdaptationAuthorityFamily,
    AdaptationBranchV2,
    AdaptationDecision,
    AdaptationDecisionAction,
    AdaptationDecisionAuthorization,
    AdaptationHead,
    AdaptationMapV2,
    ScreenplayArtifactV2,
)


@runtime_checkable
class AdaptationEvidenceRepositoryPort(Protocol):
    """Scoped, transaction-bound evidence adapter: exact reads and append-only writes.

    No method mutates an authority head. The adapter never commits, rolls back, or
    constructs a session — the unit of work owns that lifecycle.
    """

    async def get_exact_branch(
        self, *, branch_id: str, version: int, project_name: str, user_id: str
    ) -> AdaptationBranchV2 | None: ...

    async def get_latest_branch_version(
        self, *, branch_id: str, project_name: str, user_id: str
    ) -> AdaptationBranchV2 | None: ...

    async def insert_branch(self, branch: AdaptationBranchV2, *, user_id: str, project_name: str) -> None: ...

    async def get_exact_map(
        self, *, adaptation_map_id: str, version: int, project_name: str, user_id: str
    ) -> AdaptationMapV2 | None: ...

    async def insert_map(self, map_: AdaptationMapV2, *, user_id: str, project_name: str) -> None: ...

    async def get_exact_screenplay(
        self, *, screenplay_id: str, version: int, project_name: str, user_id: str
    ) -> ScreenplayArtifactV2 | None: ...

    async def insert_screenplay(self, screenplay: ScreenplayArtifactV2, *, user_id: str, project_name: str) -> None: ...


@runtime_checkable
class AdaptationAuthorityRepositoryPort(Protocol):
    """Scoped, transaction-bound authority adapter: the append-only decision log plus
    its one mutable, rebuildable head projection per ``(family, head_key)``.

    ``get_decision_by_id`` takes no ``family``/``head_key`` — ``decision_id`` is a
    single global identity registry across every family in one ``(user_id,
    project_name)`` scope, exactly like M5C's own decision-identity registry.
    ``prepare_or_lock_head`` returns ``None`` only for a head that has never recorded a
    decision (``AdaptationHead.generation`` is never less than 1, so "no decisions yet"
    cannot be represented by a real instance); a non-``None`` return is always locked
    for the remainder of the caller's transaction. The adapter never commits, rolls
    back, or constructs a session, and never repairs a disagreement it finds.
    """

    async def get_decision_by_id(
        self, *, user_id: str, project_name: str, decision_id: str
    ) -> AdaptationDecision | None: ...

    async def prepare_or_lock_head(
        self, *, user_id: str, project_name: str, family: AdaptationAuthorityFamily, head_key: str
    ) -> AdaptationHead | None: ...

    async def list_decisions_for_locked_head(
        self, *, user_id: str, project_name: str, family: AdaptationAuthorityFamily, head_key: str
    ) -> Sequence[AdaptationDecision]: ...

    async def append_decision_and_advance_head(
        self, decision: AdaptationDecision, *, expected_generation: int
    ) -> None: ...


@runtime_checkable
class AdaptationShowrunnerAuthorityPort(Protocol):
    """The sole source of Human Showrunner decision authority for M6. Its only source
    of truth is an explicit project-scoped ``HUMAN_SHOWRUNNER`` grant; a concrete
    adapter denies by default (raises ``AdaptationAuthorityDeniedError``) until that
    grant is proven. Called exactly once per ``decide_*`` invocation — genesis and
    exact retry alike, unlike M5C's split initial/retry authorization — because
    ``command_identity_hash`` alone (not a stored-vs-fresh distinction) is what the
    minted ``AdaptationDecisionAuthorization`` binds itself to.
    """

    async def authorize(
        self, *, authenticated_principal: str, action: AdaptationDecisionAction, command_identity_hash: str
    ) -> AdaptationDecisionAuthorization: ...


@runtime_checkable
class AdaptationRepositoryPort(AdaptationEvidenceRepositoryPort, AdaptationAuthorityRepositoryPort, Protocol):
    """Every method the concrete ``AdaptationRepository`` implements. ``evidence.py``
    and ``authority.py`` each depend on their own narrower protocol above; only the
    unit of work needs the combined shape."""


@runtime_checkable
class AdaptationUnitOfWork(Protocol):
    repository: AdaptationRepositoryPort

    async def __aenter__(self) -> AdaptationUnitOfWork: ...

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    async def commit(self) -> None: ...


AdaptationUnitOfWorkFactory = Callable[[], AdaptationUnitOfWork]

__all__ = [
    "AdaptationAuthorityRepositoryPort",
    "AdaptationEvidenceRepositoryPort",
    "AdaptationRepositoryPort",
    "AdaptationShowrunnerAuthorityPort",
    "AdaptationUnitOfWork",
    "AdaptationUnitOfWorkFactory",
]
