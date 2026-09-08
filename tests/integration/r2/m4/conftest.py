"""D09 pipeline + Host-integration doubles for the M4 integration tests.

The pipeline harness itself lives in ``scripts/r2/run_m4_golden_12.py`` so the
canonical runner and the tests exercise exactly the same wiring.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from lib.budget_reservation import BudgetReservationSnapshot, BudgetReservationState
from r2.contracts import (
    ExecutionDecision,
    ExecutionIdentityStability,
    ExecutionType,
    Provenance,
    ProvenanceActor,
    ProviderRequest,
)
from r2.production_intelligence.fixture_loader import load_m4_golden_12
from r2.production_intelligence.host_integration import HostSubmitOutcome
from scripts.r2.run_m4_golden_12 import M4PipelineResult, run_pipeline

__all__ = ["M4PipelineResult", "run_pipeline"]

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
def golden_12():
    return load_m4_golden_12()


@pytest.fixture
def pipeline():
    return run_pipeline


# --------------------------------------------------------------------------- #
# Host-integration doubles
# --------------------------------------------------------------------------- #


class _FakeReservationService:
    def __init__(self, *, claim_error: BaseException | None = None) -> None:
        self.claim_calls = 0
        self.release_calls = 0
        self._claim_error = claim_error

    async def claim_for_submission(self, *, reservation_ref, execution_decision_ref, now):
        self.claim_calls += 1
        if self._claim_error is not None:
            raise self._claim_error
        return _reservation_snapshot(reservation_ref, execution_decision_ref, BudgetReservationState.CLAIMED)

    async def release_pre_submit(self, *, reservation_ref, execution_decision_ref, now):  # pragma: no cover
        self.release_calls += 1
        return _reservation_snapshot(reservation_ref, execution_decision_ref, BudgetReservationState.RELEASED)


class _FakeSubmitter:
    def __init__(self, *, outcome: HostSubmitOutcome | None = None, error: BaseException | None = None) -> None:
        self.calls = 0
        self._outcome = outcome or HostSubmitOutcome(
            succeeded=True, provider_execution_ref="job:1", output_asset_ref="asset:1"
        )
        self._error = error

    async def __call__(self, request):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._outcome


def _reservation_snapshot(reservation_ref: str, execution_decision_ref: str, state: BudgetReservationState):
    return BudgetReservationSnapshot(
        reservation_ref=reservation_ref,
        budget_scope_ref="scope:1",
        execution_decision_ref=execution_decision_ref,
        reserved_amount=Decimal("3.00"),
        currency="USD",
        state=state,
        created_at=_NOW,
        expires_at=None,
        claimed_at=_NOW if state is BudgetReservationState.CLAIMED else None,
        released_at=None,
        reconciled_at=None,
        cost_record_ref=None,
        version=1,
    )


def _make_decision(*, provider: str = "cloud", reservation: str | None = "RSV:1"):
    return ExecutionDecision(
        id=f"ED:SH01:{provider}",
        target_ref="SH01",
        method_decision_ref="MD:SH01",
        prompt_plan_ref="PP:SH01",
        capability_resolution_ref="req-hash",
        adapter_id=f"adapter:{provider}",
        provider_id=provider,
        model_or_tool_id=f"cap:{provider}",
        execution_type=ExecutionType.API if reservation else ExecutionType.LOCAL,
        capability_descriptor_version="cat-v1",
        observation_snapshot_ref="obs-1",
        execution_identity_stability=ExecutionIdentityStability.IMMUTABLE_REVISION,
        request_semantics_hash="r" * 16,
        selection_policy_version="sel-v1",
        budget_reservation_ref=reservation,
        provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=_NOW),
    )


def _make_request(*, provider: str = "cloud"):
    return ProviderRequest(
        id="REQ-1",
        method_decision_ref="MD:SH01",
        prompt_plan_ref="PP:SH01",
        provider=provider,
        model=f"cap:{provider}",
        endpoint="generate/api",
        payload={"instruction": "do the thing"},
        adapter_version="cat-v1",
    )


class _HostKit:
    NOW = _NOW
    ReservationService = _FakeReservationService
    Submitter = _FakeSubmitter
    make_decision = staticmethod(_make_decision)
    make_request = staticmethod(_make_request)


@pytest.fixture
def hostkit():
    return _HostKit
