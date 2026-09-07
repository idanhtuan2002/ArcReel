"""D01/D02/D03 — Director routing authority, fallback, and normalized result."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import (
    ContentBasis,
    ContentBasisType,
    DirectorFailure,
    DirectorFailureClass,
    DirectorKind,
    DirectorSuccess,
    Provenance,
    ProvenanceActor,
)
from r2.m3.director import FixtureOpenMontageBackend, GoldenAOpenMontageAdapter
from r2.m3.factual_fixture import load_golden_a_factual_bundle
from r2.production_intelligence.director import (
    DirectorExecutionService,
    DirectorPartialOutput,
    DirectorRouteUnavailable,
    DirectorRoutingPolicy,
    DirectorTransientError,
    DirectorValidator,
    OpenMontageDirectorAdapter,
)

FORBIDDEN_PROVIDER_FIELDS = {"provider", "model", "endpoint", "payload", "provider_job_id"}
_CLOCK = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _factual_basis() -> ContentBasis:
    return ContentBasis(basis_type=ContentBasisType.FACTUAL, basis_version="v1", refs=["research:RP-1"])


def _narrative_basis() -> ContentBasis:
    return ContentBasis(basis_type=ContentBasisType.NARRATIVE, basis_version="canon-v1", refs=["event:1"])


def _policy() -> DirectorRoutingPolicy:
    return DirectorRoutingPolicy(clock=lambda: _CLOCK)


def _service() -> DirectorExecutionService:
    return DirectorExecutionService(validator=DirectorValidator(clock=lambda: _CLOCK), clock=lambda: _CLOCK)


class _FakeRaw:
    def __init__(self, scenes, shots):
        self.scenes = scenes
        self.shots = shots


class _FakeAdapter:
    def __init__(self, kind: DirectorKind, *, result=None, error=None, error_times: int | None = None):
        self.director_kind = kind
        self._result = result
        self._error = error
        self._error_times = error_times
        self.calls = 0

    def direct(self, artifact):
        self.calls += 1
        if self._error is not None and (self._error_times is None or self.calls <= self._error_times):
            raise self._error
        return self._result


def _golden_raw():
    return GoldenAOpenMontageAdapter(FixtureOpenMontageBackend()).direct(load_golden_a_factual_bundle().script)


# --------------------------------------------------------------------------- #
# Step 1 — routing
# --------------------------------------------------------------------------- #


def test_factual_content_routes_to_openmontage() -> None:
    decision = _policy().decide(input_profile_ref="profile:doc", content_basis=_factual_basis())
    assert decision.policy_selected_director is DirectorKind.OPENMONTAGE
    assert decision.selected_director is DirectorKind.OPENMONTAGE
    assert decision.fallback_enabled is True
    assert decision.routing_policy_version
    assert decision.provenance.created_at == _CLOCK


def test_narrative_content_routes_to_take() -> None:
    decision = _policy().decide(input_profile_ref="profile:drama", content_basis=_narrative_basis())
    assert decision.policy_selected_director is DirectorKind.TAKE
    assert decision.selected_director is DirectorKind.TAKE


def test_human_override_is_sticky_and_disables_fallback_by_default() -> None:
    decision = _policy().decide(
        input_profile_ref="profile:doc",
        content_basis=_factual_basis(),
        advisory_recommendations=[DirectorKind.OPENMONTAGE],
        human_override=DirectorKind.TAKE,
        override_actor="human-showrunner",
        override_reason="wants cinematic treatment",
    )
    assert decision.policy_selected_director is DirectorKind.OPENMONTAGE
    assert decision.selected_director is DirectorKind.TAKE
    assert decision.human_override is DirectorKind.TAKE
    assert decision.override_actor == "human-showrunner"
    assert decision.fallback_enabled is False


def test_human_override_can_explicitly_permit_fallback() -> None:
    decision = _policy().decide(
        input_profile_ref="profile:doc",
        content_basis=_factual_basis(),
        human_override=DirectorKind.TAKE,
        override_actor="human-showrunner",
        override_reason="cinematic, but resilience matters",
        override_allows_fallback=True,
    )
    assert decision.fallback_enabled is True


def test_routing_decision_carries_no_provider_fields() -> None:
    decision = _policy().decide(input_profile_ref="profile:doc", content_basis=_factual_basis())
    assert set(decision.model_dump(mode="json")).isdisjoint(FORBIDDEN_PROVIDER_FIELDS)


# --------------------------------------------------------------------------- #
# Step 2 — failure classes and fallback
# --------------------------------------------------------------------------- #


def test_route_unavailable_falls_back_to_arcreel_native_when_policy_allows() -> None:
    routing = _policy().decide(input_profile_ref="p", content_basis=_factual_basis())
    primary = _FakeAdapter(DirectorKind.OPENMONTAGE, error=DirectorRouteUnavailable("donor down"))
    native = _FakeAdapter(DirectorKind.ARCREEL_NATIVE, result=_FakeRaw(*_split(_golden_raw())))
    result = _service().execute(
        routing=routing,
        adapters={DirectorKind.OPENMONTAGE: primary, DirectorKind.ARCREEL_NATIVE: native},
        artifact=object(),
    )
    assert isinstance(result, DirectorSuccess)
    assert result.actual_director is DirectorKind.ARCREEL_NATIVE
    assert native.calls == 1


def test_route_unavailable_fails_when_fallback_disabled() -> None:
    routing = _policy().decide(
        input_profile_ref="p",
        content_basis=_factual_basis(),
        human_override=DirectorKind.OPENMONTAGE,
        override_actor="human",
        override_reason="stay on openmontage",
    )
    primary = _FakeAdapter(DirectorKind.OPENMONTAGE, error=DirectorRouteUnavailable("donor down"))
    native = _FakeAdapter(DirectorKind.ARCREEL_NATIVE, result=_FakeRaw(*_split(_golden_raw())))
    result = _service().execute(
        routing=routing,
        adapters={DirectorKind.OPENMONTAGE: primary, DirectorKind.ARCREEL_NATIVE: native},
        artifact=object(),
    )
    assert isinstance(result, DirectorFailure)
    assert result.failure_class is DirectorFailureClass.ROUTE_UNAVAILABLE
    assert native.calls == 0


def test_transient_retries_same_director_before_any_fallback() -> None:
    routing = _policy().decide(input_profile_ref="p", content_basis=_factual_basis())
    primary = _FakeAdapter(
        DirectorKind.OPENMONTAGE,
        result=_FakeRaw(*_split(_golden_raw())),
        error=DirectorTransientError("rate limited"),
        error_times=1,
    )
    native = _FakeAdapter(DirectorKind.ARCREEL_NATIVE, result=_FakeRaw(*_split(_golden_raw())))
    result = _service().execute(
        routing=routing,
        adapters={DirectorKind.OPENMONTAGE: primary, DirectorKind.ARCREEL_NATIVE: native},
        artifact=object(),
        transient_retry_budget=1,
    )
    assert isinstance(result, DirectorSuccess)
    assert result.actual_director is DirectorKind.OPENMONTAGE
    assert primary.calls == 2
    assert native.calls == 0


def test_transient_exhausted_falls_back_to_arcreel_native() -> None:
    routing = _policy().decide(input_profile_ref="p", content_basis=_factual_basis())
    primary = _FakeAdapter(DirectorKind.OPENMONTAGE, error=DirectorTransientError("still down"))
    native = _FakeAdapter(DirectorKind.ARCREEL_NATIVE, result=_FakeRaw(*_split(_golden_raw())))
    result = _service().execute(
        routing=routing,
        adapters={DirectorKind.OPENMONTAGE: primary, DirectorKind.ARCREEL_NATIVE: native},
        artifact=object(),
        transient_retry_budget=1,
    )
    assert isinstance(result, DirectorSuccess)
    assert result.actual_director is DirectorKind.ARCREEL_NATIVE
    assert primary.calls == 2  # initial + one retry
    assert native.calls == 1


def test_contract_or_semantic_failure_fails_closed_without_fallback() -> None:
    routing = _policy().decide(input_profile_ref="p", content_basis=_factual_basis())
    primary = _FakeAdapter(DirectorKind.OPENMONTAGE, result=_FakeRaw([], [{"id": "SH-broken"}]))
    native = _FakeAdapter(DirectorKind.ARCREEL_NATIVE, result=_FakeRaw(*_split(_golden_raw())))
    result = _service().execute(
        routing=routing,
        adapters={DirectorKind.OPENMONTAGE: primary, DirectorKind.ARCREEL_NATIVE: native},
        artifact=object(),
    )
    assert isinstance(result, DirectorFailure)
    assert result.failure_class is DirectorFailureClass.CONTRACT_OR_SEMANTIC_FAILURE
    assert result.fallback_eligible is False
    assert native.calls == 0


def test_partial_or_ambiguous_execution_fails_closed() -> None:
    routing = _policy().decide(input_profile_ref="p", content_basis=_factual_basis())
    primary = _FakeAdapter(
        DirectorKind.OPENMONTAGE,
        error=DirectorPartialOutput("crashed after 2 of 5 shots", diagnostic_ref="diag:quarantine/1"),
    )
    native = _FakeAdapter(DirectorKind.ARCREEL_NATIVE, result=_FakeRaw(*_split(_golden_raw())))
    result = _service().execute(
        routing=routing,
        adapters={DirectorKind.OPENMONTAGE: primary, DirectorKind.ARCREEL_NATIVE: native},
        artifact=object(),
    )
    assert isinstance(result, DirectorFailure)
    assert result.failure_class is DirectorFailureClass.PARTIAL_OR_AMBIGUOUS_EXECUTION
    assert result.partial_output_diagnostic_ref == "diag:quarantine/1"
    assert native.calls == 0


def test_no_automatic_cross_route_between_openmontage_and_take() -> None:
    routing = _policy().decide(input_profile_ref="p", content_basis=_factual_basis())
    primary = _FakeAdapter(DirectorKind.OPENMONTAGE, error=DirectorRouteUnavailable("down"))
    take = _FakeAdapter(DirectorKind.TAKE, result=_FakeRaw(*_split(_golden_raw())))
    result = _service().execute(
        routing=routing,
        adapters={DirectorKind.OPENMONTAGE: primary, DirectorKind.TAKE: take},
        artifact=object(),
    )
    assert isinstance(result, DirectorFailure)
    assert take.calls == 0


# --------------------------------------------------------------------------- #
# Step 3 — M3 donor adapter behind the generic seam
# --------------------------------------------------------------------------- #


def test_wraps_m3_golden_a_openmontage_adapter_without_modifying_m3() -> None:
    bundle = load_golden_a_factual_bundle()
    routing = _policy().decide(input_profile_ref="profile:golden-a", content_basis=bundle.script.content_basis)
    adapter = OpenMontageDirectorAdapter(GoldenAOpenMontageAdapter(FixtureOpenMontageBackend()))
    assert adapter.director_kind is DirectorKind.OPENMONTAGE

    result = _service().execute(
        routing=routing,
        adapters={DirectorKind.OPENMONTAGE: adapter},
        artifact=bundle.script,
    )
    assert isinstance(result, DirectorSuccess)
    assert result.actual_director is DirectorKind.OPENMONTAGE
    assert len(result.scenes) == 3
    assert len(result.shots) == 4
    assert {s.id for s in result.scenes} == {"SC01", "SC02", "SC03"}
    assert result.routing_decision_ref == routing.routing_decision_id


def test_validator_rejects_shot_referencing_unknown_scene() -> None:
    routing = _policy().decide(input_profile_ref="p", content_basis=_factual_basis())
    scenes, shots = _split(_golden_raw())
    orphan = shots[0].model_copy(update={"scene_id": "SC-DOES-NOT-EXIST"})
    result = _service().execute(
        routing=routing,
        adapters={DirectorKind.OPENMONTAGE: _FakeAdapter(DirectorKind.OPENMONTAGE, result=_FakeRaw(scenes, [orphan]))},
        artifact=object(),
    )
    assert isinstance(result, DirectorFailure)
    assert result.failure_class is DirectorFailureClass.CONTRACT_OR_SEMANTIC_FAILURE


def _split(golden):
    return list(golden.scenes), list(golden.shots)


# --------------------------------------------------------------------------- #
# High-3 — a pre-built DirectorSuccess is still semantically re-validated
# --------------------------------------------------------------------------- #


def _prebuilt_success(routing, director, *, scenes=None, shots=None) -> DirectorSuccess:
    s, sh = _split(_golden_raw())
    return DirectorSuccess(
        routing_decision_ref=routing.routing_decision_id,
        actual_director=director,
        scenes=s if scenes is None else scenes,
        shots=sh if shots is None else shots,
        validation_summary="adapter-asserted PASS",
        provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=_CLOCK),
    )


def _run_with_prebuilt(prebuilt, routing):
    return _service().execute(
        routing=routing,
        adapters={DirectorKind.OPENMONTAGE: _FakeAdapter(DirectorKind.OPENMONTAGE, result=prebuilt)},
        artifact=object(),
    )


def test_prebuilt_director_success_with_orphan_shot_is_rejected() -> None:
    routing = _policy().decide(input_profile_ref="p", content_basis=_factual_basis())
    _, shots = _split(_golden_raw())
    orphan = shots[0].model_copy(update={"scene_id": "SC-NOWHERE"})
    result = _run_with_prebuilt(_prebuilt_success(routing, DirectorKind.OPENMONTAGE, shots=[orphan]), routing)
    assert isinstance(result, DirectorFailure)
    assert result.failure_class is DirectorFailureClass.CONTRACT_OR_SEMANTIC_FAILURE


def test_prebuilt_director_success_citing_a_foreign_routing_ref_is_rejected() -> None:
    routing = _policy().decide(input_profile_ref="p", content_basis=_factual_basis())
    prebuilt = _prebuilt_success(routing, DirectorKind.OPENMONTAGE).model_copy(
        update={"routing_decision_ref": "RD:some-other-run"}
    )
    result = _run_with_prebuilt(prebuilt, routing)
    assert isinstance(result, DirectorFailure)
    assert result.failure_class is DirectorFailureClass.CONTRACT_OR_SEMANTIC_FAILURE


def test_prebuilt_director_success_reporting_a_different_director_is_rejected() -> None:
    routing = _policy().decide(input_profile_ref="p", content_basis=_factual_basis())
    prebuilt = _prebuilt_success(routing, DirectorKind.TAKE)  # attempted is OPENMONTAGE
    result = _run_with_prebuilt(prebuilt, routing)
    assert isinstance(result, DirectorFailure)
    assert result.failure_class is DirectorFailureClass.CONTRACT_OR_SEMANTIC_FAILURE


def test_prebuilt_director_success_with_no_shots_is_rejected() -> None:
    routing = _policy().decide(input_profile_ref="p", content_basis=_factual_basis())
    result = _run_with_prebuilt(_prebuilt_success(routing, DirectorKind.OPENMONTAGE, shots=[]), routing)
    assert isinstance(result, DirectorFailure)
    assert result.failure_class is DirectorFailureClass.CONTRACT_OR_SEMANTIC_FAILURE


def test_a_coherent_prebuilt_director_success_still_passes() -> None:
    routing = _policy().decide(input_profile_ref="p", content_basis=_factual_basis())
    result = _run_with_prebuilt(_prebuilt_success(routing, DirectorKind.OPENMONTAGE), routing)
    assert isinstance(result, DirectorSuccess)
    assert result.actual_director is DirectorKind.OPENMONTAGE


def test_a_prebuilt_director_failure_passes_through_untouched() -> None:
    routing = _policy().decide(input_profile_ref="p", content_basis=_factual_basis())
    failure = DirectorFailure(
        routing_decision_ref="RD:whatever",
        attempted_director=DirectorKind.TAKE,
        failure_class=DirectorFailureClass.ROUTE_UNAVAILABLE,
        retryable=False,
        fallback_eligible=False,
        error_code="ROUTE_UNAVAILABLE",
        message="donor down",
    )
    result = _run_with_prebuilt(failure, routing)
    assert result is failure


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
