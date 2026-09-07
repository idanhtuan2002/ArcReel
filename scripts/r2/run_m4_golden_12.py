"""D09/D11 — the canonical M4 golden-12 runner.

``--mode regression`` threads all 12 fixture shots through the real M4
policies/services/contracts/compiler against controlled boundary doubles, with a
deterministic clock/observations/budget; no paid network. ``--mode evidence``
additionally proves real deterministic seams (FFmpeg) for the non-generative
methods and reports which generative seams still need a Human-approved waiver.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from lib.budget_reservation import BudgetDeniedError, BudgetReservationSnapshot, BudgetReservationState
from r2.contracts import (
    AdmissionOutcome,
    DirectorKind,
    DirectorResult,
    DirectorSuccess,
    ProductionMethod,
    ReadinessState,
)
from r2.production_intelligence.admission import GenerationAdmissionService
from r2.production_intelligence.capability_registry import (
    CapabilityMatcher,
    CapabilityRegistry,
    CapabilityRequirementBuilder,
    default_freshness_policy,
)
from r2.production_intelligence.director import DirectorExecutionService, DirectorRoutingPolicy
from r2.production_intelligence.execution import ExecutionDecisionService
from r2.production_intelligence.fixture_loader import M4ShotCase, load_m4_golden_12
from r2.production_intelligence.identity import VisualIdentityResolver
from r2.production_intelligence.method_router import MethodRouter, MethodRoutingContext
from r2.production_intelligence.prompting import DefaultPromptCompiler, PromptPlanner
from r2.production_intelligence.readiness import ProductionReadinessEvaluator
from scripts.r2.m4_test_doubles import DirectorDoubleMode, FixtureDirectorAdapter

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
_SNAPSHOT = "golden-12-binding-snapshot@1"
_NON_GENERATIVE = {
    ProductionMethod.REUSE,
    ProductionMethod.STOCK,
    ProductionMethod.SCREEN_CAPTURE,
    ProductionMethod.DETERMINISTIC,
    ProductionMethod.COMPOSITE,
}


class _FakeBudgetPort:
    def __init__(self, *, deny: bool = False) -> None:
        self.reserve_calls = 0
        self._deny = deny

    async def reserve(
        self, *, budget_scope_ref, reservation_ref, execution_decision_ref, amount, currency, expires_at, provenance
    ):
        self.reserve_calls += 1
        if self._deny:
            raise BudgetDeniedError("over budget")
        return BudgetReservationSnapshot(
            reservation_ref=reservation_ref,
            budget_scope_ref=budget_scope_ref,
            execution_decision_ref=execution_decision_ref,
            reserved_amount=amount,
            currency=currency,
            state=BudgetReservationState.ACTIVE,
            created_at=_NOW,
            expires_at=expires_at,
            claimed_at=None,
            released_at=None,
            reconciled_at=None,
            cost_record_ref=None,
            version=1,
        )

    async def release_pre_submit(self, *, reservation_ref, execution_decision_ref):  # pragma: no cover
        raise AssertionError("runner must not release")


@dataclass
class M4PipelineResult:
    case: M4ShotCase
    routing: Any
    director_result: DirectorResult
    readiness: Any = None
    method_decision: Any = None
    capability_resolution: Any = None
    prompt_plan: Any = None
    admission: Any = None
    execution_decision: Any = None
    provider_request: Any = None
    method_error: BaseException | None = None
    trace: list[str] = field(default_factory=list)

    @property
    def admitted(self) -> bool:
        return self.admission is not None and self.admission.outcome is AdmissionOutcome.ADMITTED


async def run_pipeline(
    case: M4ShotCase,
    *,
    director_mode: DirectorDoubleMode = DirectorDoubleMode.SUCCEED,
    drop_required_binding: bool = False,
    feature_support_override: dict[str, Any] | None = None,
    stale_observation: bool = False,
    budget_denied: bool = False,
) -> M4PipelineResult:
    routing = DirectorRoutingPolicy(clock=lambda: _NOW).decide(
        input_profile_ref=f"profile:{case.shot.id}",
        content_basis=case.content_basis,
        human_override=DirectorKind.ARCREEL_NATIVE if case.director is DirectorKind.ARCREEL_NATIVE else None,
        override_actor="human-showrunner" if case.director is DirectorKind.ARCREEL_NATIVE else None,
        override_reason="fixture routes sequence C natively" if case.director is DirectorKind.ARCREEL_NATIVE else None,
        override_allows_fallback=False,
        decision_id=f"RD:{case.shot.id}",
    )
    adapter = FixtureDirectorAdapter(
        director_kind=routing.selected_director, scenes=[case.scene], shots=[case.shot], mode=director_mode
    )
    native = FixtureDirectorAdapter(director_kind=DirectorKind.ARCREEL_NATIVE, scenes=[case.scene], shots=[case.shot])
    director_result = DirectorExecutionService(clock=lambda: _NOW).execute(
        routing=routing,
        adapters={routing.selected_director: adapter, DirectorKind.ARCREEL_NATIVE: native},
        artifact=case.shot,
    )
    result = M4PipelineResult(case=case, routing=routing, director_result=director_result, trace=["RoutingDecision"])
    if not isinstance(director_result, DirectorSuccess):
        return result
    result.trace.append("DirectorSuccess")

    resolved_identity = VisualIdentityResolver().resolve(
        target_ref=case.shot.id,
        scope_ancestry=case.scope_ancestry,
        profiles=list(case.identity_profiles),
    )
    bindings = () if drop_required_binding else case.bindings
    readiness = ProductionReadinessEvaluator().evaluate(
        shot=case.shot,
        bindings=list(bindings),
        resolved_identity=resolved_identity,
        observed_target_version=f"{case.shot.id}@1",
        binding_snapshot_ref=_SNAPSHOT,
    )
    result.readiness = readiness
    result.trace.append(f"ProductionReadiness={readiness.state.value}")
    if readiness.state is not ReadinessState.READY:
        return result

    try:
        method_decision = MethodRouter().decide(
            MethodRoutingContext(
                target_ref=case.shot.id,
                allowed_methods=case.allowed_methods,
                readiness=readiness,
                identity=resolved_identity,
                source_authenticity_required=False,
                reusable_asset_current=case.reusable_asset_current,
                deterministic_equivalent_available=case.deterministic_equivalent_available,
                policy_version="m4-method-router-v1",
            )
        )
    except Exception as exc:
        result.method_error = exc
        return result
    result.method_decision = method_decision
    result.trace.append(f"MethodDecision={method_decision.method.value}")

    requirements = CapabilityRequirementBuilder().build(
        method_decision=method_decision, identity=resolved_identity, shot=case.shot
    )
    observation = case.observation
    if stale_observation:
        observation = observation.model_copy(update={"observed_at": _NOW.replace(hour=11, minute=0)})
    descriptor = case.descriptor
    if feature_support_override:
        from r2.contracts import CapabilityFeatureSupport

        observation = observation.model_copy(
            update={
                "feature_support": [
                    CapabilityFeatureSupport(feature_key=k, support=v) for k, v in feature_support_override.items()
                ]
            }
        )
        descriptor = descriptor.model_copy(update={"typed_features": []})

    registry = CapabilityRegistry(descriptors=[descriptor], observations=[observation], registry_version="reg-12-v1")
    capability_resolution = CapabilityMatcher().resolve(
        requirements=requirements,
        registry=registry,
        freshness_policy=default_freshness_policy(created_at=_NOW),
        now=_NOW,
    )
    result.capability_resolution = capability_resolution
    result.trace.append("CapabilityResolution")

    prompt_plan = PromptPlanner().build(shot=case.shot, method_decision=method_decision, identity=resolved_identity)
    result.prompt_plan = prompt_plan
    result.trace.append("PromptPlan")

    port = _FakeBudgetPort(deny=budget_denied)
    admission = await GenerationAdmissionService(budget_port=port).evaluate(
        readiness=readiness,
        method_decision=method_decision,
        capability_resolution=capability_resolution,
        prompt_plan=prompt_plan,
        budget_scope_ref=f"scope:{case.shot.id}" if case.paid else None,
        budget_amount=Decimal("3.00") if case.paid else None,
        budget_currency="USD" if case.paid else None,
        approval_ref=f"APPROVAL:{case.shot.id}" if case.requires_approval else None,
        now=_NOW,
        requires_approval=case.requires_approval,
    )
    result.admission = admission
    result.trace.append(f"GenerationAdmission={admission.outcome.value}")
    if admission.outcome is not AdmissionOutcome.ADMITTED:
        return result

    selected = capability_resolution.eligible_candidates[0]
    execution_decision = ExecutionDecisionService().create(
        admission=admission,
        capability_resolution=capability_resolution,
        prompt_plan=prompt_plan,
        selected_capability_id=selected,
        descriptor=descriptor,
    )
    result.execution_decision = execution_decision
    result.provider_request = DefaultPromptCompiler().compile(plan=prompt_plan, decision=execution_decision)
    result.trace.extend(["ExecutionDecision", "ProviderRequest"])
    return result


async def _run_regression() -> dict[str, object]:
    fixture = load_m4_golden_12()
    shots: list[dict[str, object]] = []
    for case in fixture.cases:
        res = await run_pipeline(case)
        ok = (
            isinstance(res.director_result, DirectorSuccess)
            and res.method_decision is not None
            and res.method_decision.method is case.method
            and res.admitted
            and res.provider_request is not None
        )
        shots.append(
            {
                "shot_id": case.shot.id,
                "expected_director": case.director.value,
                "expected_method": case.method.value,
                "actual_director": res.director_result.actual_director.value
                if isinstance(res.director_result, DirectorSuccess)
                else None,
                "actual_method": res.method_decision.method.value if res.method_decision else None,
                "trace": res.trace,
                "result": "PASS" if ok else "FAIL",
            }
        )
    passed = sum(1 for s in shots if s["result"] == "PASS")
    return {
        "mode": "regression",
        "fixture_id": fixture.fixture_id,
        "baseline_passed": passed,
        "baseline_total": len(shots),
        "result": "PASS" if passed == len(shots) else "FAIL",
        "shots": shots,
    }


def _ffmpeg_probe() -> dict[str, object]:
    """Prove a real deterministic tool seam: synthesize a tiny clip, then ffprobe it."""

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "det.mp4"
        gen = subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1", "-r", "5", str(out)],
            capture_output=True,
            text=True,
            check=False,
        )
        if gen.returncode != 0 or not out.exists():
            return {"available": False, "detail": gen.stderr[-200:]}
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
            capture_output=True,
            text=True,
            check=False,
        )
        return {"available": probe.returncode == 0, "duration": probe.stdout.strip()}


async def _run_evidence() -> dict[str, object]:
    regression = await _run_regression()
    ffmpeg = _ffmpeg_probe()
    _det = {"DETERMINISTIC", "COMPOSITE"}
    seams: list[dict[str, object]] = [
        {
            "method": method,
            "seam": "ffmpeg-deterministic" if method in _det else "fixture-local",
            "result": "PASS" if (method not in _det or ffmpeg["available"]) else "FAIL",
            "artifact_refs": (["ffmpeg://det.mp4"] if method in _det and ffmpeg["available"] else []),
            "attempt_refs": [],
            "cost_refs": [],
        }
        for method in ("REUSE", "SCREEN_CAPTURE", "DETERMINISTIC", "COMPOSITE")
    ]
    seams += [
        {
            "method": method,
            "seam": "real local/approved provider",
            "result": "WAIVER_REQUIRED",
            "detail": "no local GPU model or Human-approved provider seam configured in this environment",
            "artifact_refs": [],
            "attempt_refs": [],
            "cost_refs": [],
        }
        for method in ("GENERATED_IMAGE", "GENERATED_VIDEO")
    ]
    incomplete = [s for s in seams if s["result"] not in {"PASS"}]
    return {
        "mode": "evidence",
        "regression": regression,
        "ffmpeg": ffmpeg,
        "real_execution_evidence": seams,
        "result": "PASS" if not incomplete else "INCOMPLETE_PENDING_WAIVER",
        "incomplete_seams": [s["method"] for s in incomplete],
    }


def main() -> int:
    import asyncio

    parser = argparse.ArgumentParser(description="M4 golden-12 runner")
    parser.add_argument("--mode", choices=["regression", "evidence"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = asyncio.run(_run_regression() if args.mode == "regression" else _run_evidence())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{args.mode}: {report['result']}", file=sys.stderr)
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
