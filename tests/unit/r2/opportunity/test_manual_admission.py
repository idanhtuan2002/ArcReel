"""Original manual bindings, upstream clocks and content-free custody metadata."""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from r2.contracts.opportunity import SourceCapabilityGrant
from r2.opportunity.errors import OpportunityError

NOW = datetime(2026, 10, 17, tzinfo=UTC)
ID = "019a0000-0000-7000-8000-000000000001"
H = "sha256:" + "a" * 64
PUBLIC = b"p" * 32


def admission() -> Any:
    return importlib.import_module("r2.opportunity.manual_admission")


def descriptor_data() -> dict[str, Any]:
    return {
        "binding_id": "manual-fixture",
        "binding_version": 1,
        "user_id": "u1",
        "project_name": "show-a",
        "source_kind": "manual-import",
        "source_contract_version": "manual-import.v1",
        "implementation_digest": H,
        "decoder_digest": H,
        "normalizer_digest": H,
        "dependencies_digest": H,
        "config_digest": H,
        "store_namespace": "fixture-store",
        "resolver_namespace": "fixture-resolver",
        "verification_key_id": "fixture-custodian",
        "verification_key_digest": "sha256:" + hashlib.sha256(PUBLIC).hexdigest(),
    }


def rule_data(name: str = "manual-excerpt", *, unbounded: bool = False) -> dict[str, Any]:
    metadata = name == "manual-public-metadata"
    return {
        "data_class": name,
        "refresh_interval_seconds": None if unbounded else (60 if metadata else 30),
        "retention_seconds": None if unbounded else (120 if metadata else 90),
        "delete_on_revoke": True,
        "digest_proof_may_be_retained": metadata,
    }


def object_data(*, metadata: bool = False, unbounded: bool = False) -> dict[str, Any]:
    name = "manual-public-metadata" if metadata else "manual-excerpt"
    r = rule_data(name, unbounded=unbounded)
    return {
        "payload_ref": "opaque-" + name,
        "integrity_ref": "opaque-integrity-" + name,
        "attestation_ref": "opaque-seal-" + name,
        "evidence_kind": "raw-page",
        "data_classes": [name],
        "data_rules": [r],
        "original_clocks": [
            {
                "data_class": name,
                "captured_at": NOW,
                "refresh_due_at": None if unbounded else NOW + timedelta(seconds=r["refresh_interval_seconds"]),
                "retention_due_at": None if unbounded else NOW + timedelta(seconds=r["retention_seconds"]),
            }
        ],
        "retained_material_digest": None,
    }


def request_data() -> dict[str, Any]:
    return {
        "context": {"user_id": "u1", "project_name": "show-a", "actor_id": "human-a", "command_id": ID},
        "request_digest": H,
        "query_id": ID,
        "query_revision": 1,
        "query_digest": H,
        "attempt_id": ID,
        "attempt_version": 2,
        "descriptor": descriptor_data(),
        "opaque_upload_id": "opaque-upload-1",
        "upload_version": 1,
        "publication_key": "opaque-publication-1",
        "data_rules": [rule_data()],
        "original_clocks": object_data()["original_clocks"],
    }


def grant_for(objects: list[dict[str, Any]]) -> SourceCapabilityGrant:
    p = Path(__file__).resolve().parents[3] / "fixtures/r2/opportunity/source_capabilities.json"
    raw = json.loads(p.read_text())["grant"]
    raw["data_rules"] = [r for obj in objects for r in obj["data_rules"]]
    return SourceCapabilityGrant.model_validate(raw)


def envelope_data(*, phase: str = "READY") -> dict[str, Any]:
    m = admission()
    obj = m.SealedObjectDescriptor.model_validate(object_data())
    deadlines = m.effective_admission_deadlines(grant_for([object_data()]), (obj,), admitted_at=NOW)
    body = {
        "schema_version": "m9.manual-admission.v1",
        "request": request_data(),
        "phase": phase,
        "version": 1,
        "claim_ref": "opaque-claim-1",
        "objects": [obj.model_dump()],
        "admitted_at": NOW,
        "deadlines": deadlines.model_dump(),
        "dispatch_claim": None,
    }
    return {**body, "metadata_digest": m.admission_metadata_digest(body)}


def test_exact_binding_resolution_preserves_host_ports_and_registry_is_immutable():
    m = admission()
    descriptor = m.ManualBindingDescriptor.model_validate(descriptor_data())
    port = object()
    binding = m.FrozenManualBinding(
        descriptor=descriptor,
        public_key=PUBLIC,
        source=port,
        upload_admission=port,
        publication=port,
        measure=lambda: descriptor,
    )
    registry = m.ManualBindingRegistry(bindings=(binding,))
    assert registry.resolve_exact(descriptor) is binding
    with pytest.raises(FrozenInstanceError):
        registry.bindings = ()
    with pytest.raises(FrozenInstanceError):
        binding.public_key = b"q" * 32
    with pytest.raises(ValidationError):
        descriptor.binding_version = 2


@pytest.mark.parametrize(
    "field",
    [
        "implementation_digest",
        "decoder_digest",
        "normalizer_digest",
        "dependencies_digest",
        "config_digest",
        "store_namespace",
        "resolver_namespace",
        "verification_key_id",
        "project_name",
        "user_id",
    ],
)
def test_same_label_cannot_hide_changed_live_measurements(field):
    m = admission()
    descriptor = m.ManualBindingDescriptor.model_validate(descriptor_data())
    live = descriptor_data()
    port = object()
    binding = m.FrozenManualBinding(
        descriptor=descriptor,
        public_key=PUBLIC,
        source=port,
        upload_admission=port,
        publication=port,
        measure=lambda: m.ManualBindingDescriptor.model_validate(live),
    )
    registry = m.ManualBindingRegistry(bindings=(binding,))
    assert registry.resolve_exact(descriptor) is binding
    live[field] = "sha256:" + "b" * 64 if field.endswith("digest") else "another"
    with pytest.raises(OpportunityError, match="M9_SOURCE_CAPABILITY_UNAVAILABLE"):
        registry.resolve_exact(descriptor)


def test_resolving_original_descriptor_remeasures_changed_source_bytes(tmp_path):
    m = admission()
    source = tmp_path / "fixture_decoder.py"
    source.write_text("def decode(raw): return raw\n")

    def measure():
        data = descriptor_data()
        data["decoder_digest"] = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
        return m.ManualBindingDescriptor.model_validate(data)

    original = measure()
    port = object()
    binding = m.FrozenManualBinding(
        descriptor=original, public_key=PUBLIC, source=port, upload_admission=port, publication=port, measure=measure
    )
    registry = m.ManualBindingRegistry(bindings=(binding,))
    assert registry.resolve_exact(original) is binding
    source.write_text("def decode(raw): return b'replacement'\n")
    with pytest.raises(OpportunityError, match="M9_SOURCE_CAPABILITY_UNAVAILABLE"):
        registry.resolve_exact(original)


def test_no_binding_fallback_duplicate_identity_or_wrong_public_key():
    m = admission()
    d = m.ManualBindingDescriptor.model_validate(descriptor_data())
    port = object()
    wrong = m.FrozenManualBinding(
        descriptor=d, public_key=b"q" * 32, source=port, upload_admission=port, publication=port, measure=lambda: d
    )
    with pytest.raises(ValueError, match="identities must be unique"):
        m.ManualBindingRegistry(bindings=(wrong, wrong))
    with pytest.raises(OpportunityError):
        m.ManualBindingRegistry(bindings=(wrong,)).resolve_exact(d)
    with pytest.raises(OpportunityError):
        m.ManualBindingRegistry(bindings=()).resolve_exact(d)


def test_mixed_class_deadlines_preserve_original_anchors_and_earliest_bound():
    m = admission()
    data = [object_data(), object_data(metadata=True)]
    objects = tuple(m.SealedObjectDescriptor.model_validate(obj) for obj in data)
    fold = m.effective_admission_deadlines(grant_for(data), objects, admitted_at=NOW + timedelta(seconds=10))
    assert fold.refresh_due_at == NOW + timedelta(seconds=30)
    assert fold.retention_due_at == NOW + timedelta(seconds=90)
    by_class = {item.data_class: item for item in fold.classes}
    excerpt = by_class["manual-excerpt"]
    assert excerpt.admission_refresh_due_at == NOW + timedelta(seconds=40)
    assert excerpt.admission_retention_due_at == NOW + timedelta(seconds=100)
    assert excerpt.original_clocks[0].captured_at == NOW
    assert by_class["manual-public-metadata"].refresh_due_at == NOW + timedelta(seconds=60)
    assert by_class["manual-public-metadata"].retention_due_at == NOW + timedelta(seconds=120)


def test_upstream_expiry_before_admission_is_preserved_and_refused():
    m = admission()
    data = object_data()
    data["original_clocks"][0]["retention_due_at"] = NOW + timedelta(seconds=1)
    obj = m.SealedObjectDescriptor.model_validate(data)
    folded = m.effective_admission_deadlines(grant_for([data]), (obj,), admitted_at=NOW + timedelta(seconds=10))
    assert folded.retention_due_at == NOW + timedelta(seconds=1)
    envelope = envelope_data()
    envelope["request"]["original_clocks"] = data["original_clocks"]
    envelope.update(objects=[data], admitted_at=NOW + timedelta(seconds=10), deadlines=folded.model_dump())
    envelope["metadata_digest"] = m.admission_metadata_digest(envelope)
    retained = m.AdmissionEnvelope.model_validate(envelope)
    with pytest.raises(OpportunityError, match="M9_EVIDENCE_RETENTION_EXPIRED"):
        m.require_admission_access(retained, now=NOW + timedelta(seconds=10), operational=False)


def test_explicitly_unbounded_rules_keep_null_deadlines():
    m = admission()
    data = object_data(unbounded=True)
    folded = m.effective_admission_deadlines(
        grant_for([data]), (m.SealedObjectDescriptor.model_validate(data),), admitted_at=NOW
    )
    assert folded.refresh_due_at is None
    assert folded.retention_due_at is None


@pytest.mark.parametrize("fault", ["missing_clock", "extra_clock", "bounded_null", "future_anchor", "wrong_policy"])
def test_missing_or_incompatible_class_clock_authority_is_refused(fault):
    m = admission()
    data = object_data()
    if fault == "missing_clock":
        data["original_clocks"] = []
    elif fault == "extra_clock":
        data["original_clocks"].append({**data["original_clocks"][0], "data_class": "other"})
    elif fault == "bounded_null":
        data["original_clocks"][0]["retention_due_at"] = None
    elif fault == "future_anchor":
        data["original_clocks"][0]["captured_at"] = NOW + timedelta(seconds=1)
    grant = grant_for([object_data()])
    if fault == "wrong_policy":
        data["data_rules"][0]["retention_seconds"] = 180
    if fault in {"missing_clock", "extra_clock", "bounded_null"}:
        with pytest.raises(ValidationError):
            m.SealedObjectDescriptor.model_validate(data)
    else:
        obj = m.SealedObjectDescriptor.model_validate(data)
        with pytest.raises(OpportunityError, match="M9_SOURCE_POLICY_FORBIDDEN"):
            m.effective_admission_deadlines(grant, (obj,), admitted_at=NOW)


@pytest.mark.parametrize(
    ("seconds", "operational", "code"),
    [
        (29, True, None),
        (30, True, "M9_EVIDENCE_STALE"),
        (30, False, None),
        (89, False, None),
        (90, False, "M9_EVIDENCE_RETENTION_EXPIRED"),
        (90, True, "M9_EVIDENCE_RETENTION_EXPIRED"),
    ],
)
def test_exact_access_boundaries(seconds, operational, code):
    m = admission()
    envelope = m.AdmissionEnvelope.model_validate(envelope_data())
    if code:
        with pytest.raises(OpportunityError, match=code):
            m.require_admission_access(envelope, now=NOW + timedelta(seconds=seconds), operational=operational)
    else:
        assert (
            m.require_admission_access(envelope, now=NOW + timedelta(seconds=seconds), operational=operational) is None
        )


@pytest.mark.parametrize("phase", ["RESERVED", "CLEANUP_PENDING", "ERASED"])
def test_non_ready_admissions_cannot_be_read(phase):
    m = admission()
    data = envelope_data(phase=phase)
    if phase == "RESERVED":
        data.update(objects=[], claim_ref=None, admitted_at=None, deadlines=None)
        data["metadata_digest"] = m.admission_metadata_digest(data)
    envelope = m.AdmissionEnvelope.model_validate(data)
    with pytest.raises(OpportunityError):
        m.require_admission_access(envelope, now=NOW, operational=False)


@pytest.mark.parametrize("fault", ["proof", "mixed_proof", "missing_ready", "changed_metadata", "cross_scope", "naive"])
def test_metadata_cannot_retain_forbidden_proof_or_invent_admission(fault):
    m = admission()
    if fault in {"proof", "mixed_proof"}:
        data = object_data()
        data["retained_material_digest"] = H
        if fault == "mixed_proof":
            meta = object_data(metadata=True)
            for field in ("data_classes", "data_rules", "original_clocks"):
                data[field] += meta[field]
        with pytest.raises(ValidationError):
            m.SealedObjectDescriptor.model_validate(data)
        return
    data = envelope_data()
    if fault == "missing_ready":
        data["objects"] = []
        data["metadata_digest"] = m.admission_metadata_digest(data)
    elif fault == "changed_metadata":
        data["version"] = 2
    elif fault == "cross_scope":
        data["request"]["descriptor"]["project_name"] = "foreign"
    else:
        data["admitted_at"] = NOW.replace(tzinfo=None)
    with pytest.raises(ValidationError):
        m.AdmissionEnvelope.model_validate(data)


def test_metadata_digest_is_order_independent_and_binds_whole_envelope():
    m = admission()
    data = envelope_data()
    envelope = m.AdmissionEnvelope.model_validate(data)
    assert m.admission_metadata_digest(envelope) == data["metadata_digest"]
    changed = {**data, "version": 2}
    assert m.admission_metadata_digest(changed) != data["metadata_digest"]


def test_metadata_canonicalization_preserves_multi_object_roundtrip_and_permutations():
    m = admission()
    data = envelope_data()
    excerpt, metadata = object_data(), object_data(metadata=True)
    for field in ("data_rules", "original_clocks"):
        data["request"][field] = excerpt[field] + metadata[field]
    data["objects"] = [metadata, excerpt]
    folded = m.effective_admission_deadlines(
        grant_for([excerpt, metadata]),
        tuple(m.SealedObjectDescriptor.model_validate(obj) for obj in data["objects"]),
        admitted_at=NOW,
    )
    data["deadlines"] = folded.model_dump()
    digest = m.admission_metadata_digest(data)
    data["objects"].reverse()
    assert m.admission_metadata_digest(data) == digest
    envelope = m.AdmissionEnvelope.model_validate({**data, "metadata_digest": digest})
    assert m.AdmissionEnvelope.model_validate_json(envelope.model_dump_json()) == envelope


@pytest.mark.parametrize("field", ["phase", "admitted_at", "objects", "deadlines"])
def test_cleanup_cannot_discard_original_admission_anchors(field):
    m = admission()
    data = envelope_data(phase="CLEANUP_PENDING")
    if field == "phase":
        data[field] = "PUBLISHED_UNATTACHED"
    elif field == "objects":
        data[field] = []
    else:
        data[field] = None
    with pytest.raises(ValidationError):
        m.AdmissionEnvelope.model_validate(data)


def test_metadata_receipt_projection_never_contains_material_proof():
    m = admission()
    data = object_data(metadata=True)
    data["retained_material_digest"] = H
    obj = m.SealedObjectDescriptor.model_validate(data)
    ref = m.PublicationObjectRef.from_descriptor(obj)
    assert H not in ref.model_dump_json()
    with pytest.raises(ValidationError):
        m.PublicationObjectRef.model_validate(obj.model_dump())


def test_read_permits_and_deletion_receipts_require_exact_original_bounds():
    m = admission()
    permit = {
        "lease_id": "opaque-lease",
        "user_id": "u1",
        "project_name": "show-a",
        "attempt_id": ID,
        "envelope_version": 1,
        "operational": True,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(seconds=30),
        "access_deadline": NOW + timedelta(seconds=30),
    }
    assert m.AdmissionReadPermit.model_validate(permit).expires_at == NOW + timedelta(seconds=30)
    with pytest.raises(ValidationError):
        m.AdmissionReadPermit.model_validate({**permit, "expires_at": NOW + timedelta(seconds=31)})
    closure = {
        "closure_id": "opaque-closure",
        "user_id": "u1",
        "project_name": "show-a",
        "attempt_id": ID,
        "attempt_version": 2,
        "envelope_version": 1,
        "phase": "CLEANUP_PENDING",
        "version": 1,
        "object_refs": ["opaque-payload", "opaque-seal"],
        "fenced_at": NOW,
    }
    intent = m.AdmissionClosureIntent.model_validate(closure)
    receipt = {
        "closure": intent.model_dump(),
        "absent_refs": ["opaque-payload", "opaque-seal"],
        "retained_proofs": [],
        "deleted_at": NOW,
    }
    assert m.AdmissionDeletionReceipt.model_validate(receipt).closure == intent
    with pytest.raises(ValidationError):
        m.AdmissionDeletionReceipt.model_validate({**receipt, "absent_refs": ["opaque-payload"]})


@pytest.mark.parametrize("fault", [None, "publication", "version", "policy", "refs", "classes", "clock"])
def test_publication_preserves_reserved_identity_policy_and_opaque_ref_closure(fault):
    m = admission()
    data = {
        "request": request_data(),
        "publication_key": "opaque-publication-1",
        "claim_ref": "opaque-claim-1",
        "upload_version": 1,
        "objects": [object_data()],
    }
    if fault == "publication":
        data["publication_key"] = "different-publication"
    elif fault == "version":
        data["upload_version"] = 2
    elif fault == "policy":
        data["objects"][0]["data_rules"][0]["retention_seconds"] = 180
    elif fault == "refs":
        data["objects"][0]["attestation_ref"] = data["objects"][0]["payload_ref"]
    elif fault == "classes":
        data["objects"] = [object_data(metadata=True)]
    elif fault == "clock":
        data["objects"][0]["original_clocks"][0]["retention_due_at"] = NOW + timedelta(seconds=60)
    if fault:
        with pytest.raises(ValidationError):
            m.PublishedAdmission.model_validate(data)
    else:
        published = m.PublishedAdmission.model_validate(data)
        assert published.request.publication_key == published.publication_key
        assert published.objects[0].original_clocks == published.request.original_clocks
