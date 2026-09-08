"""D04 — reusable provider-neutral Gate-1 ProductionReadiness."""

from __future__ import annotations

import pytest

from r2.contracts import (
    ContentBasis,
    ContentBasisType,
    CreativeApprovalStatus,
    ProductionBinding,
    ProductionBindingRole,
    ProductionBindingTarget,
    ReadinessState,
    ResolvedIdentityStatus,
    ResolvedVisualIdentity,
    ShotSpec,
)
from r2.production_intelligence.readiness import ProductionReadinessEvaluator

_SNAPSHOT = "binding-snapshot@7"
_TARGET_VERSION = "SH01@4"


def _basis() -> ContentBasis:
    return ContentBasis(basis_type=ContentBasisType.FACTUAL, basis_version="v1", refs=["research:RP-1"])


def _shot(roles: list[ProductionBindingRole]) -> ShotSpec:
    return ShotSpec(
        id="SH01",
        schema_version="1",
        version=1,
        scene_id="SC01",
        content_basis=_basis(),
        purpose="Reaction",
        target_duration=4.0,
        framing="close-up",
        camera="locked",
        audio_intent="narration",
        required_reference_roles=roles,
        allowed_methods=["GENERATED_VIDEO"],
        quality_tier=2,
        approval_status=CreativeApprovalStatus.APPROVED,
    )


def _binding(role: ProductionBindingRole, bid: str = "B1", target_id: str = "SH01") -> ProductionBinding:
    return ProductionBinding(
        id=bid,
        schema_version="1",
        version=1,
        target_type=ProductionBindingTarget.SHOT,
        target_id=target_id,
        semantic_ref="character:maya",
        production_ref="character-profile:maya-v3",
        role=role,
        asset_refs=["asset:char-master"],
    )


def _resolved(status: ResolvedIdentityStatus = ResolvedIdentityStatus.RESOLVED) -> ResolvedVisualIdentity:
    return ResolvedVisualIdentity(
        target_ref="SH01",
        status=status,
        resolution_policy_version="identity-v1",
    )


def _evaluator() -> ProductionReadinessEvaluator:
    return ProductionReadinessEvaluator()


def _evaluate(shot, bindings, resolved=None, *, optional_roles=()):
    return _evaluator().evaluate(
        shot=shot,
        bindings=bindings,
        resolved_identity=resolved or _resolved(),
        observed_target_version=_TARGET_VERSION,
        binding_snapshot_ref=_SNAPSHOT,
        optional_roles=optional_roles,
    )


def test_missing_required_binding_blocks() -> None:
    readiness = _evaluate(_shot([ProductionBindingRole.CHARACTER]), [])
    assert readiness.state is ReadinessState.BLOCKED
    req = next(r for r in readiness.requirements if r.role is ProductionBindingRole.CHARACTER)
    assert req.required is True
    assert req.status is ReadinessState.BLOCKED
    assert req.reason == "MISSING_REQUIRED_BINDING"


def test_resolved_required_binding_is_ready() -> None:
    readiness = _evaluate(_shot([ProductionBindingRole.CHARACTER]), [_binding(ProductionBindingRole.CHARACTER)])
    assert readiness.state is ReadinessState.READY
    req = readiness.requirements[0]
    assert req.status is ReadinessState.READY
    assert req.resolved_binding == "B1"
    assert req.resolution_source == _SNAPSHOT


def test_optional_unresolved_requirement_is_advisory_not_blocking() -> None:
    readiness = _evaluate(
        _shot([ProductionBindingRole.CHARACTER]),
        [_binding(ProductionBindingRole.CHARACTER)],
        optional_roles=[ProductionBindingRole.STYLE],
    )
    assert readiness.state is ReadinessState.READY
    style = next(r for r in readiness.requirements if r.role is ProductionBindingRole.STYLE)
    assert style.required is False
    assert style.status is ReadinessState.BLOCKED
    assert style.reason == "OPTIONAL_UNRESOLVED"


def test_identity_conflict_blocks_with_reason() -> None:
    readiness = _evaluate(
        _shot([ProductionBindingRole.CHARACTER]),
        [_binding(ProductionBindingRole.CHARACTER)],
        _resolved(ResolvedIdentityStatus.CONFLICTED),
    )
    assert readiness.state is ReadinessState.BLOCKED
    assert readiness.blocked_reason == "IDENTITY_CONFLICT"


def test_is_current_detects_stale_target_version() -> None:
    readiness = _evaluate(_shot([ProductionBindingRole.CHARACTER]), [_binding(ProductionBindingRole.CHARACTER)])
    assert _evaluator().is_current(readiness, target_version=_TARGET_VERSION, binding_snapshot_ref=_SNAPSHOT) is True
    assert _evaluator().is_current(readiness, target_version="SH01@5", binding_snapshot_ref=_SNAPSHOT) is False


def test_is_current_false_when_binding_snapshot_changed() -> None:
    readiness = _evaluate(_shot([ProductionBindingRole.CHARACTER]), [_binding(ProductionBindingRole.CHARACTER)])
    assert (
        _evaluator().is_current(readiness, target_version=_TARGET_VERSION, binding_snapshot_ref="snapshot@9") is False
    )


def test_readiness_records_freshness_anchors() -> None:
    readiness = _evaluate(_shot([ProductionBindingRole.CHARACTER]), [_binding(ProductionBindingRole.CHARACTER)])
    assert readiness.observed_target_version == _TARGET_VERSION
    assert readiness.observed_binding_snapshot_ref == _SNAPSHOT
    assert readiness.evaluation_policy_version


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
