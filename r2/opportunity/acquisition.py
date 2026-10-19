"""Verified immutable source-query evidence for the acquisition application."""

from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from r2.contracts.opportunity import M9ContractModel, SnapshotPage, SourceQuery
from r2.opportunity.digests import digest_source_query
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
