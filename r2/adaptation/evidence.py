"""``AdaptationEvidenceService`` — the only public append capability for M6 adaptation
proposal evidence (plan Task 6).

Every write is immutable and idempotent: an exact retry (same id/version, byte-identical
model) compares the full stored tuple and performs no write; a mismatched retry fails
closed with no write. This service holds no authority-head mutation capability — its
ports (``r2.adaptation.ports``) expose no head-advancing method, and it imports no Canon
writer, Production approval, provider or M6 authority internal (enforced by
``tests/unit/r2/test_m6_architecture_boundaries.py`` and the matching import-linter
contract).

Branches are the one evidence kind with more than one version per lineage: genesis and
every subsequent version are validated by the pure Task 2 ratchet
(``validate_adaptation_transition``), which this service translates from its embedded
``ADAPTATION_STALE_HEAD`` / ``ADAPTATION_PROFILE_MISMATCH`` messages into the typed
taxonomy. Maps and screenplays bind an exact ``ArtifactVersionRef`` to their parent
branch (and, for screenplays, their parent map); every such reference is resolved and,
wherever a real stored hash exists to compare against, hash-bound — never trusted as a
bare id/version pair (plan global constraint: "every authority input is an exact
immutable ref and content/digest binding"). Branches carry no ``content_hash`` field of
their own, so a branch reference can only be proven to exist, never hash-verified; a
map's own ``content_hash`` is real and is verified wherever a screenplay's
``adaptation_map_ref`` claims it.
"""

from __future__ import annotations

from typing import NoReturn

from r2.adaptation.errors import (
    AdaptationError,
    AdaptationIdentityConflictError,
    AdaptationNotFoundError,
    AdaptationProfileMismatchError,
    AdaptationStaleDependencyError,
    AdaptationStaleHeadError,
)
from r2.adaptation.ports import AdaptationUnitOfWorkFactory
from r2.adaptation.schema_upgrade import validate_adaptation_transition
from r2.contracts.adaptation import AdaptationBranchV2, AdaptationMapV2, ScreenplayArtifactV2


def _raise_typed_transition_error(err: ValueError) -> NoReturn:
    message = str(err)
    if message.startswith("ADAPTATION_STALE_HEAD:"):
        raise AdaptationStaleHeadError(message) from err
    if message.startswith("ADAPTATION_PROFILE_MISMATCH:"):
        raise AdaptationProfileMismatchError(message) from err
    raise AdaptationError(message) from err


class AdaptationEvidenceService:
    def __init__(self, uow_factory: AdaptationUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def create_branch(self, branch: AdaptationBranchV2, *, user_id: str, project_name: str) -> AdaptationBranchV2:
        """Append one branch version. ``branch_id`` is the caller-supplied genesis retry
        identity: reusing it with the same complete tuple at the same version is an
        exact retry, with a different tuple an identity conflict. A version beyond
        genesis must be the exact next sequential version of the same lineage, carrying
        the same profile and root binding as its predecessor (Task 2's ratchet)."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            existing = await repo.get_exact_branch(
                branch_id=branch.branch_id, version=branch.version, project_name=project_name, user_id=user_id
            )
            if existing is not None:
                if existing == branch:
                    return existing
                raise AdaptationIdentityConflictError(
                    f"adaptation branch {branch.branch_id!r} v{branch.version} was already recorded "
                    "with a different tuple"
                )

            previous = await repo.get_latest_branch_version(
                branch_id=branch.branch_id, project_name=project_name, user_id=user_id
            )
            try:
                validate_adaptation_transition(previous, branch)
            except ValueError as err:
                _raise_typed_transition_error(err)

            if branch.parent_branch_id is not None:
                parent = await repo.get_latest_branch_version(
                    branch_id=branch.parent_branch_id, project_name=project_name, user_id=user_id
                )
                if parent is None:
                    raise AdaptationNotFoundError(
                        f"parent branch {branch.parent_branch_id!r} does not resolve in this scope"
                    )

            try:
                await repo.insert_branch(branch, user_id=user_id, project_name=project_name)
            except Exception as err:
                if _is_integrity_error(err):
                    raise AdaptationIdentityConflictError(
                        f"adaptation branch {branch.branch_id!r} v{branch.version} was concurrently recorded"
                    ) from err
                raise
            await uow.commit()
            return branch

    async def append_map(self, map_: AdaptationMapV2, *, user_id: str, project_name: str) -> AdaptationMapV2:
        """Append one map proposal version. Its ``adaptation_branch_ref`` must resolve to
        an already-recorded exact branch version in this scope; branches carry no
        content hash of their own, so only existence is proven."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            existing = await repo.get_exact_map(
                adaptation_map_id=map_.adaptation_map_id,
                version=map_.version,
                project_name=project_name,
                user_id=user_id,
            )
            if existing is not None:
                if existing == map_:
                    return existing
                raise AdaptationIdentityConflictError(
                    f"adaptation map {map_.adaptation_map_id!r} v{map_.version} was already recorded "
                    "with a different tuple"
                )

            branch_ref = map_.adaptation_branch_ref
            branch = await repo.get_exact_branch(
                branch_id=branch_ref.artifact_id, version=branch_ref.version, project_name=project_name, user_id=user_id
            )
            if branch is None:
                raise AdaptationNotFoundError(
                    f"adaptation branch {branch_ref.artifact_id!r} v{branch_ref.version} does not resolve in this scope"
                )

            try:
                await repo.insert_map(map_, user_id=user_id, project_name=project_name)
            except Exception as err:
                if _is_integrity_error(err):
                    raise AdaptationIdentityConflictError(
                        f"adaptation map {map_.adaptation_map_id!r} v{map_.version} was concurrently recorded"
                    ) from err
                raise
            await uow.commit()
            return map_

    async def append_screenplay(
        self, screenplay: ScreenplayArtifactV2, *, user_id: str, project_name: str
    ) -> ScreenplayArtifactV2:
        """Append one screenplay proposal version. Its ``adaptation_branch_ref`` must
        resolve; its ``adaptation_map_ref`` must resolve, its declared content hash must
        match the stored map's real ``content_hash``, and the stored map's own branch
        binding must equal this screenplay's declared branch — a screenplay can never
        propose against a map from a different branch than the one it claims."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            existing = await repo.get_exact_screenplay(
                screenplay_id=screenplay.screenplay_id,
                version=screenplay.version,
                project_name=project_name,
                user_id=user_id,
            )
            if existing is not None:
                if existing == screenplay:
                    return existing
                raise AdaptationIdentityConflictError(
                    f"screenplay {screenplay.screenplay_id!r} v{screenplay.version} was already recorded "
                    "with a different tuple"
                )

            branch_ref = screenplay.adaptation_branch_ref
            branch = await repo.get_exact_branch(
                branch_id=branch_ref.artifact_id, version=branch_ref.version, project_name=project_name, user_id=user_id
            )
            if branch is None:
                raise AdaptationNotFoundError(
                    f"adaptation branch {branch_ref.artifact_id!r} v{branch_ref.version} does not resolve in this scope"
                )

            map_ref = screenplay.adaptation_map_ref
            map_ = await repo.get_exact_map(
                adaptation_map_id=map_ref.artifact_id,
                version=map_ref.version,
                project_name=project_name,
                user_id=user_id,
            )
            if map_ is None:
                raise AdaptationNotFoundError(
                    f"adaptation map {map_ref.artifact_id!r} v{map_ref.version} does not resolve in this scope"
                )
            if map_.content_hash != map_ref.content_hash:
                raise AdaptationStaleDependencyError(
                    f"screenplay {screenplay.screenplay_id!r} declares adaptation_map_ref content hash "
                    f"{map_ref.content_hash!r}, but the stored map's content hash is {map_.content_hash!r}"
                )
            if map_.adaptation_branch_ref != branch_ref:
                raise AdaptationStaleDependencyError(
                    f"screenplay {screenplay.screenplay_id!r} declares branch {branch_ref!r}, which disagrees "
                    f"with its map's own branch binding {map_.adaptation_branch_ref!r}"
                )

            try:
                await repo.insert_screenplay(screenplay, user_id=user_id, project_name=project_name)
            except Exception as err:
                if _is_integrity_error(err):
                    raise AdaptationIdentityConflictError(
                        f"screenplay {screenplay.screenplay_id!r} v{screenplay.version} was concurrently recorded"
                    ) from err
                raise
            await uow.commit()
            return screenplay

    async def get_exact_branch(
        self, *, branch_id: str, version: int, project_name: str, user_id: str
    ) -> AdaptationBranchV2 | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_exact_branch(
                branch_id=branch_id, version=version, project_name=project_name, user_id=user_id
            )

    async def get_exact_map(
        self, *, adaptation_map_id: str, version: int, project_name: str, user_id: str
    ) -> AdaptationMapV2 | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_exact_map(
                adaptation_map_id=adaptation_map_id, version=version, project_name=project_name, user_id=user_id
            )

    async def get_exact_screenplay(
        self, *, screenplay_id: str, version: int, project_name: str, user_id: str
    ) -> ScreenplayArtifactV2 | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_exact_screenplay(
                screenplay_id=screenplay_id, version=version, project_name=project_name, user_id=user_id
            )


def _is_integrity_error(err: Exception) -> bool:
    """True for a raw ``sqlalchemy.exc.IntegrityError`` without importing SQLAlchemy at
    module scope — this pure-adjacent service otherwise depends only on ``r2.adaptation``
    and ``r2.contracts``; the exact class is resolved lazily by name."""
    return type(err).__module__.startswith("sqlalchemy") and type(err).__name__ == "IntegrityError"


__all__ = ["AdaptationEvidenceService"]
