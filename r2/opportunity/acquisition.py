"""Verified immutable source-query evidence for the acquisition application."""

from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from r2.contracts.opportunity import (
    AcquisitionReceipt,
    CommandContext,
    M9ContractModel,
    QueryReceipt,
    SnapshotPage,
    SourceQuery,
)
from r2.opportunity.digests import digest_command_result, digest_source_query
from r2.opportunity.errors import OpportunityError, StopCode


def verified_query(query: SourceQuery) -> SourceQuery:
    try:
        value = SourceQuery.model_validate(query.model_dump())
        if value.query_digest != digest_source_query(value):
            raise ValueError("query integrity differs")
        return value
    except ValueError:
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None


class PageCheckpoint(M9ContractModel):
    """Internal restart metadata; cursor bytes and native values remain erasable."""

    page: SnapshotPage
    source_identity_refs: tuple[str, ...]
    quota_units_observed: int | None = Field(ge=0)
    next_cursor_ref: str | None
    next_cursor_integrity_ref: str | None
    terminal_page: bool
    provider_observed_at: AwareDatetime | None

    @model_validator(mode="after")
    def validate_checkpoint(self) -> Self:
        if (self.next_cursor_ref is None) != (self.next_cursor_integrity_ref is None):
            raise ValueError("cursor refs must be paired")
        if self.terminal_page != (self.page.response_cursor_digest is None) or self.terminal_page != (
            self.next_cursor_ref is None
        ):
            raise ValueError("cursor metadata must match terminal coverage")
        if len(set(self.source_identity_refs)) != len(self.source_identity_refs):
            raise ValueError("source identities must be distinct")
        if len(self.source_identity_refs) > self.page.record_count or bool(self.source_identity_refs) != bool(
            self.page.record_count
        ):
            raise ValueError("source identity coverage differs from page records")
        if self.page.payload_ref is None and (not self.terminal_page or self.source_identity_refs):
            raise ValueError("missing page cannot carry resumable content")
        return self


def verified_query_receipt(receipt: QueryReceipt, context: CommandContext, request_digest: str) -> QueryReceipt:
    try:
        receipt = QueryReceipt.model_validate(receipt.model_dump())
        query = verified_query(receipt.query)
        if (
            (
                query.user_id,
                query.project_name,
                query.created_by,
                receipt.command_id,
                receipt.request_digest,
                receipt.head.query_id,
                receipt.head.current_revision,
            )
            != (
                context.user_id,
                context.project_name,
                context.actor_id,
                context.command_id,
                request_digest,
                query.query_id,
                query.revision,
            )
            or receipt.committed_at < query.created_at
            or receipt.head.head_version != query.revision
        ):
            raise ValueError("query receipt binding differs")
        if digest_command_result("declare_query", request_digest, receipt) != receipt.result_digest:
            raise ValueError("query receipt result differs")
        return receipt
    except ValueError:
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None


def verified_acquisition_receipt(
    receipt: AcquisitionReceipt, context: CommandContext, request_digest: str
) -> AcquisitionReceipt:
    try:
        receipt = AcquisitionReceipt.model_validate(receipt.model_dump())
        if (receipt.command_id, receipt.request_digest) != (context.command_id, request_digest) or (
            len(receipt.snapshot_ids) != len(receipt.snapshot_digests)
        ):
            raise ValueError("acquisition receipt binding differs")
        if digest_command_result("acquire", request_digest, receipt) != receipt.result_digest:
            raise ValueError("acquisition receipt result differs")
        return receipt
    except ValueError:
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None
