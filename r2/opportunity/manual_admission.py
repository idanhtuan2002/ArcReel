"""Content-free bindings for independently authenticated manual material."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from r2.advanced_creative.digests import canonical_json_bytes
from r2.contracts.advanced_creative import Sha256Digest
from r2.contracts.opportunity import (
    CommandContext,
    EvidenceDataClassClock,
    M9ContractModel,
    Slug,
    SourceCapabilityGrant,
    SourceDataRule,
)
from r2.opportunity.errors import OpportunityError, StopCode

if TYPE_CHECKING:
    from r2.opportunity.manual_admission_ports import ManualPublicationPort, ManualUploadAdmissionPort
    from r2.opportunity.ports import MarketSourcePort


class SealExpectation(M9ContractModel):
    schema_version: Literal["m9.manual-material-seal.v1"]
    source_kind: Literal["manual-import"]
    source_contract_version: Literal["manual-import.v1"]
    verification_key_id: Slug
    context: CommandContext
    request_digest: Sha256Digest
    query_id: str
    query_revision: int = Field(ge=1, strict=True)
    query_digest: Sha256Digest
    attempt_id: str
    attempt_version: int = Field(ge=1, strict=True)
    publication_key: str
    claim_ref: str
    upload_version: int = Field(ge=1, strict=True)
    descriptor_digest: Sha256Digest
    payload_ref: str
    integrity_ref: str
    attestation_ref: str
    evidence_kind: Slug
    data_classes: tuple[Slug, ...] = Field(min_length=1)
    data_rules: tuple[SourceDataRule, ...] = Field(min_length=1)
    original_clocks: tuple[EvidenceDataClassClock, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_class_closure(self) -> Self:
        _validate_classes(self.data_classes, self.data_rules, self.original_clocks)
        return self


class ManualBindingDescriptor(M9ContractModel):
    binding_id: Slug
    binding_version: int = Field(ge=1, strict=True)
    user_id: str
    project_name: str
    source_kind: Literal["manual-import"]
    source_contract_version: Literal["manual-import.v1"]
    implementation_digest: Sha256Digest
    decoder_digest: Sha256Digest
    normalizer_digest: Sha256Digest
    dependencies_digest: Sha256Digest
    config_digest: Sha256Digest
    store_namespace: Slug
    resolver_namespace: Slug
    verification_key_id: Slug
    verification_key_digest: Sha256Digest


def _digest(domain: bytes, value: object) -> str:
    return "sha256:" + hashlib.sha256(domain + canonical_json_bytes(value)).hexdigest()


def manual_binding_digest(descriptor: ManualBindingDescriptor) -> str:
    return _digest(b"m9.manual-binding.v1\x00", descriptor)


@dataclass(frozen=True, slots=True)
class FrozenManualBinding:
    """Host-only capabilities; measurement is supplied by trusted deployment composition."""

    descriptor: ManualBindingDescriptor
    public_key: bytes = field(repr=False)
    source: MarketSourcePort = field(repr=False)
    upload_admission: ManualUploadAdmissionPort = field(repr=False)
    publication: ManualPublicationPort = field(repr=False)
    measure: Callable[[], ManualBindingDescriptor] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ManualBindingRegistry:
    bindings: tuple[FrozenManualBinding, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bindings", tuple(self.bindings))
        keys = [
            (b.descriptor.user_id, b.descriptor.project_name, b.descriptor.binding_id, b.descriptor.binding_version)
            for b in self.bindings
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("manual binding identities must be unique")

    def resolve_exact(self, descriptor: ManualBindingDescriptor) -> FrozenManualBinding:
        """Re-measure the selected deployment binding; never select by an alias alone."""
        try:
            descriptor = ManualBindingDescriptor.model_validate(descriptor.model_dump())
            for binding in self.bindings:
                if binding.descriptor != descriptor:
                    continue
                live = ManualBindingDescriptor.model_validate(binding.measure().model_dump())
                if (
                    live != descriptor
                    or type(binding.public_key) is not bytes
                    or len(binding.public_key) != 32
                    or "sha256:" + hashlib.sha256(binding.public_key).hexdigest() != descriptor.verification_key_digest
                ):
                    break
                return binding
        except Exception:
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE) from None
        raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)


def _validate_classes(
    classes: Sequence[str], rules: Sequence[SourceDataRule], clocks: Sequence[EvidenceDataClassClock]
) -> None:
    selected = set(classes)
    if not selected or len(selected) != len(classes):
        raise ValueError("declared data classes must be nonempty and unique")
    if len(rules) != len(selected) or {r.data_class for r in rules} != selected:
        raise ValueError("data rules must exactly cover declared classes")
    if len(clocks) != len(selected) or {c.data_class for c in clocks} != selected:
        raise ValueError("original clocks must exactly cover declared classes")
    by_class = {r.data_class: r for r in rules}
    for clock in clocks:
        rule = by_class[clock.data_class]
        for bound, seconds in (
            (clock.refresh_due_at, rule.refresh_interval_seconds),
            (clock.retention_due_at, rule.retention_seconds),
        ):
            if seconds is not None and (bound is None or bound > clock.captured_at + timedelta(seconds=seconds)):
                raise ValueError("original bounded clocks cannot omit or extend policy deadlines")


class PublicationObjectRef(M9ContractModel):
    """Content-free object projection permitted in independently signed orphan receipts."""

    payload_ref: str
    integrity_ref: str
    attestation_ref: str
    evidence_kind: Slug
    data_classes: tuple[Slug, ...] = Field(min_length=1)
    data_rules: tuple[SourceDataRule, ...] = Field(min_length=1)
    original_clocks: tuple[EvidenceDataClassClock, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_objects(self) -> Self:
        _validate_classes(self.data_classes, self.data_rules, self.original_clocks)
        if len({self.payload_ref, self.integrity_ref, self.attestation_ref}) != 3:
            raise ValueError("paired object references must be distinct")
        return self

    @classmethod
    def from_descriptor(cls, descriptor: SealedObjectDescriptor) -> Self:
        return cls.model_validate({name: getattr(descriptor, name) for name in cls.model_fields})


class SealedObjectDescriptor(PublicationObjectRef):
    retained_material_digest: Sha256Digest | None = None

    @model_validator(mode="after")
    def validate_proof(self) -> Self:
        if self.retained_material_digest is not None and not all(
            r.digest_proof_may_be_retained for r in self.data_rules
        ):
            raise ValueError("every object class must permit retention of material proof")
        return self


class AdmissionRequest(M9ContractModel):
    context: CommandContext
    request_digest: Sha256Digest
    query_id: str
    query_revision: int = Field(ge=1, strict=True)
    query_digest: Sha256Digest
    attempt_id: str
    attempt_version: int = Field(ge=1, strict=True)
    descriptor: ManualBindingDescriptor
    opaque_upload_id: str
    upload_version: int = Field(ge=1, strict=True)
    publication_key: str
    data_rules: tuple[SourceDataRule, ...] = Field(min_length=1)
    original_clocks: tuple[EvidenceDataClassClock, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if (self.context.user_id, self.context.project_name) != (self.descriptor.user_id, self.descriptor.project_name):
            raise ValueError("manual binding must belong to the command scope")
        _validate_classes(tuple(r.data_class for r in self.data_rules), self.data_rules, self.original_clocks)
        return self


class PublishedAdmission(M9ContractModel):
    request: AdmissionRequest
    publication_key: str
    claim_ref: str
    upload_version: int = Field(ge=1, strict=True)
    objects: tuple[SealedObjectDescriptor, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_publication(self) -> Self:
        if self.publication_key != self.request.publication_key or self.upload_version != self.request.upload_version:
            raise ValueError("publication differs from the reserved command")
        _require_request_objects(self.request, self.objects)
        return self


def _require_request_objects(request: AdmissionRequest, objects: Sequence[PublicationObjectRef]) -> None:
    refs = [ref for obj in objects for ref in (obj.payload_ref, obj.integrity_ref, obj.attestation_ref)]
    if len(refs) != len(set(refs)):
        raise ValueError("publication object references cannot alias")
    rules = {r.data_class: r for r in request.data_rules}
    clocks = {c.data_class: c for c in request.original_clocks}
    if {name for obj in objects for name in obj.data_classes} != set(rules):
        raise ValueError("publication must cover the original request classes")
    for obj in objects:
        if any(rules.get(r.data_class) != r for r in obj.data_rules) or any(
            clocks.get(c.data_class) != c for c in obj.original_clocks
        ):
            raise ValueError("publication cannot replace original policy or clocks")


def _minimum(values: Sequence[datetime | None]) -> datetime | None:
    finite = [v for v in values if v is not None]
    return min(finite) if finite else None


class AdmissionClassDeadline(M9ContractModel):
    data_class: Slug
    rule: SourceDataRule
    original_clocks: tuple[EvidenceDataClassClock, ...] = Field(min_length=1)
    admitted_at: AwareDatetime
    admission_refresh_due_at: AwareDatetime | None
    admission_retention_due_at: AwareDatetime | None
    refresh_due_at: AwareDatetime | None
    retention_due_at: AwareDatetime | None

    @model_validator(mode="after")
    def validate_fold(self) -> Self:
        if self.rule.data_class != self.data_class:
            raise ValueError("deadline rule differs from its class")
        for clock in self.original_clocks:
            _validate_classes((self.data_class,), (self.rule,), (clock,))
            if clock.captured_at > self.admitted_at:
                raise ValueError("upstream capture cannot follow admission")
        for field_name, seconds in (
            ("refresh", self.rule.refresh_interval_seconds),
            ("retention", self.rule.retention_seconds),
        ):
            local = None if seconds is None else self.admitted_at + timedelta(seconds=seconds)
            original = [getattr(c, field_name + "_due_at") for c in self.original_clocks]
            if getattr(self, "admission_" + field_name + "_due_at") != local or getattr(
                self, field_name + "_due_at"
            ) != _minimum([local, *original]):
                raise ValueError("effective deadlines must preserve the original minimum")
        return self


class AdmissionDeadlines(M9ContractModel):
    admitted_at: AwareDatetime
    classes: tuple[AdmissionClassDeadline, ...] = Field(min_length=1)
    refresh_due_at: AwareDatetime | None
    retention_due_at: AwareDatetime | None

    @model_validator(mode="after")
    def validate_minima(self) -> Self:
        if len({c.data_class for c in self.classes}) != len(self.classes) or any(
            c.admitted_at != self.admitted_at for c in self.classes
        ):
            raise ValueError("class deadlines must share one immutable admission anchor")
        for name in ("refresh_due_at", "retention_due_at"):
            if getattr(self, name) != _minimum([getattr(c, name) for c in self.classes]):
                raise ValueError("mixed access requires the earliest class deadline")
        return self


def _fold_deadlines(
    rules: Sequence[SourceDataRule], objects: Sequence[SealedObjectDescriptor], admitted_at: datetime
) -> AdmissionDeadlines:
    if admitted_at.tzinfo is None or admitted_at.utcoffset() is None or not objects:
        raise ValueError("admission requires an aware clock and original objects")
    by_class = {r.data_class: r for r in rules}
    used = {name for obj in objects for name in obj.data_classes}
    if not used <= set(by_class):
        raise ValueError("object data classes are not granted")
    classes: list[AdmissionClassDeadline] = []
    for name in sorted(used):
        rule = by_class[name]
        selected = [obj for obj in objects if name in obj.data_classes]
        if any(next(r for r in obj.data_rules if r.data_class == name) != rule for obj in selected):
            raise ValueError("object policy differs from the pinned grant")
        clocks = tuple(
            {
                canonical_json_bytes(c): c for obj in selected for c in obj.original_clocks if c.data_class == name
            }.values()
        )
        refresh = (
            None
            if rule.refresh_interval_seconds is None
            else admitted_at + timedelta(seconds=rule.refresh_interval_seconds)
        )
        retention = None if rule.retention_seconds is None else admitted_at + timedelta(seconds=rule.retention_seconds)
        classes.append(
            AdmissionClassDeadline(
                data_class=name,
                rule=rule,
                original_clocks=clocks,
                admitted_at=admitted_at,
                admission_refresh_due_at=refresh,
                admission_retention_due_at=retention,
                refresh_due_at=_minimum([refresh, *(c.refresh_due_at for c in clocks)]),
                retention_due_at=_minimum([retention, *(c.retention_due_at for c in clocks)]),
            )
        )
    return AdmissionDeadlines(
        admitted_at=admitted_at,
        classes=tuple(classes),
        refresh_due_at=_minimum([c.refresh_due_at for c in classes]),
        retention_due_at=_minimum([c.retention_due_at for c in classes]),
    )


def effective_admission_deadlines(
    grant: SourceCapabilityGrant, objects: Sequence[SealedObjectDescriptor], *, admitted_at: datetime
) -> AdmissionDeadlines:
    """Fold original class deadlines without moving any original capture anchor."""
    try:
        grant = SourceCapabilityGrant.model_validate(grant.model_dump())
        original = tuple(SealedObjectDescriptor.model_validate(obj.model_dump()) for obj in objects)
        return _fold_deadlines(grant.data_rules, original, admitted_at)
    except (ValueError, TypeError, OverflowError):
        raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN) from None


class AdmissionPhase(StrEnum):
    RESERVED = "RESERVED"
    READY = "READY"
    CLEANUP_PENDING = "CLEANUP_PENDING"
    ERASED = "ERASED"


class DispatchClaim(M9ContractModel):
    claim_id: str
    context: CommandContext
    request_digest: Sha256Digest
    attempt_id: str
    attempt_version: int = Field(ge=1, strict=True)
    envelope_version: int = Field(ge=1, strict=True)
    claimed_at: AwareDatetime


def admission_metadata_digest(value: AdmissionEnvelope | Mapping[str, object]) -> str:
    body = value.model_dump(mode="json") if isinstance(value, AdmissionEnvelope) else dict(value)
    body.pop("metadata_digest", None)
    return _digest(b"m9.manual-admission.v1\x00", _AdmissionMetadata.model_validate(body))


class _AdmissionMetadata(M9ContractModel):
    schema_version: Literal["m9.manual-admission.v1"]
    request: AdmissionRequest
    phase: AdmissionPhase
    version: int = Field(ge=1, strict=True)
    claim_ref: str | None
    objects: tuple[SealedObjectDescriptor, ...]
    admitted_at: AwareDatetime | None
    deadlines: AdmissionDeadlines | None
    dispatch_claim: DispatchClaim | None


class AdmissionEnvelope(_AdmissionMetadata):
    metadata_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if admission_metadata_digest(self) != self.metadata_digest:
            raise ValueError("admission metadata digest differs")
        if self.phase == AdmissionPhase.RESERVED:
            if (
                self.claim_ref is not None
                or self.objects
                or self.admitted_at is not None
                or self.deadlines is not None
                or self.dispatch_claim is not None
            ):
                raise ValueError("reserved admission cannot invent publication or dispatch")
        elif self.phase == AdmissionPhase.READY and (
            not self.objects or self.claim_ref is None or self.admitted_at is None or self.deadlines is None
        ):
            raise ValueError("ready admission requires original publication and DB anchor")
        if self.objects:
            _require_request_objects(self.request, self.objects)
        if (self.admitted_at is None) != (self.deadlines is None):
            raise ValueError("admission anchor and deadlines are paired")
        if (
            self.deadlines is not None
            and self.admitted_at is not None
            and (
                not self.objects
                or _fold_deadlines(self.request.data_rules, self.objects, self.admitted_at) != self.deadlines
            )
        ):
            raise ValueError("admission deadlines differ from original objects")
        claim = self.dispatch_claim
        if claim is not None and (
            self.admitted_at is None
            or claim.claimed_at < self.admitted_at
            or claim.context != self.request.context
            or claim.request_digest != self.request.request_digest
            or claim.attempt_id != self.request.attempt_id
            or claim.attempt_version < self.request.attempt_version
            or claim.envelope_version > self.version
        ):
            raise ValueError("dispatch claim differs from the original admission")
        return self


def require_admission_access(envelope: AdmissionEnvelope, *, now: datetime, operational: bool) -> None:
    try:
        envelope = AdmissionEnvelope.model_validate(envelope.model_dump())
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("aware access clock required")
    except (ValueError, TypeError):
        raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE) from None
    if envelope.phase != AdmissionPhase.READY:
        raise OpportunityError(StopCode.M9_INVALIDATION_INCOMPLETE)
    if envelope.admitted_at is None or envelope.deadlines is None or now < envelope.admitted_at:
        raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
    if envelope.deadlines.retention_due_at is not None and now >= envelope.deadlines.retention_due_at:
        raise OpportunityError(StopCode.M9_EVIDENCE_RETENTION_EXPIRED)
    if operational and envelope.deadlines.refresh_due_at is not None and now >= envelope.deadlines.refresh_due_at:
        raise OpportunityError(StopCode.M9_EVIDENCE_STALE)


class PublicationReceiptMetadata(M9ContractModel):
    schema_version: Literal["m9.manual-publication-receipt.v1"]
    context: CommandContext
    source_kind: Literal["manual-import"]
    source_contract_version: Literal["manual-import.v1"]
    verification_key_id: Slug
    request_digest: Sha256Digest
    query_id: str
    query_revision: int = Field(ge=1, strict=True)
    query_digest: Sha256Digest
    attempt_id: str
    attempt_version: int = Field(ge=1, strict=True)
    publication_key: str
    claim_ref: str
    upload_version: int = Field(ge=1, strict=True)
    descriptor_digest: Sha256Digest
    objects: tuple[PublicationObjectRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        refs = [ref for obj in self.objects for ref in (obj.payload_ref, obj.integrity_ref, obj.attestation_ref)]
        if len(refs) != len(set(refs)):
            raise ValueError("receipt object references cannot alias")
        return self


def publication_metadata_digest(metadata: PublicationReceiptMetadata) -> str:
    return _digest(b"m9.manual-publication-metadata.v1\x00", metadata)


class PublicationHeader(M9ContractModel):
    metadata: PublicationReceiptMetadata
    metadata_digest: Sha256Digest
    signature: str = Field(pattern=r"^[A-Za-z0-9_-]{86}$")

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        if publication_metadata_digest(self.metadata) != self.metadata_digest:
            raise ValueError("publication receipt metadata digest differs")
        return self


class AdmissionReadPermit(M9ContractModel):
    lease_id: str
    user_id: str
    project_name: str
    attempt_id: str
    envelope_version: int = Field(ge=1, strict=True)
    operational: bool
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    access_deadline: AwareDatetime | None

    @model_validator(mode="after")
    def validate_permit(self) -> Self:
        if self.expires_at <= self.issued_at or (
            self.access_deadline is not None and self.expires_at > self.access_deadline
        ):
            raise ValueError("read lease must expire within original access bounds")
        return self


class AdmissionClosureIntent(M9ContractModel):
    closure_id: str
    user_id: str
    project_name: str
    attempt_id: str
    attempt_version: int = Field(ge=1, strict=True)
    envelope_version: int = Field(ge=1, strict=True)
    phase: Literal["CLEANUP_PENDING", "ERASED"]
    version: int = Field(ge=1, strict=True)
    object_refs: tuple[str, ...] = Field(min_length=1)
    fenced_at: AwareDatetime


class AdmissionDeletionReceipt(M9ContractModel):
    closure: AdmissionClosureIntent
    absent_refs: tuple[str, ...] = Field(min_length=1)
    retained_proofs: tuple[SealedObjectDescriptor, ...]
    deleted_at: AwareDatetime

    @model_validator(mode="after")
    def validate_deletion(self) -> Self:
        if self.absent_refs != self.closure.object_refs or self.deleted_at < self.closure.fenced_at:
            raise ValueError("deletion receipt must confirm every exact fenced reference")
        for proof in self.retained_proofs:
            if proof.retained_material_digest is None or not all(
                r.digest_proof_may_be_retained for r in proof.data_rules
            ):
                raise ValueError("deletion proof must be explicitly permitted")
            if not {proof.payload_ref, proof.integrity_ref, proof.attestation_ref} <= set(self.absent_refs):
                raise ValueError("deletion proof must belong to the exact closure")
        return self
