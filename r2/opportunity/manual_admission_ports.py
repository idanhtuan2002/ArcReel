"""Internal asynchronous manual-upload custody and publication boundaries."""

from typing import Protocol

from r2.opportunity.manual_admission import (
    AdmissionClosureIntent,
    AdmissionDeletionReceipt,
    AdmissionEnvelope,
    AdmissionReadPermit,
    AdmissionRequest,
    PublicationHeader,
    PublishedAdmission,
)


class ManualUploadAdmissionPort(Protocol):
    async def admit(self, request: AdmissionRequest) -> PublishedAdmission: ...


class ManualPublicationPort(Protocol):
    async def lookup_receipt(self, publication_key: str) -> PublicationHeader | None: ...
    async def read_verified(
        self, envelope: AdmissionEnvelope, *, object_ref: str, permit: AdmissionReadPermit
    ) -> bytes: ...
    async def delete_exact(self, closure: AdmissionClosureIntent) -> AdmissionDeletionReceipt: ...
