"""D06 — constrained policy Method Router (method before provider)."""

from __future__ import annotations

import pytest

from r2.contracts import (
    ProductionMethod,
    ReadinessState,
    ResolvedIdentityStatus,
    ResolvedVisualIdentity,
)
from r2.production_intelligence.method_router import (
    MethodRouter,
    MethodRoutingBlocked,
    MethodRoutingContext,
)

_POLICY = "m4-method-router-v1"


def _readiness(state: ReadinessState = ReadinessState.READY):
    payload = {
        "id": "READY:SH01",
        "target_id": "SH01",
        "requirements": [],
    }
    if state is ReadinessState.BLOCKED:
        payload["blocked_reason"] = "MISSING_REQUIRED_BINDING"
    from r2.contracts import ProductionReadiness

    return ProductionReadiness.model_validate(payload)


def _identity(status: ResolvedIdentityStatus = ResolvedIdentityStatus.RESOLVED) -> ResolvedVisualIdentity:
    return ResolvedVisualIdentity(target_ref="SH01", status=status, resolution_policy_version="identity-v1")


def _ctx(
    allowed: tuple[ProductionMethod, ...],
    *,
    source_authenticity_required: bool = False,
    reusable_asset_current: bool = False,
    deterministic_equivalent_available: bool = False,
    readiness_state: ReadinessState = ReadinessState.READY,
) -> MethodRoutingContext:
    return MethodRoutingContext(
        target_ref="SH01",
        allowed_methods=allowed,
        readiness=_readiness(readiness_state),
        identity=_identity(),
        source_authenticity_required=source_authenticity_required,
        reusable_asset_current=reusable_asset_current,
        deterministic_equivalent_available=deterministic_equivalent_available,
        policy_version=_POLICY,
    )


def _router() -> MethodRouter:
    return MethodRouter()


def test_current_reusable_asset_is_selected_first() -> None:
    decision = _router().decide(
        _ctx((ProductionMethod.REUSE, ProductionMethod.GENERATED_VIDEO), reusable_asset_current=True)
    )
    assert decision.method is ProductionMethod.REUSE
    assert ProductionMethod.REUSE in decision.eligible_methods
    assert decision.method_policy_version == _POLICY


def test_source_authenticity_selects_capture_over_synthetic_generation() -> None:
    decision = _router().decide(
        _ctx(
            (ProductionMethod.SCREEN_CAPTURE, ProductionMethod.GENERATED_IMAGE, ProductionMethod.REUSE),
            source_authenticity_required=True,
            reusable_asset_current=True,
        )
    )
    assert decision.method is ProductionMethod.SCREEN_CAPTURE
    assert ProductionMethod.GENERATED_IMAGE not in decision.eligible_methods


def test_deterministic_precedes_generation_when_equivalent_available() -> None:
    decision = _router().decide(
        _ctx(
            (ProductionMethod.DETERMINISTIC, ProductionMethod.GENERATED_IMAGE),
            deterministic_equivalent_available=True,
        )
    )
    assert decision.method is ProductionMethod.DETERMINISTIC


def test_generation_availability_alone_does_not_force_generation() -> None:
    decision = _router().decide(
        _ctx((ProductionMethod.REUSE, ProductionMethod.GENERATED_IMAGE), reusable_asset_current=True)
    )
    assert decision.method is ProductionMethod.REUSE


def test_composite_is_an_explicit_method_not_a_generated_video_fallback() -> None:
    decision = _router().decide(_ctx((ProductionMethod.COMPOSITE,)))
    assert decision.method is ProductionMethod.COMPOSITE
    assert "fallback" not in decision.rationale.lower()


def test_context_does_not_accept_provider_identity() -> None:
    # The context is a fixed frozen dataclass: there is structurally no place to
    # smuggle provider/model identity into method routing.
    assert "provider" not in MethodRoutingContext.__dataclass_fields__
    assert "model" not in MethodRoutingContext.__dataclass_fields__
    smuggle = {"provider": "seedance"}
    with pytest.raises(TypeError):
        MethodRoutingContext(
            target_ref="SH01",
            allowed_methods=(ProductionMethod.REUSE,),
            readiness=_readiness(),
            identity=_identity(),
            source_authenticity_required=False,
            reusable_asset_current=True,
            deterministic_equivalent_available=False,
            policy_version=_POLICY,
            **smuggle,
        )


def test_method_decision_is_provider_neutral() -> None:
    decision = _router().decide(_ctx((ProductionMethod.GENERATED_VIDEO,)))
    assert set(decision.model_dump(mode="json")).isdisjoint({"provider", "model", "endpoint", "payload"})


def test_blocked_readiness_is_not_routable() -> None:
    with pytest.raises(MethodRoutingBlocked):
        _router().decide(_ctx((ProductionMethod.REUSE,), readiness_state=ReadinessState.BLOCKED))


def test_conflicted_identity_is_not_routable() -> None:
    ctx = MethodRoutingContext(
        target_ref="SH01",
        allowed_methods=(ProductionMethod.REUSE,),
        readiness=_readiness(),
        identity=_identity(ResolvedIdentityStatus.CONFLICTED),
        source_authenticity_required=False,
        reusable_asset_current=True,
        deterministic_equivalent_available=False,
        policy_version=_POLICY,
    )
    with pytest.raises(MethodRoutingBlocked):
        _router().decide(ctx)


def test_rejected_methods_explain_why_they_are_ineligible() -> None:
    decision = _router().decide(
        _ctx((ProductionMethod.REUSE, ProductionMethod.DETERMINISTIC, ProductionMethod.GENERATED_IMAGE))
    )
    assert decision.method is ProductionMethod.GENERATED_IMAGE
    rejected = {r.method: r.reason_codes for r in decision.rejected_methods}
    assert "NO_CURRENT_REUSABLE_ASSET" in rejected[ProductionMethod.REUSE]
    assert "NO_DETERMINISTIC_EQUIVALENT" in rejected[ProductionMethod.DETERMINISTIC]


def test_decision_is_deterministic() -> None:
    ctx = _ctx((ProductionMethod.REUSE, ProductionMethod.DETERMINISTIC), deterministic_equivalent_available=True)
    a = _router().decide(ctx)
    b = _router().decide(ctx)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
