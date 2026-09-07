"""D09 — the positive golden baseline: all 12 shots produce the full public trace."""

from __future__ import annotations

import pytest

from r2.contracts import AdmissionOutcome, DirectorSuccess


@pytest.mark.parametrize(
    "shot_id",
    ["SH01", "SH02", "SH03", "SH04", "SH05", "SH06", "SH07", "SH08", "SH09", "SH10", "SH11", "SH12"],
)
async def test_baseline_shot_completes_the_public_trace(golden_12, pipeline, shot_id: str) -> None:
    case = golden_12.by_id(shot_id)
    result = await pipeline(case)

    assert isinstance(result.director_result, DirectorSuccess)
    assert result.director_result.actual_director is case.director
    assert result.readiness is not None
    assert result.readiness.state.value == "READY"
    assert result.method_decision is not None
    assert result.method_decision.method is case.method
    assert result.capability_resolution is not None
    assert result.capability_resolution.eligible_candidates
    assert result.prompt_plan is not None
    assert result.admission is not None
    assert result.admission.outcome is AdmissionOutcome.ADMITTED
    assert result.execution_decision is not None
    assert result.provider_request is not None
    assert result.provider_request.provider == case.descriptor.provider_id
    # provider identity is authoritative only from ExecutionDecision onward
    assert "provider" not in result.method_decision.model_dump(mode="json")
    assert "provider" not in result.prompt_plan.model_dump(mode="json")


async def test_baseline_is_twelve_of_twelve(golden_12, pipeline) -> None:
    passed = 0
    for case in golden_12.cases:
        result = await pipeline(case)
        if (
            isinstance(result.director_result, DirectorSuccess)
            and result.method_decision is not None
            and result.method_decision.method is case.method
            and result.admission is not None
            and result.admission.outcome is AdmissionOutcome.ADMITTED
            and result.provider_request is not None
        ):
            passed += 1
    assert passed == 12
