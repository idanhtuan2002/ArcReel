"""D08/M4 — narrow Host adapter for admitted execution."""

from __future__ import annotations

import pytest

from r2.contracts import CandidateSelectionStatus, GenerationLifecycleStatus
from r2.production_intelligence.host_integration import HostSubmitOutcome, M4HostIntegration

_CONTENT_FP = "c" * 64


async def test_local_submission_needs_no_reservation(hostkit) -> None:
    submitter = hostkit.Submitter()
    integration = M4HostIntegration(submitter=submitter)
    candidate = await integration.execute_admitted(
        decision=hostkit.make_decision(reservation=None),
        request=hostkit.make_request(),
        attempt_ref="ATT-1",
        content_fingerprint=_CONTENT_FP,
    )
    assert submitter.calls == 1
    assert candidate.lifecycle_state is GenerationLifecycleStatus.GENERATED
    assert candidate.selection_state is CandidateSelectionStatus.UNREVIEWED


async def test_candidate_success_is_not_an_approved_master(hostkit) -> None:
    integration = M4HostIntegration(submitter=hostkit.Submitter())
    candidate = await integration.execute_admitted(
        decision=hostkit.make_decision(reservation=None),
        request=hostkit.make_request(),
        attempt_ref="ATT-1",
        content_fingerprint=_CONTENT_FP,
    )
    assert candidate.selection_state is not CandidateSelectionStatus.SELECTED
    assert type(candidate).__name__ == "GenerationCandidate"


async def test_execution_fingerprint_reflects_provider_not_content(hostkit) -> None:
    a = await M4HostIntegration(submitter=hostkit.Submitter()).execute_admitted(
        decision=hostkit.make_decision(provider="prov-a", reservation=None),
        request=hostkit.make_request(provider="prov-a"),
        attempt_ref="ATT-A",
        content_fingerprint=_CONTENT_FP,
    )
    b = await M4HostIntegration(submitter=hostkit.Submitter()).execute_admitted(
        decision=hostkit.make_decision(provider="prov-b", reservation=None),
        request=hostkit.make_request(provider="prov-b"),
        attempt_ref="ATT-B",
        content_fingerprint=_CONTENT_FP,
    )
    assert a.content_fingerprint == b.content_fingerprint == _CONTENT_FP
    assert a.execution_fingerprint != b.execution_fingerprint


async def test_failed_submission_yields_a_failed_candidate_with_placeholder_output(hostkit) -> None:
    submitter = hostkit.Submitter(
        outcome=HostSubmitOutcome(succeeded=False, provider_execution_ref="job:x", output_asset_ref=None)
    )
    candidate = await M4HostIntegration(submitter=submitter).execute_admitted(
        decision=hostkit.make_decision(reservation=None),
        request=hostkit.make_request(),
        attempt_ref="ATT-1",
        content_fingerprint=_CONTENT_FP,
    )
    assert candidate.lifecycle_state is GenerationLifecycleStatus.FAILED
    assert candidate.output_asset_ref.startswith("no-output:")


async def test_paid_submission_without_reservation_service_is_rejected(hostkit) -> None:
    with pytest.raises(ValueError, match="reservation service"):
        await M4HostIntegration(submitter=hostkit.Submitter()).execute_admitted(
            decision=hostkit.make_decision(reservation="RSV:1"),
            request=hostkit.make_request(),
            attempt_ref="ATT-1",
            content_fingerprint=_CONTENT_FP,
        )


async def test_request_provider_must_match_the_execution_decision(hostkit) -> None:
    with pytest.raises(ValueError, match="provider"):
        await M4HostIntegration(submitter=hostkit.Submitter()).execute_admitted(
            decision=hostkit.make_decision(provider="cloud", reservation=None),
            request=hostkit.make_request(provider="somewhere-else"),
            attempt_ref="ATT-1",
            content_fingerprint=_CONTENT_FP,
        )
    assert hostkit.Submitter().calls == 0


async def test_request_model_must_match_the_execution_decision(hostkit) -> None:
    submitter = hostkit.Submitter()
    mismatched = hostkit.make_request(provider="cloud").model_copy(update={"model": "cap:other"})
    with pytest.raises(ValueError, match="model"):
        await M4HostIntegration(submitter=submitter).execute_admitted(
            decision=hostkit.make_decision(provider="cloud", reservation=None),
            request=mismatched,
            attempt_ref="ATT-1",
            content_fingerprint=_CONTENT_FP,
        )
    assert submitter.calls == 0
