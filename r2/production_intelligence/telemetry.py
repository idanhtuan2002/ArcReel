"""D10 — non-authoritative production telemetry projection.

The projector turns authoritative records into ``ProductionEvent`` envelopes and
bounded metric labels. It references authoritative objects; it never mutates
ApprovedMaster, the Artifact Manifest, a MethodDecision, or Canon, and it imports
no authority layer.
"""

from __future__ import annotations

from datetime import datetime

from r2.contracts import (
    FailureRecord,
    ProductionEvent,
    Provenance,
    ProvenanceActor,
)


class ProductionTelemetryProjector:
    def __init__(self, *, production_run_id: str) -> None:
        self._run_id = production_run_id

    def project_failure(self, failure: FailureRecord) -> ProductionEvent:
        return ProductionEvent(
            event_id=f"E:{self._run_id}:{failure.failure_id}",
            event_type="FAILURE",
            timestamp=failure.occurred_at,
            production_run_id=self._run_id,
            target_ref=failure.target_ref,
            stage=failure.domain.value.lower(),
            outcome=failure.classification.value,
            reason_code=failure.reason_code,
            decision_refs=list(failure.decision_refs),
            attempt_ref=failure.attempt_ref,
            provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=failure.occurred_at),
        )

    def project_attempt(
        self,
        *,
        target_ref: str,
        method_decision_ref: str,
        execution_decision_ref: str,
        attempt_ref: str,
        stage: str,
        outcome: str,
        now: datetime,
    ) -> ProductionEvent:
        return ProductionEvent(
            event_id=f"E:{self._run_id}:{target_ref}:{attempt_ref}",
            event_type="ATTEMPT",
            timestamp=now,
            production_run_id=self._run_id,
            target_ref=target_ref,
            stage=stage,
            outcome=outcome,
            reason_code=None,
            decision_refs=[method_decision_ref, execution_decision_ref],
            attempt_ref=attempt_ref,
            provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=now),
        )

    def project_shot_outcome(self, *, target_ref: str, outcome: str, now: datetime) -> ProductionEvent:
        return ProductionEvent(
            event_id=f"E:{self._run_id}:{target_ref}:outcome",
            event_type="SHOT_OUTCOME",
            timestamp=now,
            production_run_id=self._run_id,
            target_ref=target_ref,
            stage="shot",
            outcome=outcome,
            reason_code=None,
            decision_refs=[],
            attempt_ref=None,
            provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=now),
        )


def metric_labels(event: ProductionEvent) -> dict[str, str]:
    """Bounded label set only — enum/code values, never identifiers or free text."""

    labels = {
        "event_type": event.event_type,
        "stage": event.stage,
        "outcome": event.outcome or "NONE",
    }
    if event.reason_code is not None:
        labels["reason_code"] = event.reason_code
    return labels
