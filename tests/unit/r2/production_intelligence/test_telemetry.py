"""D10 — non-authoritative production telemetry projection."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from r2.contracts import FailureClassification, FailureDomain, ProductionEvent, RetryDisposition
from r2.production_intelligence import telemetry as telemetry_module
from r2.production_intelligence.failure import FailureNormalizer
from r2.production_intelligence.telemetry import ProductionTelemetryProjector, metric_labels

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
_MUTATION_WORDS = ("promote", "approve", "commit", "mutate", "write", "set_master", "update_manifest", "save")
_FORBIDDEN_IMPORT_ROOTS = (
    "lib.artifact_manifest",
    "lib.db",
    "r2.production.approval_service",
    "r2.production.artifact_bridge",
)


def _projector() -> ProductionTelemetryProjector:
    return ProductionTelemetryProjector(production_run_id="run-1")


def test_project_failure_produces_a_referencing_event() -> None:
    record = FailureNormalizer().normalize_outcome(
        domain=FailureDomain.CAPABILITY, reason_code="CAPABILITY_UNKNOWN", target_ref="SH01", now=_NOW
    )
    event = _projector().project_failure(record)
    assert isinstance(event, ProductionEvent)
    assert event.target_ref == "SH01"
    assert event.reason_code == "CAPABILITY_UNKNOWN"
    assert event.production_run_id == "run-1"


def test_attempt_history_keeps_every_attempt_observable_while_the_shot_succeeds() -> None:
    p = _projector()
    events = [
        p.project_attempt(
            target_ref="SH01",
            method_decision_ref="MD:SH01",
            execution_decision_ref="ED-A",
            attempt_ref="ATT-A1",
            stage="execution",
            outcome="FAILED",
            now=_NOW,
        ),
        p.project_attempt(
            target_ref="SH01",
            method_decision_ref="MD:SH01",
            execution_decision_ref="ED-A",
            attempt_ref="ATT-A2",
            stage="execution",
            outcome="FAILED",
            now=_NOW,
        ),
        p.project_attempt(
            target_ref="SH01",
            method_decision_ref="MD:SH01",
            execution_decision_ref="ED-B",
            attempt_ref="ATT-B1",
            stage="execution",
            outcome="SUCCEEDED",
            now=_NOW,
        ),
        p.project_shot_outcome(target_ref="SH01", outcome="SUCCEEDED", now=_NOW),
    ]
    assert len({e.event_id for e in events}) == 4
    assert [e.attempt_ref for e in events[:3]] == ["ATT-A1", "ATT-A2", "ATT-B1"]
    assert events[-1].outcome == "SUCCEEDED"
    assert {"ED-A", "ED-B"} <= {ref for e in events for ref in e.decision_refs}


def test_metric_labels_are_bounded_and_carry_no_identifiers_or_secrets() -> None:
    record = FailureNormalizer().normalize_outcome(
        domain=FailureDomain.ADMISSION, reason_code="DENIED_BUDGET", target_ref="SH01-secret-xyz", now=_NOW
    )
    labels = metric_labels(_projector().project_failure(record))
    assert "SH01-secret-xyz" not in labels.values()
    assert set(labels) <= {"stage", "outcome", "reason_code", "event_type"}


def test_projector_has_no_authority_mutation_surface() -> None:
    names = dir(ProductionTelemetryProjector)
    assert not any(any(word in name.lower() for word in _MUTATION_WORDS) for name in names)


def test_telemetry_module_imports_no_authority_layer() -> None:
    text = Path(telemetry_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(text)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    assert not any(m.startswith(root) for m in modules for root in _FORBIDDEN_IMPORT_ROOTS)


def test_disposition_is_not_a_telemetry_concern() -> None:
    # Telemetry projects state; it never assigns a retry disposition itself.
    assert RetryDisposition  # imported for documentation of the boundary
    record = FailureNormalizer().normalize_outcome(
        domain=FailureDomain.METHOD, reason_code="BLOCKED", target_ref="SH01", now=_NOW
    )
    event = _projector().project_failure(record)
    assert event.outcome == FailureClassification.EXPECTED_BLOCK.value


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
