"""D08/C04 — budget-guarded paid submission."""

from __future__ import annotations

import pytest

from lib.budget_reservation import InvalidBudgetTransitionError
from r2.contracts import GenerationLifecycleStatus
from r2.production_intelligence.host_integration import HostSubmitOutcome, M4HostIntegration

_CONTENT_FP = "c" * 64


async def test_active_claim_success_submits_exactly_once(hostkit) -> None:
    reservation = hostkit.ReservationService()
    submitter = hostkit.Submitter()
    candidate = await M4HostIntegration(submitter=submitter, reservation_service=reservation).execute_admitted(
        decision=hostkit.make_decision(reservation="RSV:1"),
        request=hostkit.make_request(),
        attempt_ref="ATT-1",
        content_fingerprint=_CONTENT_FP,
    )
    assert reservation.claim_calls == 1
    assert submitter.calls == 1
    assert candidate.lifecycle_state is GenerationLifecycleStatus.GENERATED


async def test_unclaimable_reservation_submits_zero_times(hostkit) -> None:
    reservation = hostkit.ReservationService(claim_error=InvalidBudgetTransitionError("reservation EXPIRED"))
    submitter = hostkit.Submitter()
    with pytest.raises(InvalidBudgetTransitionError):
        await M4HostIntegration(submitter=submitter, reservation_service=reservation).execute_admitted(
            decision=hostkit.make_decision(reservation="RSV:1"),
            request=hostkit.make_request(),
            attempt_ref="ATT-1",
            content_fingerprint=_CONTENT_FP,
        )
    assert reservation.claim_calls == 1
    assert submitter.calls == 0


async def test_post_claim_timeout_does_not_auto_release(hostkit) -> None:
    reservation = hostkit.ReservationService()
    submitter = hostkit.Submitter(error=TimeoutError("provider timed out after claim"))
    with pytest.raises(TimeoutError):
        await M4HostIntegration(submitter=submitter, reservation_service=reservation).execute_admitted(
            decision=hostkit.make_decision(reservation="RSV:1"),
            request=hostkit.make_request(),
            attempt_ref="ATT-1",
            content_fingerprint=_CONTENT_FP,
        )
    assert reservation.claim_calls == 1
    assert submitter.calls == 1
    assert reservation.release_calls == 0


async def test_charge_then_fail_keeps_the_host_cost_reference_attributable(hostkit) -> None:
    reservation = hostkit.ReservationService()
    submitter = hostkit.Submitter(
        outcome=HostSubmitOutcome(
            succeeded=False, provider_execution_ref="job:2", output_asset_ref=None, cost_record_ref="COST:2"
        )
    )
    integration = M4HostIntegration(submitter=submitter, reservation_service=reservation)
    candidate = await integration.execute_admitted(
        decision=hostkit.make_decision(reservation="RSV:1"),
        request=hostkit.make_request(),
        attempt_ref="ATT-1",
        content_fingerprint=_CONTENT_FP,
    )
    assert candidate.lifecycle_state is GenerationLifecycleStatus.FAILED
    assert integration.cost_records == [("ATT-1", "COST:2")]
