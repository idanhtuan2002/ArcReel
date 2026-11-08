"""A step reserves at least what its model calls may cost on the run's paid routes before it dispatches."""

from __future__ import annotations

from r2.contracts.automation import ModelRoute
from server.production_run.controller import ProductionController
from server.production_run.ports import StepPlan
from tests.unit.server.production_run.test_controller import _policy, _run


def _route(role: str, *, paid: bool, ceiling: int | None) -> ModelRoute:
    return ModelRoute(
        role=role,
        provider_id="custom-1",
        model_id=role,
        model_identity=role,
        config_digest="sha256:" + "1" * 64,
        local=not paid,
        paid=paid,
        currency="USD",
        max_cost_per_call=ceiling,
    )


def _plan(cost: int, calls: int) -> StepPlan:
    return StepPlan(
        unit_key="script",
        input_refs=(),
        estimated_cost_minor_units=cost,
        estimated_model_calls=calls,
        estimated_tasks=1,
        estimated_runtime_seconds=60,
    )


def _intent(routes, plan: StepPlan):
    return ProductionController._intent(_run(policy=_policy(routes=routes)), "text", plan)


def test_a_step_on_a_paid_route_reserves_its_calls_at_the_highest_per_call_ceiling():
    routes = (_route("writer", paid=False, ceiling=None), _route("reviewer_a", paid=True, ceiling=7))

    assert _intent(routes, _plan(0, 3)).estimated_cost_minor_units == 21
    assert _intent(routes, _plan(40, 3)).estimated_cost_minor_units == 40


def test_a_run_with_only_local_routes_reserves_what_the_owner_estimated():
    routes = (_route("writer", paid=False, ceiling=None),)

    assert _intent(routes, _plan(0, 3)).estimated_cost_minor_units == 0
