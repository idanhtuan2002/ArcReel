"""Verified immutable source-query evidence for the acquisition application."""

from r2.contracts.opportunity import SourceQuery
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
