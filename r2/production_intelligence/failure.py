"""D10 — normalized domain failure semantics.

A domain outcome is not a telemetry signal, and an expected block
(BLOCKED / DENIED / UNKNOWN / UNSUPPORTED / APPROVAL_REQUIRED / normal CANCELLED)
is not automatically a system error. Retry disposition is explicit and never
inferred ad hoc from an exception string. ``safe_message`` never carries the
exception payload; restricted detail lives behind ``diagnostic_ref``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import ValidationError

from lib.budget_reservation import BudgetDeniedError
from r2.contracts import (
    FailureClassification,
    FailureDomain,
    FailureRecord,
    Provenance,
    ProvenanceActor,
    RetryDisposition,
)
from r2.production_intelligence.director import (
    DirectorPartialOutput,
    DirectorRouteUnavailable,
    DirectorTransientError,
)
from r2.production_intelligence.execution import ExecutionNotAdmitted
from r2.production_intelligence.method_router import MethodRoutingBlocked
from r2.production_intelligence.prompting import PromptCompilationIncompatible

_SYSTEM_ERROR_CLASSES = {FailureClassification.PERMANENT, FailureClassification.INTEGRITY}

# exception type -> (domain, classification, retry_disposition, reason_code)
_EXCEPTION_MAP: list[tuple[type[BaseException], tuple[FailureDomain, FailureClassification, RetryDisposition, str]]] = [
    (
        MethodRoutingBlocked,
        (
            FailureDomain.METHOD,
            FailureClassification.EXPECTED_BLOCK,
            RetryDisposition.HUMAN_ACTION_REQUIRED,
            "METHOD_ROUTING_BLOCKED",
        ),
    ),
    (
        PromptCompilationIncompatible,
        (
            FailureDomain.COMPILATION,
            FailureClassification.CONTRACT,
            RetryDisposition.NEW_EXECUTION_DECISION_REQUIRED,
            "COMPILATION_INCOMPATIBLE",
        ),
    ),
    (
        ExecutionNotAdmitted,
        (
            FailureDomain.ADMISSION,
            FailureClassification.EXPECTED_BLOCK,
            RetryDisposition.NEW_EXECUTION_DECISION_REQUIRED,
            "NOT_ADMITTED",
        ),
    ),
    (
        BudgetDeniedError,
        (
            FailureDomain.ADMISSION,
            FailureClassification.EXPECTED_BLOCK,
            RetryDisposition.NEW_EXECUTION_DECISION_REQUIRED,
            "BUDGET_DENIED",
        ),
    ),
    (
        DirectorPartialOutput,
        (
            FailureDomain.DIRECTOR,
            FailureClassification.CONTRACT,
            RetryDisposition.HUMAN_ACTION_REQUIRED,
            "PARTIAL_OR_AMBIGUOUS_EXECUTION",
        ),
    ),
    (
        DirectorRouteUnavailable,
        (
            FailureDomain.DIRECTOR,
            FailureClassification.EXPECTED_BLOCK,
            RetryDisposition.NOT_RETRYABLE,
            "ROUTE_UNAVAILABLE",
        ),
    ),
    (
        DirectorTransientError,
        (
            FailureDomain.DIRECTOR,
            FailureClassification.TRANSIENT,
            RetryDisposition.RETRY_SAME_EXECUTION,
            "TRANSIENT_EXECUTION_FAILURE",
        ),
    ),
    (
        TimeoutError,
        (FailureDomain.EXECUTION, FailureClassification.TRANSIENT, RetryDisposition.RETRY_WITH_BACKOFF, "TRANSIENT_IO"),
    ),
    (
        ConnectionError,
        (FailureDomain.EXECUTION, FailureClassification.TRANSIENT, RetryDisposition.RETRY_WITH_BACKOFF, "TRANSIENT_IO"),
    ),
    (
        ValidationError,
        (
            FailureDomain.VALIDATION,
            FailureClassification.CONTRACT,
            RetryDisposition.NOT_RETRYABLE,
            "CONTRACT_VIOLATION",
        ),
    ),
    (
        ValueError,
        (
            FailureDomain.VALIDATION,
            FailureClassification.CONTRACT,
            RetryDisposition.NOT_RETRYABLE,
            "CONTRACT_VIOLATION",
        ),
    ),
]

_EXPECTED_OUTCOME_DISPOSITION: dict[str, RetryDisposition] = {
    "BLOCKED": RetryDisposition.HUMAN_ACTION_REQUIRED,
    "IDENTITY_CONFLICT": RetryDisposition.HUMAN_ACTION_REQUIRED,
    "NOT_READY": RetryDisposition.HUMAN_ACTION_REQUIRED,
    "DENIED_BUDGET": RetryDisposition.NEW_EXECUTION_DECISION_REQUIRED,
    "DENIED_NOT_READY": RetryDisposition.HUMAN_ACTION_REQUIRED,
    "DENIED_NO_CAPABILITY": RetryDisposition.NEW_METHOD_DECISION_REQUIRED,
    "DENIED_UNAVAILABLE": RetryDisposition.RETRY_WITH_BACKOFF,
    "DENIED_POLICY": RetryDisposition.HUMAN_ACTION_REQUIRED,
    "APPROVAL_REQUIRED": RetryDisposition.HUMAN_ACTION_REQUIRED,
    "CAPABILITY_UNKNOWN": RetryDisposition.RETRY_WITH_BACKOFF,
    "UNSUPPORTED": RetryDisposition.NEW_METHOD_DECISION_REQUIRED,
    "CANCELLED": RetryDisposition.NOT_RETRYABLE,
}


def is_system_error(record: FailureRecord) -> bool:
    return record.classification in _SYSTEM_ERROR_CLASSES


class FailureNormalizer:
    def normalize(
        self,
        exc: BaseException,
        *,
        stage: str,
        target_ref: str,
        now: datetime,
        attempt_ref: str | None = None,
        decision_refs: Sequence[str] | None = None,
        diagnostic_ref: str | None = None,
    ) -> FailureRecord:
        domain, classification, disposition, reason_code = self._classify(exc, stage)
        return FailureRecord(
            failure_id=f"F:{target_ref}:{stage}:{reason_code}",
            occurred_at=now,
            domain=domain,
            reason_code=reason_code,
            classification=classification,
            retry_disposition=disposition,
            target_ref=target_ref,
            attempt_ref=attempt_ref,
            decision_refs=list(decision_refs or []),
            safe_message=f"{type(exc).__name__} in {stage}",
            diagnostic_ref=diagnostic_ref,
            provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=now),
        )

    def normalize_outcome(
        self,
        *,
        domain: FailureDomain,
        reason_code: str,
        target_ref: str,
        now: datetime,
        attempt_ref: str | None = None,
        decision_refs: Sequence[str] | None = None,
    ) -> FailureRecord:
        disposition = _EXPECTED_OUTCOME_DISPOSITION.get(reason_code, RetryDisposition.HUMAN_ACTION_REQUIRED)
        return FailureRecord(
            failure_id=f"F:{target_ref}:{domain.value}:{reason_code}",
            occurred_at=now,
            domain=domain,
            reason_code=reason_code,
            classification=FailureClassification.EXPECTED_BLOCK,
            retry_disposition=disposition,
            target_ref=target_ref,
            attempt_ref=attempt_ref,
            decision_refs=list(decision_refs or []),
            safe_message=f"expected outcome {reason_code} in {domain.value}",
            provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=now),
        )

    @staticmethod
    def _classify(
        exc: BaseException,
        stage: str,
    ) -> tuple[FailureDomain, FailureClassification, RetryDisposition, str]:
        for exc_type, mapping in _EXCEPTION_MAP:
            if isinstance(exc, exc_type):
                return mapping
        return (
            _stage_domain(stage),
            FailureClassification.PERMANENT,
            RetryDisposition.HUMAN_ACTION_REQUIRED,
            "UNCLASSIFIED_ERROR",
        )


def _stage_domain(stage: str) -> FailureDomain:
    try:
        return FailureDomain(stage.upper())
    except ValueError:
        return FailureDomain.EXECUTION
