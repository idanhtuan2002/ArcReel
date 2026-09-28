"""ADR-0089's four mandatory Human Gates (A-D) -- P1 backlog item 6
(docs/superpowers/specs/2026-09-22-r2-p1-gate-receipt-surface-design.md).

Gate B (Narrative Lock) and Gate C's existing selection mechanism
(ApprovedMasterMetadata) already have real, LOCKED contracts elsewhere
(r2.contracts.adaptation, r2.production.artifact_metadata) and are not
duplicated here. This module holds only what is genuinely new: Gate A/D's
own decision records, and Gate C's additive audit companion.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field

from .common import NonEmptyStr, R2ContractModel


class GateAuthorization(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    authenticated_principal: NonEmptyStr
    authority_role: Literal["HUMAN_OPERATOR"]
    authorized_at: AwareDatetime


class GreenlightDecision(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    decision_id: NonEmptyStr
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    source_digest: NonEmptyStr
    action: Literal["GREENLIGHT", "REVOKE"]
    authorization: GateAuthorization
    sequence: int = Field(ge=1)
    created_at: AwareDatetime


class ScriptLockDecision(R2ContractModel):
    """Gate B for a factual product (ADR-0092): a human lock on the exact source and script
    revision. Drama products are locked by screenplay admission instead."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    decision_id: NonEmptyStr
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    source_digest: NonEmptyStr
    script_digest: NonEmptyStr
    action: Literal["LOCK", "REVOKE"]
    authorization: GateAuthorization
    sequence: int = Field(ge=1)
    created_at: AwareDatetime


class PublishApprovalDecision(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    decision_id: NonEmptyStr
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    deliverable_digest: NonEmptyStr
    platform: NonEmptyStr
    visibility: NonEmptyStr
    action: Literal["APPROVE_PUBLISH", "REVOKE"]
    authorization: GateAuthorization
    sequence: int = Field(ge=1)
    created_at: AwareDatetime


class FinalCutReceipt(R2ContractModel):
    """Gate C's additive audit companion. Written only by the Gate C route
    handler after a successful ProductionApprovalService.promote() call
    (design section 4.2) -- never by ProductionApprovalService itself, which
    is unmodified and has no knowledge this contract exists."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    artifact_key: NonEmptyStr
    selected_candidate_id: NonEmptyStr
    content_fingerprint: NonEmptyStr
    approval_record: NonEmptyStr
    selected_by: NonEmptyStr
    selected_at: AwareDatetime
    sequence: int = Field(ge=1)
    # The composed final's verified audio decision (ADR-0092); shot receipts carry none.
    audio_decision: Literal["AUDIO", "MUTE"] | None = None


__all__ = [
    "FinalCutReceipt",
    "GateAuthorization",
    "GreenlightDecision",
    "PublishApprovalDecision",
    "ScriptLockDecision",
]
