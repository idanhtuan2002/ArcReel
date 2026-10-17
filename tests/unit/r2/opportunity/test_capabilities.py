from __future__ import annotations

import importlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from r2.contracts.opportunity import (
    CapabilityEvaluationRequest,
    EffectiveCapabilityEvaluation,
    SourceCapabilityGrant,
    SourcePageResult,
)
from r2.opportunity import digests
from r2.opportunity.errors import OpportunityError

NOW = datetime(2026, 10, 17, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parents[3] / "fixtures/r2/opportunity"


def _module() -> Any:
    assert importlib.util.find_spec("r2.opportunity.capabilities") is not None, "B1 capability fold is missing"
    return importlib.import_module("r2.opportunity.capabilities")


def _authority() -> tuple[SourceCapabilityGrant, EffectiveCapabilityEvaluation, CapabilityEvaluationRequest]:
    raw = json.loads((FIXTURES / "source_capabilities.json").read_bytes())
    return (
        SourceCapabilityGrant.model_validate(raw["grant"]),
        EffectiveCapabilityEvaluation.model_validate(raw["evaluation"]),
        CapabilityEvaluationRequest.model_validate(raw["request"]),
    )


def _resign(
    g: SourceCapabilityGrant, e: EffectiveCapabilityEvaluation, r: CapabilityEvaluationRequest
) -> tuple[SourceCapabilityGrant, EffectiveCapabilityEvaluation, CapabilityEvaluationRequest]:
    g = SourceCapabilityGrant.model_validate({name: getattr(g, name) for name in SourceCapabilityGrant.model_fields})
    e = EffectiveCapabilityEvaluation.model_validate(
        {name: getattr(e, name) for name in EffectiveCapabilityEvaluation.model_fields}
    )
    g = g.model_copy(update={"grant_digest": digests.digest_capability_grant(g)})
    r = r.model_copy(update={"grant_digest": g.grant_digest})
    e = e.model_copy(
        update={
            "grant_digest": g.grant_digest,
            "condition_evidence_digest": digests.digest_condition_evidence(
                grant_id=g.grant_id,
                grant_version=g.grant_version,
                grant_digest=g.grant_digest,
                condition_evidence=e.condition_evidence,
            ),
        }
    )
    e = e.model_copy(update={"evaluation_digest": digests.digest_capability_evaluation(e, actor_id=r.actor_id)})
    return g, e, r


def _page(classes: tuple[str, ...] = ("manual-excerpt", "manual-public-metadata")) -> SourcePageResult:
    return SourcePageResult(
        provider_request_id=None,
        next_cursor=None,
        raw_payload=b"{}",
        raw_media_type="application/json",
        source_native_ids=(),
        data_classes=classes,
        returned_record_count=0,
        provider_observed_at=NOW - timedelta(days=300),
        terminal_page=True,
    )


def test_exact_host_fixture_is_executable_without_mutating_authority() -> None:
    g, e, r = _authority()
    before = g.model_dump_json(), e.model_dump_json()
    assert _module().validate_capability(g, e, r, now=NOW) is None
    assert (g.model_dump_json(), e.model_dump_json()) == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", "other"),
        ("project_name", "other"),
        ("actor_id", "other"),
        ("grant_id", "other"),
        ("grant_version", 2),
        ("grant_digest", "sha256:" + "b" * 64),
        ("source_kind", "other"),
        ("operation", "other"),
        ("purpose", "AUDIENCE"),
        ("account_binding_digest", "sha256:" + "b" * 64),
    ],
)
def test_request_substitution_never_reuses_an_effective_evaluation(field: str, value: object) -> None:
    g, e, r = _authority()
    with pytest.raises(OpportunityError):
        _module().validate_capability(g, e, r.model_copy(update={field: value}), now=NOW)


@pytest.mark.parametrize("state", ["DISABLED", "UNAVAILABLE", "EXPIRED", "REVOKED"])
def test_non_enabled_grant_refuses_even_with_valid_digests(state: str) -> None:
    g, e, r = _authority()
    g, e, r = _resign(g.model_copy(update={"state": state}), e, r)
    with pytest.raises(OpportunityError, match="M9_SOURCE_CAPABILITY_UNAVAILABLE"):
        _module().validate_capability(g, e, r, now=NOW)


@pytest.mark.parametrize(
    "target",
    [
        "grant_expiry",
        "grant_refresh",
        "policy_expiry",
        "evaluation_expiry",
        "grant_future",
        "evaluation_future",
        "policy_future",
    ],
)
@pytest.mark.parametrize("offset", [0, 1])
def test_currentness_refuses_at_and_beyond_deadline_or_before_issue(target: str, offset: int) -> None:
    g, e, r = _authority()
    boundary = NOW - timedelta(seconds=offset)
    if target == "grant_expiry":
        g = g.model_copy(update={"expires_at": boundary})
    elif target == "grant_refresh":
        g = g.model_copy(update={"refresh_after": boundary})
    elif target == "policy_expiry":
        g = g.model_copy(
            update={"policy_documents": (g.policy_documents[0].model_copy(update={"expires_at": boundary}),)}
        )
    elif target == "evaluation_expiry":
        e = e.model_copy(update={"expires_at": boundary})
    elif target == "grant_future":
        g = g.model_copy(update={"issued_at": NOW + timedelta(seconds=offset + 1)})
    elif target == "evaluation_future":
        e = e.model_copy(update={"evaluated_at": NOW + timedelta(seconds=offset + 1)})
    else:
        g = g.model_copy(
            update={
                "policy_documents": (
                    g.policy_documents[0].model_copy(update={"effective_at": NOW + timedelta(seconds=offset + 1)}),
                )
            }
        )
    g, e, r = _resign(g, e, r)
    with pytest.raises(OpportunityError):
        _module().validate_capability(g, e, r, now=NOW)


@pytest.mark.parametrize(
    "fault",
    [
        "grant_digest",
        "evaluation_digest",
        "condition_digest",
        "forbidden",
        "effective_conditional",
        "manual_credential",
        "manual_account",
        "missing_condition",
        "unknown_condition",
        "false_condition",
        "numeric_condition",
    ],
)
def test_corrupt_or_unresolved_permission_is_not_executable(fault: str) -> None:
    g, e, r = _authority()
    if fault.startswith(("missing_", "unknown_", "false_", "numeric_")):
        g = g.model_copy(update={"permission": "CONDITIONAL", "conditions": ({"kind": "synthetic-human-import"},)})
        proof = (
            ()
            if fault == "missing_condition"
            else ({"unknown": True},)
            if fault == "unknown_condition"
            else (
                {
                    "condition": {"kind": "synthetic-human-import"},
                    "satisfied": 1 if fault == "numeric_condition" else False,
                },
            )
        )
        e = e.model_copy(update={"condition_evidence": proof})
    elif fault == "forbidden":
        g = g.model_copy(update={"permission": "FORBIDDEN"})
    elif fault == "effective_conditional":
        e = e.model_copy(update={"effective_permission": "CONDITIONAL"})
    elif fault == "manual_credential":
        g = g.model_copy(update={"credential_ref": "Bearer canary-secret"})
    elif fault == "manual_account":
        g = g.model_copy(update={"account_binding_digest": "sha256:" + "b" * 64})
    g, e, r = _resign(g, e, r)
    if fault == "grant_digest":
        g = g.model_copy(update={"grant_digest": "sha256:" + "b" * 64})
    elif fault == "evaluation_digest":
        e = e.model_copy(update={"evaluation_digest": "sha256:" + "b" * 64})
    elif fault == "condition_digest":
        e = e.model_copy(
            update={"condition_evidence_digest": "sha256:" + "b" * 64, "evaluation_digest": "sha256:" + "b" * 64}
        )
    with pytest.raises(OpportunityError) as caught:
        _module().validate_capability(g, e, r, now=NOW)
    assert "canary-secret" not in str(caught.value)


def test_host_must_prove_each_condition_in_order() -> None:
    g, e, r = _authority()
    condition = {"kind": "synthetic-human-import"}
    g = g.model_copy(update={"permission": "CONDITIONAL", "conditions": (condition,)})
    e = e.model_copy(update={"condition_evidence": ({"condition": condition, "satisfied": True},)})
    g, e, r = _resign(g, e, r)
    assert _module().validate_capability(g, e, r, now=NOW) is None


def test_page_class_clocks_use_only_first_database_admission_anchor() -> None:
    g, _, _ = _authority()
    clocks = _module().page_clocks(_page(), g, captured_at=NOW)
    assert {c.data_class: (c.captured_at, c.refresh_due_at, c.retention_due_at) for c in clocks} == {
        "manual-excerpt": (NOW, NOW + timedelta(seconds=30), NOW + timedelta(seconds=90)),
        "manual-public-metadata": (NOW, NOW + timedelta(seconds=60), NOW + timedelta(seconds=120)),
    }
    assert _module().page_deadlines(clocks) == (NOW + timedelta(seconds=30), NOW + timedelta(seconds=90))
    assert _module().retain_page_proof(_page(), g) is False
    assert _module().retain_page_proof(_page(("manual-public-metadata",)), g) is True


@pytest.mark.parametrize(
    ("seconds", "operational", "code"),
    [
        (29, True, None),
        (30, True, "M9_EVIDENCE_STALE"),
        (31, True, "M9_EVIDENCE_STALE"),
        (89, False, None),
        (90, False, "M9_EVIDENCE_RETENTION_EXPIRED"),
        (91, False, "M9_EVIDENCE_RETENTION_EXPIRED"),
    ],
)
def test_clock_boundary_and_replay_do_not_extend_retention(seconds: int, operational: bool, code: str | None) -> None:
    g, _, _ = _authority()
    clocks = _module().page_clocks(_page(), g, captured_at=NOW)
    if code:
        with pytest.raises(OpportunityError, match=code):
            _module().require_clocks_current(clocks, now=NOW + timedelta(seconds=seconds), operational=operational)
    else:
        assert (
            _module().require_clocks_current(clocks, now=NOW + timedelta(seconds=seconds), operational=operational)
            is None
        )
    assert clocks[0].captured_at == NOW


def test_explicit_null_rule_is_unbounded_and_missing_rule_refuses() -> None:
    g, _, _ = _authority()
    rules = tuple(
        r.model_copy(update={"refresh_interval_seconds": None, "retention_seconds": None}) for r in g.data_rules
    )
    clocks = _module().page_clocks(_page(), g.model_copy(update={"data_rules": rules}), captured_at=NOW)
    assert _module().page_deadlines(clocks) == (None, None)
    assert _module().require_clocks_current(clocks, now=NOW + timedelta(days=1000), operational=True) is None
    with pytest.raises(OpportunityError, match="M9_SOURCE_POLICY_FORBIDDEN"):
        _module().page_clocks(_page(("missing",)), g, captured_at=NOW)
