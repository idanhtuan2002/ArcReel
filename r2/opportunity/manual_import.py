"""Immutable host-bound manual bytes through the frozen source-page port."""

from __future__ import annotations

import hashlib

from r2.contracts.advanced_creative import CanonicalJsonObject
from r2.contracts.opportunity import (
    CapabilityState,
    EffectiveCapabilityEvaluation,
    PermissionDisposition,
    SourceCapabilityGrant,
    SourcePageRequest,
    SourcePageResult,
)
from r2.opportunity.digests import digest_capability_evaluation, digest_capability_grant, digest_condition_evidence
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.normalization import decode_manual_payload


class ManualImportSource:
    def __init__(
        self,
        *,
        payload: bytes,
        grant: SourceCapabilityGrant,
        evaluation: EffectiveCapabilityEvaluation,
        actor_id: str,
        upload_ref: str,
        origin_ref: str,
        declared_origin: str,
        uploader_id: str,
        payload_digest: str,
    ) -> None:
        # The host supplies these bindings; incoming query labels are never authority.
        # Raw content integrity remains erasable host state, never grant conditions.
        if "sha256:" + hashlib.sha256(payload).hexdigest() != payload_digest:
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        if (
            grant.source_kind != "manual-import"
            or grant.source_contract_version != "manual-import.v1"
            or grant.state is not CapabilityState.ENABLED
            or grant.permission is not PermissionDisposition.CONDITIONAL
            or grant.credential_ref is not None
            or grant.account_binding_digest is not None
            or digest_capability_grant(grant) != grant.grant_digest
            or digest_capability_evaluation(evaluation, actor_id=actor_id) != evaluation.evaluation_digest
            or (
                evaluation.grant_id,
                evaluation.grant_version,
                evaluation.grant_digest,
                evaluation.user_id,
                evaluation.project_name,
                evaluation.source_kind,
                evaluation.operation,
            )
            != (
                grant.grant_id,
                grant.grant_version,
                grant.grant_digest,
                grant.user_id,
                grant.project_name,
                grant.source_kind,
                "import",
            )
            or evaluation.effective_permission is not PermissionDisposition.PERMITTED
            or "import" not in grant.allowed_operations
            or evaluation.purpose not in grant.allowed_purposes
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        body, rows = decode_manual_payload(payload)
        if body["origin"] != declared_origin or body["uploader"] != uploader_id:
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        classes = tuple(sorted({str(row["data_class"]) for row in rows})) or tuple(
            rule.data_class for rule in grant.data_rules
        )
        if set(classes) - {rule.data_class for rule in grant.data_rules}:
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        condition = CanonicalJsonObject.model_validate(
            {
                "kind": "manual-upload-policy.v1",
                "upload_ref": upload_ref,
                "origin_ref": origin_ref,
                "uploader_id": actor_id,
                "data_classes": classes,
            }
        )
        if (
            grant.conditions != (condition,)
            or tuple(item.model_dump() for item in evaluation.condition_evidence)
            != ({"condition": condition.model_dump(), "satisfied": True},)
            or any(item.model_dump().get("satisfied") is not True for item in evaluation.condition_evidence)
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        if evaluation.condition_evidence_digest != digest_condition_evidence(
            grant_id=grant.grant_id,
            grant_version=grant.grant_version,
            grant_digest=grant.grant_digest,
            condition_evidence=evaluation.condition_evidence,
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        self._payload = payload
        self._grant = grant
        self._evaluation = evaluation
        self._upload_ref = upload_ref
        self._classes = classes
        self._native_ids = tuple(sorted({str(row["source_native_id"]) for row in rows}))
        self._record_count = len(rows)

    async def fetch_page(self, request: SourcePageRequest) -> SourcePageResult:
        grant = self._grant
        if (
            (
                request.user_id,
                request.project_name,
                request.source_kind,
                request.source_contract_version,
                request.operation,
            )
            != (grant.user_id, grant.project_name, "manual-import", "manual-import.v1", "import")
            or request.capability_grant_digest != grant.grant_digest
            or request.capability_evaluation_digest != self._evaluation.evaluation_digest
            or request.parameters.model_dump() != {"import_ref": self._upload_ref}
            or request.credential_ref is not None
            or request.cursor is not None
            or request.page_ordinal != 1
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        if request.remaining_record_limit < self._record_count:
            raise OpportunityError(StopCode.M9_OPERATIONAL_ENVELOPE_EXCEEDED)
        return SourcePageResult(
            provider_request_id=self._upload_ref,
            next_cursor=None,
            raw_payload=self._payload,
            raw_media_type="application/json",
            source_native_ids=self._native_ids,
            data_classes=self._classes,
            returned_record_count=self._record_count,
            quota_units_observed=0,
            provider_observed_at=None,
            terminal_page=True,
        )
