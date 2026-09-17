"""Pure branch-version transition ratchet for M6 adaptation branches (plan Task 2).

``AdaptationBranchV2.version`` is the branch lineage's own sequential version number
(genesis = 1), not a structural schema selector — every branch is always shaped
``r2-adaptation-branch-v2``, there is no legacy v1 branch format to preserve. The
ratchet enforced here is: a branch lineage's version only ever increases by exactly
one, its profile never changes mid-lineage (a profile change is a new branch, not a
new version of an existing one), and its root binding (parent branch, parent Canon
version) is fixed at genesis. A second "genesis" (``previous=None``) submission under
the same ``branch_id`` with a different tuple is rejected the same way any other
non-sequential version would be, since a real prior genesis is never actually absent.
"""

from __future__ import annotations

from r2.contracts.adaptation import AdaptationBranchV2


def validate_adaptation_transition(previous: AdaptationBranchV2 | None, candidate: AdaptationBranchV2) -> None:
    """Raise ``ValueError`` unless ``candidate`` is a legal next version of ``previous``
    (or a legal genesis, when ``previous`` is ``None``) under the same ``branch_id``."""
    if previous is None:
        if candidate.version != 1:
            raise ValueError(
                f"ADAPTATION_STALE_HEAD: genesis branch {candidate.branch_id!r} must start at version 1, "
                f"got {candidate.version}"
            )
        return

    if candidate.branch_id != previous.branch_id:
        raise ValueError(
            "ADAPTATION_STALE_HEAD: validate_adaptation_transition compares two versions of one "
            f"branch lineage; got {previous.branch_id!r} then {candidate.branch_id!r}"
        )
    if candidate.version <= previous.version:
        raise ValueError(
            f"ADAPTATION_STALE_HEAD: branch {candidate.branch_id!r} version must strictly increase "
            f"(previous {previous.version}, candidate {candidate.version}) — a v2-to-v1-shaped downgrade "
            "or a same-ID genesis tuple substitution is never a legal transition"
        )
    if candidate.version != previous.version + 1:
        raise ValueError(
            f"ADAPTATION_STALE_HEAD: branch {candidate.branch_id!r} version must advance by exactly one "
            f"(previous {previous.version}, candidate {candidate.version})"
        )
    if candidate.profile_ref != previous.profile_ref:
        raise ValueError(
            f"ADAPTATION_PROFILE_MISMATCH: branch {candidate.branch_id!r} cannot change its profile "
            "mid-lineage — a profile change requires a new branch_id"
        )
    if candidate.parent_branch_id != previous.parent_branch_id:
        raise ValueError(
            f"ADAPTATION_STALE_HEAD: branch {candidate.branch_id!r} cannot change its parent_branch_id after genesis"
        )
    if candidate.parent_canon_version != previous.parent_canon_version:
        raise ValueError(
            f"ADAPTATION_STALE_HEAD: branch {candidate.branch_id!r} cannot change its parent_canon_version "
            "after genesis"
        )


__all__ = ["validate_adaptation_transition"]
