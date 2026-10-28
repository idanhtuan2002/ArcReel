"""M10-B packaging check, preview, Human selection and deterministic export contracts.

The package payload itself is the M8 kernel member `PackagingCandidate`; these shapes bind it to M10 evidence.
"""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import AwareDatetime, Field, StrictInt, field_validator, model_validator

from r2.contracts.advanced_creative import Sha256Digest
from r2.contracts.quality import (
    CommandEnvelope,
    ExactIdentity,
    M10ContractModel,
    M10Uuid7,
    NonBlankText,
    ObservationBase,
    ObservationType,
)

EXPORT_PATH = re.compile(r"^[a-z0-9._-]+(/[a-z0-9._-]+)*$")
EXPORT_MEMBER_MAX_BYTES = 2**31 - 1


def _unique(values: object) -> None:
    items = tuple(values)  # pyright: ignore[reportArgumentType]
    if len(items) != len(set(items)):
        raise ValueError("duplicate identity")


def _window(start: AwareDatetime, end: AwareDatetime, maximum: int) -> None:
    if not 0 < (end - start).total_seconds() <= maximum:
        raise ValueError("invalid explicit time window")


def _command(
    command: CommandEnvelope,
    subject: PackageCheckSubject | PackagePreviewSubject | PackageSelectionSubject | ExportSubject,
    operation: str,
) -> None:
    if command.operation != operation or (command.user_id, command.project_name, command.actor_id) != (
        subject.user_id,
        subject.project_name,
        subject.actor_id,
    ):
        raise ValueError("command scope, actor or action mismatch")


class PackagingAssessedSubject(M10ContractModel):
    base_subject_digest: Sha256Digest
    packaging_candidate_id: ExactIdentity
    packaging_candidate_revision: StrictInt = Field(ge=1)
    packaging_candidate_digest: Sha256Digest
    constraint_snapshot_digest: Sha256Digest


class PackagingObservation(ObservationBase[Literal[ObservationType.PACKAGING]]):
    """A package-scoped observation; its `subject_digest` is the PackagingAssessedSubject digest, never a run's."""

    observation_type: Literal[ObservationType.PACKAGING]
    packaging_subject: PackagingAssessedSubject
    constraint_snapshot_digest: Sha256Digest
    check_config_digest: Sha256Digest
    rule_results_digest: Sha256Digest

    @model_validator(mode="after")
    def bound_snapshot(self) -> Self:
        if self.constraint_snapshot_digest != self.packaging_subject.constraint_snapshot_digest:
            raise ValueError("constraint snapshot mismatch")
        return self


class PackageCheckSubject(M10ContractModel):
    user_id: ExactIdentity
    project_name: ExactIdentity
    actor_id: ExactIdentity
    candidate_id: ExactIdentity
    candidate_revision: StrictInt = Field(ge=1)
    candidate_payload_digest: Sha256Digest
    quality_run_id: M10Uuid7
    quality_run_digest: Sha256Digest


class PackageCheckRequest(M10ContractModel):
    command: CommandEnvelope
    subject: PackageCheckSubject

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _command(self.command, self.subject, "CHECK_PACKAGE")
        return self


class PackagingSlotKey(M10ContractModel):
    """`PACKAGING_SLOT` identity: one selected head per source artifact, cohort and product surface."""

    user_id: ExactIdentity
    project_name: ExactIdentity
    source_artifact_key: ExactIdentity
    cohort_id: ExactIdentity
    product_surface: ExactIdentity


class PackageWaiver(M10ContractModel):
    rule_id: ExactIdentity
    finding_id: M10Uuid7
    reason: NonBlankText


class PackagePreviewSubject(M10ContractModel):
    """What an operator asks to preview; the server binds the current run, disposition and head itself."""

    user_id: ExactIdentity
    project_name: ExactIdentity
    actor_id: ExactIdentity
    slot: PackagingSlotKey
    candidate_id: ExactIdentity
    candidate_revision: StrictInt = Field(ge=1)
    candidate_payload_digest: Sha256Digest
    packaging_observation_id: M10Uuid7
    selected_variant_ids: tuple[ExactIdentity, ...]
    waivers: tuple[PackageWaiver, ...]

    @field_validator("selected_variant_ids")
    @classmethod
    def variant_order(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _unique(value)
        return tuple(sorted(value, key=lambda item: item.encode("utf-8")))

    @field_validator("waivers")
    @classmethod
    def waiver_order(cls, value: tuple[PackageWaiver, ...]) -> tuple[PackageWaiver, ...]:
        _unique(w.finding_id for w in value)
        return tuple(sorted(value, key=lambda w: w.finding_id))


class PackagePreviewRequest(M10ContractModel):
    command: CommandEnvelope
    subject: PackagePreviewSubject

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _command(self.command, self.subject, "PREVIEW_PACKAGE")
        if (self.subject.slot.user_id, self.subject.slot.project_name) != (
            self.subject.user_id,
            self.subject.project_name,
        ):
            raise ValueError("preview slot scope mismatch")
        return self


class PackagePreview(M10ContractModel):
    preview_id: M10Uuid7
    slot: PackagingSlotKey
    candidate_id: ExactIdentity
    candidate_revision: StrictInt = Field(ge=1)
    candidate_payload_digest: Sha256Digest
    approved_master_id: ExactIdentity
    approved_master_digest: Sha256Digest
    quality_run_id: M10Uuid7
    quality_run_digest: Sha256Digest
    disposition_id: M10Uuid7
    disposition_digest: Sha256Digest
    profile_id: M10Uuid7
    profile_revision: StrictInt = Field(ge=1)
    profile_digest: Sha256Digest
    packaging_observation_id: M10Uuid7
    packaging_observation_digest: Sha256Digest
    selected_variant_ids: tuple[ExactIdentity, ...]
    waivers: tuple[PackageWaiver, ...]
    expected_head_version: StrictInt = Field(ge=0)
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @field_validator("selected_variant_ids")
    @classmethod
    def variant_order(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _unique(value)
        return tuple(sorted(value, key=lambda item: item.encode("utf-8")))

    @field_validator("waivers")
    @classmethod
    def waiver_order(cls, value: tuple[PackageWaiver, ...]) -> tuple[PackageWaiver, ...]:
        _unique(w.finding_id for w in value)
        return tuple(sorted(value, key=lambda w: w.finding_id))

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _window(self.created_at, self.expires_at, 900)
        return self


class PackageSelectionSubject(M10ContractModel):
    user_id: ExactIdentity
    project_name: ExactIdentity
    actor_id: ExactIdentity
    preview_id: M10Uuid7
    preview_digest: Sha256Digest
    expected_head_version: StrictInt = Field(ge=0)


class PackageSelectionRequest(M10ContractModel):
    command: CommandEnvelope
    subject: PackageSelectionSubject

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _command(self.command, self.subject, "SELECT_PACKAGE")
        return self


class PackagingSelectionAuthorizationLease(M10ContractModel):
    authorization_id: ExactIdentity
    action: Literal["PACKAGING_SELECTION"]
    user_id: ExactIdentity
    project_name: ExactIdentity
    actor_id: ExactIdentity
    command_id: ExactIdentity
    request_digest: Sha256Digest
    subject_digest: Sha256Digest
    policy_id: ExactIdentity
    policy_version: ExactIdentity
    evidence_digest: Sha256Digest
    issued_at: AwareDatetime
    admit_not_after: AwareDatetime

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _window(self.issued_at, self.admit_not_after, 30)
        return self


class PackageSelection(M10ContractModel):
    """The immutable selection receipt; the packaging head names exactly one of these per slot."""

    selection_id: M10Uuid7
    command_id: ExactIdentity
    request_digest: Sha256Digest
    preview: PackagePreview
    preview_digest: Sha256Digest
    head_version: StrictInt = Field(ge=1)
    selector_id: ExactIdentity
    custodian_authorization_id: ExactIdentity
    custodian_policy_id: ExactIdentity
    custodian_policy_version: ExactIdentity
    custodian_evidence_digest: Sha256Digest
    selected_at: AwareDatetime

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.head_version != self.preview.expected_head_version + 1:
            raise ValueError("selection head version is not the preview's successor")
        return self


class ExportSubject(M10ContractModel):
    user_id: ExactIdentity
    project_name: ExactIdentity
    actor_id: ExactIdentity
    slot: PackagingSlotKey
    selection_id: M10Uuid7
    selection_digest: Sha256Digest


class ExportRequest(M10ContractModel):
    command: CommandEnvelope
    subject: ExportSubject

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _command(self.command, self.subject, "EXPORT_PACKAGE")
        if (self.subject.slot.user_id, self.subject.slot.project_name) != (
            self.subject.user_id,
            self.subject.project_name,
        ):
            raise ValueError("export slot scope mismatch")
        return self


class ExportManifestEntry(M10ContractModel):
    path: ExactIdentity
    media_type: ExactIdentity
    byte_size: StrictInt = Field(ge=0, le=EXPORT_MEMBER_MAX_BYTES)
    content_digest: Sha256Digest

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        if EXPORT_PATH.fullmatch(value) is None or any(part in {".", ".."} for part in value.split("/")):
            raise ValueError("export paths are relative, normalized and lowercase ASCII")
        return value


class VariantChoice(M10ContractModel):
    group_id: ExactIdentity
    variant_id: ExactIdentity


class ExportManifest(M10ContractModel):
    schema_id: Literal["m10.export-manifest.v1"]
    slot: PackagingSlotKey
    selection_id: M10Uuid7
    selection_digest: Sha256Digest
    disposition_id: M10Uuid7
    disposition_digest: Sha256Digest
    candidate_payload_digest: Sha256Digest
    builder_identity_digest: Sha256Digest
    chosen_variants: tuple[VariantChoice, ...]
    entries: tuple[ExportManifestEntry, ...] = Field(min_length=1)

    @field_validator("chosen_variants")
    @classmethod
    def choice_order(cls, value: tuple[VariantChoice, ...]) -> tuple[VariantChoice, ...]:
        _unique(choice.group_id for choice in value)
        return tuple(sorted(value, key=lambda choice: choice.group_id.encode("utf-8")))

    @field_validator("entries")
    @classmethod
    def entry_order(cls, value: tuple[ExportManifestEntry, ...]) -> tuple[ExportManifestEntry, ...]:
        _unique(entry.path for entry in value)
        _unique(entry.path.casefold() for entry in value)
        if "manifest.json" in {entry.path for entry in value}:
            raise ValueError("manifest.json is written by the builder, never listed")
        if sum(entry.byte_size for entry in value) > EXPORT_MEMBER_MAX_BYTES:
            raise ValueError("export closure exceeds the archive envelope")
        return tuple(sorted(value, key=lambda entry: entry.path.encode("ascii")))


class ExportExecutionIdentity(M10ContractModel):
    """The M7 request identity of one export: exactly what the builder materializes and with which builder."""

    schema_id: Literal["m10.export-execution.v1"]
    slot: PackagingSlotKey
    selection_id: M10Uuid7
    selection_digest: Sha256Digest
    manifest_digest: Sha256Digest
    builder_identity_digest: Sha256Digest
    adapter_version: ExactIdentity


class ExportBundleReceipt(M10ContractModel):
    receipt_id: M10Uuid7
    execution_id: ExactIdentity
    command_id: ExactIdentity
    request_digest: Sha256Digest
    manifest: ExportManifest
    manifest_digest: Sha256Digest
    archive_ref: ExactIdentity
    archive_digest: Sha256Digest
    archive_byte_size: StrictInt = Field(gt=0)
    status: Literal["EXPORTED"]
    exported_at: AwareDatetime


__all__ = [
    "EXPORT_MEMBER_MAX_BYTES",
    "ExportBundleReceipt",
    "ExportExecutionIdentity",
    "ExportManifest",
    "ExportManifestEntry",
    "ExportRequest",
    "ExportSubject",
    "PackageCheckRequest",
    "PackageCheckSubject",
    "PackagePreview",
    "PackagePreviewRequest",
    "PackagePreviewSubject",
    "PackageSelection",
    "PackageSelectionRequest",
    "PackageSelectionSubject",
    "PackageWaiver",
    "PackagingAssessedSubject",
    "PackagingObservation",
    "PackagingSelectionAuthorizationLease",
    "PackagingSlotKey",
    "VariantChoice",
]
