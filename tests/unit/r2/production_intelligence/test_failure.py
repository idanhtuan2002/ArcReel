"""D10 — normalized domain failure semantics."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lib.budget_reservation import BudgetDeniedError
from r2.contracts import FailureClassification, FailureDomain, RetryDisposition
from r2.production_intelligence.director import (
    DirectorPartialOutput,
    DirectorRouteUnavailable,
    DirectorTransientError,
)
from r2.production_intelligence.execution import ExecutionNotAdmitted
from r2.production_intelligence.failure import FailureNormalizer, is_system_error
from r2.production_intelligence.method_router import MethodRoutingBlocked
from r2.production_intelligence.prompting import PromptCompilationIncompatible

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _n():
    return FailureNormalizer()


@pytest.mark.parametrize("reason", ["BLOCKED", "DENIED_BUDGET", "CAPABILITY_UNKNOWN", "UNSUPPORTED"])
def test_expected_domain_outcomes_are_not_system_errors(reason: str) -> None:
    record = _n().normalize_outcome(domain=FailureDomain.ADMISSION, reason_code=reason, target_ref="SH01", now=_NOW)
    assert record.classification is FailureClassification.EXPECTED_BLOCK
    assert is_system_error(record) is False


def test_transient_director_failure_is_retryable_same_execution() -> None:
    record = _n().normalize(DirectorTransientError("rate limited"), stage="director", target_ref="SH01", now=_NOW)
    assert record.domain is FailureDomain.DIRECTOR
    assert record.classification is FailureClassification.TRANSIENT
    assert record.retry_disposition is RetryDisposition.RETRY_SAME_EXECUTION
    assert is_system_error(record) is False


def test_partial_director_output_requires_human_action() -> None:
    record = _n().normalize(DirectorPartialOutput("crashed"), stage="director", target_ref="SH01", now=_NOW)
    assert record.domain is FailureDomain.DIRECTOR
    assert record.retry_disposition is RetryDisposition.HUMAN_ACTION_REQUIRED


def test_route_unavailable_is_expected_and_not_retryable() -> None:
    record = _n().normalize(DirectorRouteUnavailable("donor down"), stage="director", target_ref="SH01", now=_NOW)
    assert record.classification is FailureClassification.EXPECTED_BLOCK
    assert record.retry_disposition is RetryDisposition.NOT_RETRYABLE


def test_method_routing_blocked_maps_to_method_domain_expected_block() -> None:
    record = _n().normalize(MethodRoutingBlocked("readiness BLOCKED"), stage="method", target_ref="SH01", now=_NOW)
    assert record.domain is FailureDomain.METHOD
    assert record.classification is FailureClassification.EXPECTED_BLOCK


def test_compilation_incompatible_is_a_contract_failure() -> None:
    record = _n().normalize(
        PromptCompilationIncompatible(("COMPILATION_INCOMPATIBLE",)), stage="compilation", target_ref="SH01", now=_NOW
    )
    assert record.domain is FailureDomain.COMPILATION
    assert record.classification is FailureClassification.CONTRACT
    assert record.retry_disposition is RetryDisposition.NEW_EXECUTION_DECISION_REQUIRED


def test_not_admitted_maps_to_admission_domain() -> None:
    record = _n().normalize(ExecutionNotAdmitted("DENIED_BUDGET"), stage="admission", target_ref="SH01", now=_NOW)
    assert record.domain is FailureDomain.ADMISSION
    assert record.classification is FailureClassification.EXPECTED_BLOCK


def test_budget_denied_is_expected_not_system_error() -> None:
    record = _n().normalize(BudgetDeniedError("over budget"), stage="admission", target_ref="SH01", now=_NOW)
    assert record.classification is FailureClassification.EXPECTED_BLOCK
    assert is_system_error(record) is False


def test_unknown_exception_is_a_system_error() -> None:
    record = _n().normalize(RuntimeError("kaboom"), stage="execution", target_ref="SH01", now=_NOW)
    assert record.classification in {FailureClassification.PERMANENT, FailureClassification.INTEGRITY}
    assert is_system_error(record) is True


def test_safe_message_never_carries_the_exception_payload() -> None:
    secret = "sk-live-DEADBEEFsecret"
    record = _n().normalize(RuntimeError(f"auth failed token={secret}"), stage="execution", target_ref="SH01", now=_NOW)
    assert secret not in record.safe_message
    assert record.safe_message


def test_records_carry_attempt_and_decision_refs() -> None:
    record = _n().normalize(
        DirectorTransientError("x"),
        stage="execution",
        target_ref="SH01",
        now=_NOW,
        attempt_ref="ATT-A1",
        decision_refs=["MD:SH01", "ED-A"],
    )
    assert record.attempt_ref == "ATT-A1"
    assert record.decision_refs == ["MD:SH01", "ED-A"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
