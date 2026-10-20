"""Successor acquisition digests over the accepted canonical JSON implementation."""

from r2.advanced_creative.digests import digest_canonical
from r2.contracts.opportunity_acquisition_v2 import (
    AcquireSourceQueryV2,
    AcquisitionReceiptV2,
    SnapshotProvenanceV2,
)


def digest_acquisition_request_v2(command: AcquireSourceQueryV2) -> str:
    value = AcquireSourceQueryV2.model_validate(command.model_dump())
    return digest_canonical(
        {
            "domain": "m9.command-request.v2",
            "schema_version": "2",
            "body": {"operation": "acquire", "context": value.context, "command": value},
        }
    )


def digest_acquisition_result_v2(receipt: AcquisitionReceiptV2) -> str:
    value = AcquisitionReceiptV2.model_validate(receipt.model_dump())
    return digest_canonical(
        {
            "domain": "m9.command-result.v2",
            "schema_version": "2",
            "body": {
                "protocol_version": value.protocol_version,
                "operation": "acquire",
                "request_digest": value.request_digest,
                "receipt": value.model_dump(exclude={"result_digest"}),
            },
        }
    )


def digest_snapshot_provenance_v2(provenance: SnapshotProvenanceV2) -> str:
    value = SnapshotProvenanceV2.model_validate(provenance.model_dump())
    return digest_canonical({"domain": "m9.snapshot-provenance.v2", "schema_version": "2", "body": value})
