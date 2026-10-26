"""Frozen port descriptors bind scope and placement without granting current authority."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, get_type_hints

import pytest
from pydantic import ValidationError

from r2.contracts import quality as q
from r2.quality import ports
from r2.quality.digests import compute_digest
from tests.unit.r2.contracts.test_quality import DIGEST, NOW, observation_data, subject_data
from tests.unit.r2.quality.test_quality_digests import examples


def probe_data() -> dict[str, Any]:
    profile = examples()["m10.quality-profile.v1"]
    slot = profile["policy"]["assessment_requirements"][0]["slots"][0]
    slot.update(slot_id="technical", kind="TECHNICAL", assessor_class="DETERMINISTIC", rule_ids=["probe"])
    profile["policy"]["assessment_requirements"][0]["slots"].append({**slot, "slot_id": "other"})
    profile["policy"]["assessment_requirements"][0]["minimum_satisfied_slots"] = 2
    return {
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "independent-operator",
        "execution_ref": "m7-execution",
        "requirement_id": "review-required",
        "slot_id": "technical",
        "subject": subject_data(),
        "profile": profile,
        "rule": profile["policy"]["probe_rules"][0],
    }


def factual_data() -> dict[str, Any]:
    return {
        "user_id": "owner",
        "project_name": "project",
        "subject_digest": DIGEST,
        "claim_ledger_projection_ref": "claims",
        "claim_ledger_projection_digest": DIGEST,
        "research_pack_ref": "pack",
        "research_pack_digest": DIGEST,
        "correction_head_digest": DIGEST,
        "coverage_digest": DIGEST,
        "withdrawn": False,
        "checked_at": NOW,
        "validity_receipt_ref": "receipt",
        "validity_receipt_digest": DIGEST,
    }


def factual_request() -> ports.FactualReadRequest:
    data = factual_data()
    return ports.FactualReadRequest.model_validate(
        {
            k: data[k]
            for k in ("user_id", "project_name", "subject_digest", "claim_ledger_projection_ref", "research_pack_ref")
        }
        | {"actor_id": "operator"}
    )


def test_explicit_probe_placement_allows_distinct_actor_and_two_slots_using_one_rule() -> None:
    request = ports.ProbeRequest.model_validate(probe_data())
    assert request.actor_id != request.profile.created_by
    other = ports.ProbeRequest.model_validate(probe_data() | {"slot_id": "other"})
    assert other.rule == request.rule
    assert other.slot_id != request.slot_id
    assert ports.ProbeReceipt is q.TechnicalObservation


@pytest.mark.parametrize(
    "case",
    [
        "user",
        "project",
        "subject_scope",
        "rule_body",
        "requirement",
        "slot",
        "kind",
        "assessor",
        "slot_rule",
        "missing_selector",
    ],
)
def test_probe_descriptor_refuses_wrong_scope_rule_or_placement(case: str) -> None:
    data = probe_data()
    if case in {"user", "project"}:
        data["user_id" if case == "user" else "project_name"] = "wrong"
    elif case == "subject_scope":
        data["subject"]["master_binding"]["user_id"] = "wrong"
    elif case == "rule_body":
        data["rule"] = {**data["rule"], "max_runtime_ms": 2000}
    elif case in {"requirement", "slot"}:
        data[case + "_id"] = "wrong"
    elif case == "missing_selector":
        del data["slot_id"]
    else:
        slot = data["profile"]["policy"]["assessment_requirements"][0]["slots"][0]
        slot[{"kind": "kind", "assessor": "assessor_class", "slot_rule": "rule_ids"}[case]] = {
            "kind": "NARRATIVE",
            "assessor": "HUMAN",
            "slot_rule": ["review"],
        }[case]
    with pytest.raises(ValidationError):
        ports.ProbeRequest.model_validate(data)


def test_probe_result_binding_uses_a1_digest_and_exact_selected_slot() -> None:
    request = ports.ProbeRequest.model_validate(probe_data())
    observation = q.TechnicalObservation.model_validate(
        observation_data()
        | {"slot_id": request.slot_id, "subject_digest": compute_digest("m10.assessed-subject.v1", request.subject)}
    )
    assert ports.validate_probe_result_binding(request, observation) == observation
    for key, value in {
        "requirement_id": "wrong",
        "slot_id": "other",
        "rule_id": "review",
        "config_digest": "sha256:" + "b" * 64,
        "subject_digest": DIGEST,
        "observed_at": "CANARY_SECRET",
    }.items():
        with pytest.raises(ValueError, match=r"^probe result binding invalid$"):
            ports.validate_probe_result_binding(request, observation.model_copy(update={key: value}))


def test_factual_result_binding_retains_withdrawal_but_rejects_cross_scope_or_refs() -> None:
    request = factual_request()
    result = ports.FactualReadProjection.model_validate(factual_data() | {"withdrawn": True})
    assert ports.validate_factual_result_binding(request, result).withdrawn is True
    for key in (
        "user_id",
        "project_name",
        "claim_ledger_projection_ref",
        "research_pack_ref",
        "subject_digest",
        "checked_at",
    ):
        value = "sha256:" + "b" * 64 if key == "subject_digest" else "CANARY_SECRET"
        with pytest.raises(ValueError, match=r"^factual result binding invalid$"):
            ports.validate_factual_result_binding(request, result.model_copy(update={key: value}))


def test_raw_factual_projection_has_exact_slot_free_fieldset_and_no_authority_flags() -> None:
    assert set(ports.FactualReadProjection.model_fields) == set(factual_data())
    assert len(ports.FactualReadProjection.model_fields) == 13
    for field in ("observation", "requirement_id", "slot_id", "assessor_identity", "status", "current", "valid"):
        with pytest.raises(ValidationError):
            ports.FactualReadProjection.model_validate(factual_data() | {field: True})


@pytest.mark.parametrize(
    "descriptor", ["ProbeRequest", "FactualReadRequest", "FactualReadProjection", "EvidenceReference"]
)
def test_descriptors_are_deeply_frozen_exact_and_roundtrip(descriptor: str) -> None:
    model = getattr(ports, descriptor)
    data = {
        "ProbeRequest": probe_data(),
        "FactualReadRequest": factual_request().model_dump(),
        "FactualReadProjection": factual_data(),
        "EvidenceReference": {"user_id": "owner", "project_name": "project", "ref": "evidence", "digest": DIGEST},
    }[descriptor]
    instance = model.model_validate(data)
    assert isinstance(instance, q.M10ContractModel)
    assert model.model_validate_json(instance.model_dump_json()) == instance
    with pytest.raises(ValidationError):
        instance.user_id = "wrong"
    with pytest.raises(ValidationError):
        model.model_validate(data | {"user_id": " owner"})
    with pytest.raises(ValidationError):
        model.model_validate(data | {"unexpected": True})
    if descriptor == "ProbeRequest":
        with pytest.raises(ValidationError):
            instance.profile.policy.probe_rules[0].config_digest = DIGEST


@pytest.mark.parametrize(
    "changes", [{"withdrawn": 1}, {"checked_at": "2026-10-27T00:00:00"}, {"validity_receipt_digest": "bad"}]
)
def test_factual_projection_requires_strict_withdrawal_aware_time_and_digest(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ports.FactualReadProjection.model_validate(factual_data() | changes)


def test_exact_async_protocol_surface_contains_only_stubs() -> None:
    expected = {
        "QualityProfileReadPort": (
            "get_revision",
            ("self", "user_id", "project_name", "profile_id", "revision"),
            q.QualityProfileRevision | None,
        ),
        "QualityProfilePublicationService": ("publish", ("self", "request"), q.QualityProfileRevision),
        "QualityProbePort": ("observe", ("self", "request"), q.TechnicalObservation),
        "QualityRunService": ("complete", ("self", "command"), q.QualityRun),
        "ProfilePublicationCustodianPort": (
            "authorize_publication",
            ("self", "request"),
            q.ProfilePublicationAuthorizationLease,
        ),
        "QualityDispositionCustodianPort": (
            "authorize_disposition",
            ("self", "request"),
            q.DispositionAuthorizationLease,
        ),
        "FactualReadPort": ("read_current", ("self", "request"), ports.FactualReadProjection | None),
        "EvidenceReferencePort": (
            "get_exact",
            ("self", "user_id", "project_name", "ref", "expected_digest"),
            ports.EvidenceReference | None,
        ),
    }
    tree = ast.parse(Path(ports.__file__).read_text())
    protocols = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(isinstance(base, ast.Name) and base.id == "Protocol" for base in node.bases)
    }
    input_types = {
        "QualityProfileReadPort": {
            "user_id": q.ExactIdentity,
            "project_name": q.ExactIdentity,
            "profile_id": q.M10Uuid7,
            "revision": int,
        },
        "QualityProfilePublicationService": {"request": q.ProfilePublicationAuthorizationRequest},
        "QualityProbePort": {"request": ports.ProbeRequest},
        "QualityRunService": {"command": q.CompleteRunCommand},
        "ProfilePublicationCustodianPort": {"request": q.ProfilePublicationAuthorizationRequest},
        "QualityDispositionCustodianPort": {"request": q.DispositionAuthorizationRequest},
        "FactualReadPort": {"request": ports.FactualReadRequest},
        "EvidenceReferencePort": {
            "user_id": q.ExactIdentity,
            "project_name": q.ExactIdentity,
            "ref": q.ExactIdentity,
            "expected_digest": ports.Sha256Digest,
        },
    }
    assert set(protocols) == set(expected)
    for name, (method, parameters, return_type) in expected.items():
        fn = getattr(getattr(ports, name), method)
        assert inspect.iscoroutinefunction(fn)
        assert tuple(inspect.signature(fn).parameters) == parameters
        assert get_type_hints(fn, include_extras=True) == input_types[name] | {"return": return_type}
        methods = [node for node in protocols[name].body if isinstance(node, ast.AsyncFunctionDef)]
        assert len(methods) == 1
        assert methods[0].name == method
        assert len(methods[0].body) == 1
        assert isinstance(methods[0].body[0], ast.Expr)
        assert methods[0].body[0].value.value is Ellipsis
        if name in {"QualityProfileReadPort", "EvidenceReferencePort"}:
            assert all(
                p.kind is inspect.Parameter.KEYWORD_ONLY for p in list(inspect.signature(fn).parameters.values())[1:]
            )
