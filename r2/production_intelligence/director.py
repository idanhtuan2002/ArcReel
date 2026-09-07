"""D01/D02/D03 — Director routing authority, fallback and normalized DirectorResult.

Routing is a hybrid authority model: a deterministic versioned policy decides the
route, advisory recommendations are evidence only, and an explicit Human override
is sticky (fallback off unless the override opts in). Automatic fallback targets
``ARCREEL_NATIVE`` only — never an automatic OpenMontage<->Take cross-route.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol

from pydantic import ValidationError

from r2.contracts import (
    ContentBasis,
    ContentBasisType,
    DirectorFailure,
    DirectorFailureClass,
    DirectorKind,
    DirectorResult,
    DirectorSuccess,
    Provenance,
    ProvenanceActor,
    RoutingDecision,
)

ROUTING_POLICY_VERSION = "m4-director-routing-v1"
VALIDATION_POLICY_VERSION = "m4-director-validation-v1"

_Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Adapter boundary + failure signals
# --------------------------------------------------------------------------- #


class DirectorAdapter(Protocol):
    director_kind: DirectorKind

    def direct(self, artifact: object) -> object:
        """Accept one already-validated R2 script-like contract at the boundary."""
        ...


class DirectorRouteUnavailable(Exception):
    """The attempted Director cannot service this input (donor down, unsupported)."""


class DirectorTransientError(Exception):
    """A temporary failure (timeout, rate limit); the same Director may be retried."""


class DirectorPartialOutput(Exception):
    """The Director crashed after emitting partial/ambiguous output. Fail closed."""

    def __init__(self, message: str, *, diagnostic_ref: str | None = None) -> None:
        super().__init__(message)
        self.diagnostic_ref = diagnostic_ref


# --------------------------------------------------------------------------- #
# Routing policy
# --------------------------------------------------------------------------- #


def _policy_director(basis_type: ContentBasisType) -> DirectorKind:
    if basis_type is ContentBasisType.FACTUAL:
        return DirectorKind.OPENMONTAGE
    return DirectorKind.TAKE


class DirectorRoutingPolicy:
    def __init__(self, *, clock: _Clock | None = None) -> None:
        self._clock: _Clock = clock or _utc_now

    def decide(
        self,
        *,
        input_profile_ref: str,
        content_basis: ContentBasis,
        advisory_recommendations: Sequence[DirectorKind] = (),
        advisory_reasons: Sequence[str] = (),
        human_override: DirectorKind | None = None,
        override_actor: str | None = None,
        override_reason: str | None = None,
        override_allows_fallback: bool = False,
        decision_id: str | None = None,
    ) -> RoutingDecision:
        policy_director = _policy_director(content_basis.basis_type)
        reasons = list(advisory_reasons) or [
            f"content basis {content_basis.basis_type.value} routes to "
            f"{policy_director.value} under {ROUTING_POLICY_VERSION}"
        ]

        if human_override is not None:
            selected = human_override
            fallback_enabled = bool(override_allows_fallback)
            created_by = ProvenanceActor.HUMAN
        else:
            selected = policy_director
            fallback_enabled = True
            created_by = ProvenanceActor.SYSTEM

        now = self._clock()
        return RoutingDecision(
            routing_decision_id=decision_id or f"RD:{input_profile_ref}",
            routing_policy_version=ROUTING_POLICY_VERSION,
            input_profile_ref=input_profile_ref,
            policy_selected_director=policy_director,
            advisory_recommendations=list(advisory_recommendations),
            advisory_reasons=reasons,
            human_override=human_override,
            override_actor=override_actor,
            override_reason=override_reason,
            selected_director=selected,
            fallback_enabled=fallback_enabled,
            decided_at=now,
            provenance=Provenance(created_by=created_by, created_at=now),
        )


# --------------------------------------------------------------------------- #
# Result normalization
# --------------------------------------------------------------------------- #


class DirectorValidator:
    def __init__(self, *, clock: _Clock | None = None) -> None:
        self._clock: _Clock = clock or _utc_now

    def normalize(
        self,
        *,
        routing: RoutingDecision,
        attempted_director: DirectorKind,
        raw_result: object,
    ) -> DirectorResult:
        if isinstance(raw_result, (DirectorSuccess, DirectorFailure)):
            return raw_result

        scenes = _extract(raw_result, "scenes")
        shots = _extract(raw_result, "shots")
        if not isinstance(scenes, (list, tuple)) or not isinstance(shots, (list, tuple)):
            return self._contract_failure(
                routing,
                attempted_director,
                "director output is not a scenes/shots payload",
            )

        try:
            success = DirectorSuccess(
                routing_decision_ref=routing.routing_decision_id,
                actual_director=attempted_director,
                scenes=list(scenes),
                shots=list(shots),
                validation_summary="contract+semantic validation PASS",
                provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=self._clock()),
            )
        except ValidationError as exc:
            return self._contract_failure(
                routing, attempted_director, f"contract validation failed: {exc.error_count()} error(s)"
            )

        if not success.shots:
            return self._contract_failure(routing, attempted_director, "director produced no shots")
        scene_ids = {scene.id for scene in success.scenes}
        for shot in success.shots:
            if shot.scene_id not in scene_ids:
                return self._contract_failure(
                    routing,
                    attempted_director,
                    f"shot {shot.id} references unknown scene {shot.scene_id}",
                )
        return success

    def _contract_failure(
        self,
        routing: RoutingDecision,
        attempted_director: DirectorKind,
        message: str,
    ) -> DirectorFailure:
        return DirectorFailure(
            routing_decision_ref=routing.routing_decision_id,
            attempted_director=attempted_director,
            failure_class=DirectorFailureClass.CONTRACT_OR_SEMANTIC_FAILURE,
            retryable=False,
            fallback_eligible=False,
            error_code="CONTRACT_OR_SEMANTIC_FAILURE",
            message=message,
        )


def _extract(raw: object, name: str) -> object | None:
    if isinstance(raw, Mapping):
        return raw.get(name)
    return getattr(raw, name, None)


# --------------------------------------------------------------------------- #
# Execution service
# --------------------------------------------------------------------------- #

_FAIL_CLOSED = {
    DirectorFailureClass.CONTRACT_OR_SEMANTIC_FAILURE,
    DirectorFailureClass.PARTIAL_OR_AMBIGUOUS_EXECUTION,
}


class DirectorExecutionService:
    def __init__(self, *, validator: DirectorValidator | None = None, clock: _Clock | None = None) -> None:
        self._clock: _Clock = clock or _utc_now
        self._validator = validator or DirectorValidator(clock=self._clock)

    def execute(
        self,
        *,
        routing: RoutingDecision,
        adapters: Mapping[DirectorKind, DirectorAdapter],
        artifact: object,
        transient_retry_budget: int = 1,
    ) -> DirectorResult:
        primary = routing.selected_director
        result = self._attempt(primary, adapters, artifact, routing, transient_retry_budget)
        if isinstance(result, DirectorSuccess):
            return result
        if result.failure_class in _FAIL_CLOSED:
            return result
        if (
            routing.fallback_enabled
            and primary is not DirectorKind.ARCREEL_NATIVE
            and DirectorKind.ARCREEL_NATIVE in adapters
        ):
            return self._attempt(DirectorKind.ARCREEL_NATIVE, adapters, artifact, routing, transient_retry_budget)
        return result

    def _attempt(
        self,
        kind: DirectorKind,
        adapters: Mapping[DirectorKind, DirectorAdapter],
        artifact: object,
        routing: RoutingDecision,
        transient_retry_budget: int,
    ) -> DirectorResult:
        adapter = adapters.get(kind)
        if adapter is None:
            return self._failure(
                routing,
                kind,
                DirectorFailureClass.ROUTE_UNAVAILABLE,
                retryable=False,
                fallback_eligible=routing.fallback_enabled,
                error_code="NO_ADAPTER",
                message=f"no adapter registered for {kind.value}",
            )

        attempts = 0
        while True:
            attempts += 1
            try:
                raw = adapter.direct(artifact)
            except DirectorRouteUnavailable as exc:
                return self._failure(
                    routing,
                    kind,
                    DirectorFailureClass.ROUTE_UNAVAILABLE,
                    retryable=False,
                    fallback_eligible=routing.fallback_enabled,
                    error_code="ROUTE_UNAVAILABLE",
                    message=str(exc) or "route unavailable",
                )
            except DirectorPartialOutput as exc:
                return self._failure(
                    routing,
                    kind,
                    DirectorFailureClass.PARTIAL_OR_AMBIGUOUS_EXECUTION,
                    retryable=False,
                    fallback_eligible=False,
                    error_code="PARTIAL_OUTPUT",
                    message=str(exc) or "partial or ambiguous director output",
                    partial_output_diagnostic_ref=exc.diagnostic_ref,
                )
            except DirectorTransientError as exc:
                if attempts <= transient_retry_budget:
                    continue
                return self._failure(
                    routing,
                    kind,
                    DirectorFailureClass.TRANSIENT_EXECUTION_FAILURE,
                    retryable=True,
                    fallback_eligible=routing.fallback_enabled,
                    error_code="TRANSIENT_EXECUTION_FAILURE",
                    message=str(exc) or "transient director failure",
                )
            return self._validator.normalize(routing=routing, attempted_director=kind, raw_result=raw)

    @staticmethod
    def _failure(
        routing: RoutingDecision,
        attempted_director: DirectorKind,
        failure_class: DirectorFailureClass,
        *,
        retryable: bool,
        fallback_eligible: bool,
        error_code: str,
        message: str,
        partial_output_diagnostic_ref: str | None = None,
    ) -> DirectorFailure:
        return DirectorFailure(
            routing_decision_ref=routing.routing_decision_id,
            attempted_director=attempted_director,
            failure_class=failure_class,
            retryable=retryable,
            fallback_eligible=fallback_eligible,
            error_code=error_code,
            message=message,
            partial_output_diagnostic_ref=partial_output_diagnostic_ref,
        )


# --------------------------------------------------------------------------- #
# M3 donor wrapped behind the generic seam (no M3 modification)
# --------------------------------------------------------------------------- #


class _ScriptDirectorBackend(Protocol):
    def direct(self, artifact: object) -> object: ...


class OpenMontageDirectorAdapter:
    """Wrap an M3 ``GoldenAOpenMontageAdapter``-shaped backend as a DirectorAdapter."""

    director_kind: DirectorKind = DirectorKind.OPENMONTAGE

    def __init__(self, backend: _ScriptDirectorBackend) -> None:
        self._backend = backend

    def direct(self, artifact: object) -> object:
        return self._backend.direct(artifact)
