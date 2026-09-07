"""D06 — constrained policy Method Router.

Method authority precedes provider/model/tool selection. No provider identity is
an input here. The router applies a hard eligibility filter, an authoritative
priority, then a deterministic rank, and emits a ``MethodDecision``.
"""

from __future__ import annotations

from dataclasses import dataclass

from r2.contracts import (
    MethodDecision,
    ProductionMethod,
    ProductionReadiness,
    ReadinessState,
    RejectedMethod,
    ResolvedIdentityStatus,
    ResolvedVisualIdentity,
)

METHOD_ROUTER_POLICY_VERSION = "m4-method-router-v1"

# Reuse-first, then library, then source-authentic capture, then deterministic,
# then explicit assembly, then generation (image before video).
_DEFAULT_PRIORITY: tuple[ProductionMethod, ...] = (
    ProductionMethod.REUSE,
    ProductionMethod.STOCK,
    ProductionMethod.SCREEN_CAPTURE,
    ProductionMethod.DETERMINISTIC,
    ProductionMethod.COMPOSITE,
    ProductionMethod.GENERATED_IMAGE,
    ProductionMethod.GENERATED_VIDEO,
)
# When actual UI/person/event/evidence is required, only genuinely source-real
# methods can satisfy the intent.
_SOURCE_AUTHENTIC_PRIORITY: tuple[ProductionMethod, ...] = (
    ProductionMethod.SCREEN_CAPTURE,
    ProductionMethod.STOCK,
)

_COST_CLASS: dict[ProductionMethod, str] = {
    ProductionMethod.REUSE: "LOW",
    ProductionMethod.STOCK: "LOW",
    ProductionMethod.SCREEN_CAPTURE: "LOW",
    ProductionMethod.DETERMINISTIC: "LOW",
    ProductionMethod.COMPOSITE: "MEDIUM",
    ProductionMethod.GENERATED_IMAGE: "MEDIUM",
    ProductionMethod.GENERATED_VIDEO: "HIGH",
}


class MethodRoutingBlocked(RuntimeError):
    """Gate 1 did not pass (readiness BLOCKED or identity CONFLICTED); the router
    is not authoritative to continue."""


@dataclass(frozen=True)
class MethodRoutingContext:
    target_ref: str
    allowed_methods: tuple[ProductionMethod, ...]
    readiness: ProductionReadiness
    identity: ResolvedVisualIdentity
    source_authenticity_required: bool
    reusable_asset_current: bool
    deterministic_equivalent_available: bool
    policy_version: str = METHOD_ROUTER_POLICY_VERSION


class MethodRouter:
    def decide(self, context: MethodRoutingContext) -> MethodDecision:
        if context.readiness.state is not ReadinessState.READY:
            raise MethodRoutingBlocked(f"readiness state is {context.readiness.state.value}")
        if context.identity.status is ResolvedIdentityStatus.CONFLICTED:
            raise MethodRoutingBlocked("resolved visual identity is CONFLICTED")

        eligible, rejected = self._filter(context)
        priority = _SOURCE_AUTHENTIC_PRIORITY if context.source_authenticity_required else _DEFAULT_PRIORITY
        ranked = [method for method in priority if method in eligible]
        if not ranked:
            raise MethodRoutingBlocked("no allowed method satisfies the hard policy")

        selected = ranked[0]
        return MethodDecision(
            id=f"MD:{context.target_ref}",
            target_ref=context.target_ref,
            method=selected,
            rationale=self._rationale(selected, context),
            cost_class=_COST_CLASS[selected],
            quality_tier=0,
            fallback_methods=ranked[1:],
            method_policy_version=context.policy_version,
            eligible_methods=ranked,
            rejected_methods=rejected,
            decision_factors=self._factors(context),
        )

    @staticmethod
    def _filter(
        context: MethodRoutingContext,
    ) -> tuple[list[ProductionMethod], list[RejectedMethod]]:
        eligible: list[ProductionMethod] = []
        rejected: list[RejectedMethod] = []
        for method in context.allowed_methods:
            reasons = _ineligibility_reasons(method, context)
            if reasons:
                rejected.append(RejectedMethod(method=method, reason_codes=reasons))
            else:
                eligible.append(method)
        return eligible, rejected

    @staticmethod
    def _rationale(method: ProductionMethod, context: MethodRoutingContext) -> str:
        if method is ProductionMethod.REUSE:
            return "current approved compatible asset is reusable"
        if method is ProductionMethod.SCREEN_CAPTURE:
            return "source authenticity required; capture is the source-real method"
        if method is ProductionMethod.STOCK:
            return "library footage satisfies the intent before generation"
        if method is ProductionMethod.DETERMINISTIC:
            return "a deterministic representation satisfies the intent before generation"
        if method is ProductionMethod.COMPOSITE:
            return "explicit assembly of constituent treatments"
        return f"{method.value} is the highest-priority eligible method for this shot"

    @staticmethod
    def _factors(context: MethodRoutingContext) -> list[str]:
        factors = ["method-before-provider", "reuse-before-generation", "deterministic-before-generation"]
        if context.source_authenticity_required:
            factors.append("source-authenticity-required")
        return factors


def _ineligibility_reasons(method: ProductionMethod, context: MethodRoutingContext) -> list[str]:
    reasons: list[str] = []
    if context.source_authenticity_required and method not in _SOURCE_AUTHENTIC_PRIORITY:
        reasons.append("SOURCE_AUTHENTICITY_REQUIRED")
    if method is ProductionMethod.REUSE and not context.reusable_asset_current:
        reasons.append("NO_CURRENT_REUSABLE_ASSET")
    if method is ProductionMethod.DETERMINISTIC and not context.deterministic_equivalent_available:
        reasons.append("NO_DETERMINISTIC_EQUIVALENT")
    return reasons
