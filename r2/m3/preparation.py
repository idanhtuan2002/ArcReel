from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from r2.contracts import ShotSpec
from r2.contracts.enums import (
    ProductionBindingRole,
    ProductionBindingTarget,
    ProductionMethod,
    ReadinessState,
)
from r2.contracts.preparation import (
    ProductionBinding,
    ProductionReadiness,
    ReadinessRequirement,
)


@dataclass(frozen=True)
class GoldenAMethodAssignment:
    target_ref: str
    method: ProductionMethod
    rationale: str


@dataclass(frozen=True)
class GoldenAPreparedShot:
    shot: ShotSpec
    bindings: tuple[ProductionBinding, ...]
    readiness: ProductionReadiness
    method: GoldenAMethodAssignment

    @property
    def executable(self) -> bool:
        return self.readiness.state is ReadinessState.READY


class GoldenAProductionPreparation:
    def prepare(
        self,
        shots: Sequence[ShotSpec],
        *,
        reused_asset_ref: str | None,
    ) -> tuple[GoldenAPreparedShot, ...]:
        result: list[GoldenAPreparedShot] = []

        for shot in shots:
            method = ProductionMethod.REUSE if shot.id == "SH01" else ProductionMethod.DETERMINISTIC
            if method not in shot.allowed_methods:
                raise ValueError(f"Golden A method {method.value} is not allowed by {shot.id}")

            bindings: tuple[ProductionBinding, ...] = ()
            requirements: list[ReadinessRequirement] = []
            state = ReadinessState.READY

            if method is ProductionMethod.REUSE:
                if reused_asset_ref:
                    binding = ProductionBinding(
                        id=f"PB-{shot.id}-SOURCE",
                        schema_version=shot.schema_version,
                        version=1,
                        target_type=ProductionBindingTarget.SHOT,
                        target_id=shot.id,
                        semantic_ref=f"shot:{shot.id}:source",
                        production_ref=reused_asset_ref,
                        role=ProductionBindingRole.SOURCE_FOOTAGE,
                        asset_refs=[reused_asset_ref],
                        variant_ref=None,
                        state_ref=None,
                    )
                    bindings = (binding,)
                    requirements.append(
                        ReadinessRequirement(
                            requirement_id=f"REQ-{shot.id}-SOURCE",
                            role=ProductionBindingRole.SOURCE_FOOTAGE,
                            required=True,
                            status=ReadinessState.READY,
                            resolved_binding=binding.id,
                            reason=None,
                        )
                    )
                else:
                    state = ReadinessState.BLOCKED
                    requirements.append(
                        ReadinessRequirement(
                            requirement_id=f"REQ-{shot.id}-SOURCE",
                            role=ProductionBindingRole.SOURCE_FOOTAGE,
                            required=True,
                            status=ReadinessState.BLOCKED,
                            resolved_binding=None,
                            reason="required REUSE source asset is unresolved",
                        )
                    )

            readiness = ProductionReadiness(
                id=f"PR-{shot.id}",
                target_id=shot.id,
                state=state,
                requirements=requirements,
            )
            assignment = GoldenAMethodAssignment(
                target_ref=shot.id,
                method=method,
                rationale=(
                    "Use the checked-in approved Golden A source asset."
                    if method is ProductionMethod.REUSE
                    else "Generate deterministic local explanatory media."
                ),
            )
            result.append(
                GoldenAPreparedShot(
                    shot=shot,
                    bindings=bindings,
                    readiness=readiness,
                    method=assignment,
                )
            )

        return tuple(result)
