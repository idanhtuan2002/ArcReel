"""D05 — deterministic scoped + typed VisualIdentity resolution.

The resolver produces a computed ``ResolvedVisualIdentity`` view; it is never a
new authority store and it has no authority to pick a winner between incompatible
effective ``LOCKED`` constraints — that is an explicit conflict for the Human
Showrunner to resolve upstream.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from r2.contracts import (
    IdentityConstraint,
    IdentityScopeType,
    IdentityStrength,
    ResolvedIdentityConstraint,
    ResolvedIdentityStatus,
    ResolvedVisualIdentity,
    VisualIdentityProfile,
)

RESOLUTION_POLICY_VERSION = "m4-identity-resolution-v1"

# Broad -> specific, total order. An EPISODE belongs to a FORMAT, so an
# episode-scoped constraint is the more specific of the two and wins a tie. A
# profile with no scope is treated as the broadest possible base.
_SCOPE_RANK: dict[IdentityScopeType, int] = {
    IdentityScopeType.PROJECT: 1,
    IdentityScopeType.FORMAT: 2,
    IdentityScopeType.EPISODE: 3,
    IdentityScopeType.SEQUENCE: 4,
    IdentityScopeType.SCENE: 5,
    IdentityScopeType.SHOT: 6,
}
_STRENGTH_RANK: dict[IdentityStrength, int] = {
    IdentityStrength.ADVISORY: 0,
    IdentityStrength.PREFERRED: 1,
    IdentityStrength.LOCKED: 2,
}


class _Effective:
    __slots__ = ("locked_values", "scope_ref", "strength", "value")

    def __init__(self, strength: IdentityStrength, value: str, scope_ref: str) -> None:
        self.strength = strength
        self.value = value
        self.scope_ref = scope_ref
        self.locked_values: set[str] = {value} if strength is IdentityStrength.LOCKED else set()


def _scope_rank(scope_type: IdentityScopeType | None) -> int:
    return 0 if scope_type is None else _SCOPE_RANK[scope_type]


def _is_on_ancestry(
    profile: VisualIdentityProfile,
    scope_ancestry: Mapping[IdentityScopeType, str],
) -> bool:
    """A profile contributes only when its scope is one the target descends from.

    Unscoped profiles are the broad base and always apply. A scoped profile
    applies iff the target's ancestor at that scope level is exactly the
    profile's ``scope_ref`` — a profile scoped to a sibling scene/shot/format is
    dropped, never tie-broken on profile id.
    """
    if profile.scope_type is None:
        return True
    return scope_ancestry.get(profile.scope_type) == profile.scope_ref


def _flat_constraints(profile: VisualIdentityProfile) -> list[IdentityConstraint]:
    derived: list[IdentityConstraint] = []
    if profile.hairstyle_lock:
        derived.append(
            IdentityConstraint(
                semantic_key="hairstyle",
                strength=IdentityStrength.LOCKED,
                semantic_value=profile.hairstyle_lock,
            )
        )
    if profile.face_master_ref:
        derived.append(
            IdentityConstraint(
                semantic_key="face_master",
                strength=IdentityStrength.LOCKED,
                semantic_value=profile.face_master_ref,
            )
        )
    return derived


class VisualIdentityResolver:
    def resolve(
        self,
        *,
        target_ref: str,
        scope_ancestry: Mapping[IdentityScopeType, str],
        profiles: Sequence[VisualIdentityProfile],
    ) -> ResolvedVisualIdentity:
        applicable = [p for p in profiles if _is_on_ancestry(p, scope_ancestry)]
        ordered = sorted(applicable, key=lambda p: (_scope_rank(p.scope_type), p.id))

        effective: dict[str, _Effective] = {}
        conflicts: list[str] = []

        for profile in ordered:
            scope_ref = profile.scope_ref or (profile.scope_type.value if profile.scope_type else profile.id)
            for constraint in (*_flat_constraints(profile), *profile.identity_constraints):
                self._apply(constraint, scope_ref, effective, conflicts)

        resolved_constraints = [
            ResolvedIdentityConstraint(
                semantic_key=key,
                effective_strength=eff.strength,
                effective_value=eff.value,
                source_scope_ref=eff.scope_ref,
            )
            for key, eff in sorted(effective.items())
        ]

        status = ResolvedIdentityStatus.CONFLICTED if conflicts else ResolvedIdentityStatus.RESOLVED
        return ResolvedVisualIdentity(
            target_ref=target_ref,
            status=status,
            contributing_profile_refs=sorted(p.id for p in applicable),
            resolved_constraints=resolved_constraints,
            conflicts=sorted(conflicts),
            resolution_policy_version=RESOLUTION_POLICY_VERSION,
            observed_profile_versions=sorted(f"{p.id}@{p.version}" for p in applicable),
        )

    @staticmethod
    def _apply(
        constraint: IdentityConstraint,
        scope_ref: str,
        effective: dict[str, _Effective],
        conflicts: list[str],
    ) -> None:
        key = constraint.semantic_key
        current = effective.get(key)
        if current is None:
            effective[key] = _Effective(constraint.strength, constraint.semantic_value, scope_ref)
            return

        incoming_rank = _STRENGTH_RANK[constraint.strength]
        current_rank = _STRENGTH_RANK[current.strength]

        # Two hard locks that disagree: an explicit conflict, never a silent winner.
        if (
            constraint.strength is IdentityStrength.LOCKED
            and current.locked_values
            and constraint.semantic_value not in current.locked_values
        ):
            current.locked_values.add(constraint.semantic_value)
            conflicts.append(
                f"{key}: LOCKED {sorted(current.locked_values)[0]!r} vs LOCKED {constraint.semantic_value!r}"
            )
            return

        # A weaker or equally weak narrower constraint may not weaken an inherited
        # stronger one.
        if incoming_rank < current_rank:
            return

        # Same strength -> refine value; stronger -> strengthen (and record the lock).
        current.strength = constraint.strength
        current.value = constraint.semantic_value
        current.scope_ref = scope_ref
        if constraint.strength is IdentityStrength.LOCKED:
            current.locked_values.add(constraint.semantic_value)
