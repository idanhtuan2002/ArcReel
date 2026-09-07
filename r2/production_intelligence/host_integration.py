"""D08/M4 — narrow Host adapter for an admitted execution attempt.

Paid submissions go through the already-approved C04 guard
(``submit_with_budget_guard``): the reservation is claimed atomically, and only
then does the provider submission run — the guard never releases after ``submit``
has started. Local/non-paid submissions need no reservation. The result is a
``GenerationCandidate``; a candidate is never an ``ApprovedMaster`` (promotion is
the explicit M2 path).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from r2.contracts import (
    CandidateSelectionStatus,
    ExecutionDecision,
    GenerationCandidate,
    GenerationLifecycleStatus,
    ProviderRequest,
    compute_execution_fingerprint,
)
from server.services.paid_submission_guard import SupportsClaimForSubmission, submit_with_budget_guard


@dataclass(frozen=True)
class HostSubmitOutcome:
    succeeded: bool
    provider_execution_ref: str
    output_asset_ref: str | None
    cost_record_ref: str | None = None


HostSubmitter = Callable[[ProviderRequest], Awaitable[HostSubmitOutcome]]


class M4HostIntegration:
    def __init__(
        self,
        *,
        submitter: HostSubmitter,
        reservation_service: SupportsClaimForSubmission | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._submitter = submitter
        self._reservation_service = reservation_service
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        # attempt_ref -> Host cost record ref; cost stays attributable even on failure.
        self.cost_records: list[tuple[str, str]] = []

    async def execute_admitted(
        self,
        *,
        decision: ExecutionDecision,
        request: ProviderRequest,
        attempt_ref: str,
        content_fingerprint: str,
    ) -> GenerationCandidate:
        execution_fingerprint = compute_execution_fingerprint(
            provider=request.provider,
            model=request.model,
            endpoint=request.endpoint,
            seed=None,
            resolution=None,
            generation_settings={},
            prompt_compiler_version=request.adapter_version,
            provider_adapter_version=request.adapter_version,
        )

        if decision.budget_reservation_ref is not None:
            if self._reservation_service is None:
                raise ValueError("paid submission requires a reservation service")
            outcome = await submit_with_budget_guard(
                reservation_service=self._reservation_service,
                reservation_ref=decision.budget_reservation_ref,
                execution_decision_ref=decision.id,
                submit=lambda: self._submitter(request),
                now=self._clock(),
            )
        else:
            outcome = await self._submitter(request)

        if outcome.cost_record_ref is not None:
            self.cost_records.append((attempt_ref, outcome.cost_record_ref))

        return GenerationCandidate(
            id=f"CAND:{attempt_ref}",
            target_ref=decision.target_ref,
            content_fingerprint=content_fingerprint,
            execution_fingerprint=execution_fingerprint,
            provider_execution_ref=outcome.provider_execution_ref,
            output_asset_ref=outcome.output_asset_ref or f"no-output:{attempt_ref}",
            lifecycle_state=(
                GenerationLifecycleStatus.GENERATED if outcome.succeeded else GenerationLifecycleStatus.FAILED
            ),
            selection_state=CandidateSelectionStatus.UNREVIEWED,
        )
