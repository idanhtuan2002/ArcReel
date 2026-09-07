"""D04 Gate 1 — reusable provider-neutral ProductionReadiness.

Gate 1 decides only whether provider-neutral production prerequisites are
satisfied. It never selects a provider/model/tool, never generates a missing
asset, and never mutates Canon. ``ProductionBinding`` stays the owner of
reference-asset association.
"""

from __future__ import annotations

from collections.abc import Sequence

from r2.contracts import (
    ProductionBinding,
    ProductionBindingRole,
    ProductionReadiness,
    ReadinessRequirement,
    ReadinessState,
    ResolvedIdentityStatus,
    ResolvedVisualIdentity,
    ShotSpec,
)

EVALUATION_POLICY_VERSION = "m4-readiness-v1"


class ProductionReadinessEvaluator:
    def evaluate(
        self,
        *,
        shot: ShotSpec,
        bindings: Sequence[ProductionBinding],
        resolved_identity: ResolvedVisualIdentity,
        observed_target_version: str,
        binding_snapshot_ref: str,
        optional_roles: Sequence[ProductionBindingRole] = (),
    ) -> ProductionReadiness:
        requirements: list[ReadinessRequirement] = []

        for role in _dedupe(shot.required_reference_roles):
            match = _match(bindings, role, shot.id)
            if match is not None:
                requirements.append(
                    ReadinessRequirement(
                        requirement_id=f"req:{role.value}",
                        role=role,
                        required=True,
                        status=ReadinessState.READY,
                        resolved_binding=match.id,
                        resolution_source=binding_snapshot_ref,
                    )
                )
            else:
                requirements.append(
                    ReadinessRequirement(
                        requirement_id=f"req:{role.value}",
                        role=role,
                        required=True,
                        status=ReadinessState.BLOCKED,
                        reason="MISSING_REQUIRED_BINDING",
                    )
                )

        for role in _dedupe(optional_roles):
            match = _match(bindings, role, shot.id)
            if match is not None:
                requirements.append(
                    ReadinessRequirement(
                        requirement_id=f"opt:{role.value}",
                        role=role,
                        required=False,
                        status=ReadinessState.READY,
                        resolved_binding=match.id,
                        resolution_source=binding_snapshot_ref,
                    )
                )
            else:
                requirements.append(
                    ReadinessRequirement(
                        requirement_id=f"opt:{role.value}",
                        role=role,
                        required=False,
                        status=ReadinessState.BLOCKED,
                        reason="OPTIONAL_UNRESOLVED",
                    )
                )

        blocked_reason = "IDENTITY_CONFLICT" if resolved_identity.status is ResolvedIdentityStatus.CONFLICTED else None

        # State is derived by ProductionReadiness' own before-validator, so build
        # through model_validate rather than the positional constructor.
        return ProductionReadiness.model_validate(
            {
                "id": f"READY:{shot.id}",
                "target_id": shot.id,
                "requirements": requirements,
                "observed_target_version": observed_target_version,
                "observed_binding_snapshot_ref": binding_snapshot_ref,
                "evaluation_policy_version": EVALUATION_POLICY_VERSION,
                "blocked_reason": blocked_reason,
            }
        )

    @staticmethod
    def is_current(
        readiness: ProductionReadiness,
        *,
        target_version: str,
        binding_snapshot_ref: str,
    ) -> bool:
        return (
            readiness.observed_target_version == target_version
            and readiness.observed_binding_snapshot_ref == binding_snapshot_ref
        )


def _dedupe(roles: Sequence[ProductionBindingRole]) -> list[ProductionBindingRole]:
    seen: dict[ProductionBindingRole, None] = {}
    for role in roles:
        seen.setdefault(role, None)
    return list(seen)


def _match(
    bindings: Sequence[ProductionBinding],
    role: ProductionBindingRole,
    shot_id: str,
) -> ProductionBinding | None:
    for binding in bindings:
        if binding.role is role and binding.target_id == shot_id:
            return binding
    return None
