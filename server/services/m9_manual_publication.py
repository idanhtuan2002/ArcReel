"""Public-key authenticated, content-free manual publication discovery."""

from __future__ import annotations

import asyncio
import base64
import fcntl
import hashlib
import importlib.metadata
import importlib.util
import os
import re
import stat
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import CodeType
from typing import Literal
from uuid import uuid4

from pydantic import Field, TypeAdapter

from lib.json_io import atomic_write_bytes
from r2.advanced_creative.digests import canonical_json_bytes
from r2.contracts.opportunity import M9ContractModel, Slug
from r2.opportunity.acquisition import NativeFieldMaterial
from r2.opportunity.acquisition_v2 import (
    CustodianPublicationDisposition,
    CustodianSpendReceipt,
    CustodianSpendSubject,
    ManualCustodianClosurePort,
    manual_publication_metadata_for_request,
)
from r2.opportunity.acquisition_v2 import (
    verify_custodian_spent as verify_private_custody_spend,
)
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.manual_admission import (
    AdmissionClosureIntent,
    AdmissionDeletionReceipt,
    AdmissionEnvelope,
    AdmissionReadPermit,
    AdmissionRequest,
    ManualBindingDescriptor,
    PublicationHeader,
    PublicationObjectRef,
    PublicationReceiptMetadata,
    PublishedAdmission,
    SealedObjectDescriptor,
    SealExpectation,
    publication_metadata_digest,
    require_admission_access,
)
from r2.opportunity.normalization import decode_manual_payload
from server.services.m9_manual_authenticity import verify_manual_seal, verify_publication_receipt

_KEY_ID = TypeAdapter(Slug)
_OPEN_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def verify_custodian_spent(
    raw: bytes, *, public_key: bytes, expected_request: AdmissionRequest, closure_id: str
) -> CustodianSpendReceipt:
    """Authenticate private erasure and original header metadata without content reads."""
    return verify_private_custody_spend(
        raw, public_key=public_key, expected_request=expected_request, closure_id=closure_id
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ManualSealVerifier:
    """Host-composed verifier without a signing callback or private-key material."""

    public_key: bytes = field(repr=False)
    verification_key_id: str

    def __post_init__(self) -> None:
        try:
            _KEY_ID.validate_python(self.verification_key_id, strict=True)
            if type(self.public_key) is not bytes or len(self.public_key) != 32:
                raise ValueError("invalid host public key")
        except (ValueError, TypeError):
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE) from None

    def verify_material(self, raw_seal: bytes, actual_bytes: bytes, *, expected: SealExpectation) -> None:
        if expected.verification_key_id != self.verification_key_id:
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        verify_manual_seal(raw_seal, actual_bytes, public_key=self.public_key, expected=expected)

    def verify_receipt(self, raw_receipt: bytes, *, expected: PublicationReceiptMetadata) -> PublicationHeader:
        if expected.verification_key_id != self.verification_key_id:
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        return verify_publication_receipt(raw_receipt, public_key=self.public_key, expected=expected)


@dataclass(frozen=True, slots=True)
class FileManualPublicationStore:
    """Discover signed original refs without opening content or extending its clocks."""

    root: Path
    user_id: str = field(kw_only=True)
    project_name: str = field(kw_only=True)
    verifier: ManualSealVerifier = field(kw_only=True)
    boundary: Callable[[str], None] | None = field(default=None, kw_only=True, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.absolute())

    async def lookup_receipt(self, publication_key: str) -> PublicationHeader | None:
        return await asyncio.to_thread(self._lookup_receipt, publication_key)

    def _lookup_receipt(self, publication_key: object) -> PublicationHeader | None:
        directory = descriptor = -1
        try:
            if not isinstance(publication_key, str) or not publication_key or len(publication_key) > 4096:
                raise ValueError("invalid publication identity")
            name = hashlib.sha256(publication_key.encode()).hexdigest() + ".json"
            scope = hashlib.sha256(
                canonical_json_bytes({"user_id": self.user_id, "project_name": self.project_name})
            ).hexdigest()
            # Open every ancestor separately: O_NOFOLLOW on the final root alone misses parent symlinks.
            directory = os.open(self.root.anchor, _OPEN_DIRECTORY)
            for component in (*self.root.parts[1:], "manual-publications", scope, "headers"):
                next_directory = os.open(component, _OPEN_DIRECTORY, dir_fd=directory)
                os.close(directory)
                directory = next_directory
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("publication header must be a regular file")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                raw = stream.read(65_537)
            if not 0 < len(raw) <= 65_536:
                raise ValueError("publication header exceeds bound")
            candidate = PublicationHeader.model_validate_json(raw)
            metadata = candidate.metadata
            if (metadata.context.user_id, metadata.context.project_name, metadata.publication_key) != (
                self.user_id,
                self.project_name,
                publication_key,
            ):
                raise ValueError("publication header identity differs")
            return self.verifier.verify_receipt(raw, expected=metadata)
        except FileNotFoundError:
            return None
        except OpportunityError:
            raise
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH) from None
        finally:
            for opened in (descriptor, directory):
                if opened >= 0:
                    os.close(opened)

    def _arrive(self, name: str) -> None:
        if self.boundary is not None:
            self.boundary(name)

    @contextmanager
    def _locked(self, *, create: bool = False) -> Generator[dict[str, int]]:
        directory = lock = -1
        children: dict[str, int] = {}
        try:
            directory = os.open(self.root.anchor, _OPEN_DIRECTORY)
            for component in self.root.parts[1:]:
                child = os.open(component, _OPEN_DIRECTORY, dir_fd=directory)
                os.close(directory)
                directory = child
            scope = hashlib.sha256(
                canonical_json_bytes({"user_id": self.user_id, "project_name": self.project_name})
            ).hexdigest()
            for component in ("manual-publications", scope):
                if create:
                    with suppress(FileExistsError):
                        os.mkdir(component, mode=0o700, dir_fd=directory)
                    os.fsync(directory)
                child = os.open(component, _OPEN_DIRECTORY, dir_fd=directory)
                os.close(directory)
                directory = child
            lock = os.open(
                "lock",
                os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_CREAT if create else 0),
                0o600,
                dir_fd=directory,
            )
            if not stat.S_ISREG(os.fstat(lock).st_mode) or os.fstat(lock).st_nlink != 1:
                raise ValueError("invalid publication lock")
            fcntl.flock(lock, fcntl.LOCK_EX)
            for name in ("headers", "payloads", "integrities", "attestations", "closures", "blocked"):
                if create:
                    with suppress(FileExistsError):
                        os.mkdir(name, mode=0o700, dir_fd=directory)
                child = os.open(name, _OPEN_DIRECTORY, dir_fd=directory)
                children[name] = child
                for temporary in os.listdir(child):
                    if temporary.endswith(".tmp") and temporary.startswith((".rollback.", ".publication-stage.")):
                        os.unlink(temporary, dir_fd=child)
                os.fsync(child)
            os.fsync(directory)
            yield children
        except OpportunityError:
            raise
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH) from None
        finally:
            for descriptor in (*children.values(), lock, directory):
                if descriptor >= 0:
                    os.close(descriptor)

    def _require_binding(self, request: AdmissionRequest) -> None:
        if (
            (request.context.user_id, request.context.project_name) != (self.user_id, self.project_name)
            or request.descriptor.verification_key_id != self.verifier.verification_key_id
            or request.descriptor.verification_key_digest != _sha(self.verifier.public_key)
            or any(
                getattr(request.descriptor, name) != value for name, value in manual_publication_measurements().items()
            )
        ):
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)

    async def publish_if_absent(
        self, request: AdmissionRequest, material: OriginalManualUpload, *, sign: Callable[[bytes], bytes]
    ) -> PublishedAdmission:
        return await asyncio.to_thread(self._publish, request, material, sign)

    def _publish(
        self, request: AdmissionRequest, material: OriginalManualUpload, sign: Callable[[bytes], bytes]
    ) -> PublishedAdmission:
        request = AdmissionRequest.model_validate(request.model_dump())
        self._require_binding(request)
        if request != material.request or request.descriptor.config_digest != manual_publication_config_digest(
            self.root,
            declared_origin=material.declared_origin,
            uploader_id=material.uploader_id,
            store_namespace=request.descriptor.store_namespace,
            resolver_namespace=request.descriptor.resolver_namespace,
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        _require_original_clocks(request)
        specs = original_manual_object_specs(material)
        with self._locked(create=True) as directories:
            _require_unblocked(directories, (request.publication_key,))
            header = material.original_header or self._lookup_receipt(request.publication_key)
            if header is None:
                objects = tuple(_new_object(request, kind, classes) for kind, classes in specs)
                metadata = manual_publication_metadata(request, material.claim_ref, objects)
                body = {"metadata": metadata, "metadata_digest": publication_metadata_digest(metadata)}
                header = PublicationHeader(
                    metadata=metadata,
                    metadata_digest=body["metadata_digest"],
                    signature=_signature(sign(_HEADER_DOMAIN + canonical_json_bytes(body))),
                )
            expected = manual_publication_metadata(request, material.claim_ref, header.metadata.objects)
            self.verifier.verify_receipt(canonical_json_bytes(header), expected=expected)
            if {o.evidence_kind: o.data_classes for o in header.metadata.objects} != dict(specs):
                raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
            objects = header.metadata.objects
            _require_unblocked(
                directories,
                tuple(ref for obj in objects for ref in (obj.payload_ref, obj.integrity_ref, obj.attestation_ref)),
            )
            _write_once(directories["headers"], _key_name(request.publication_key), canonical_json_bytes(header))
            self._arrive("publication-header-durable")
            drafts = original_manual_materials(material, objects)
            published = []
            for obj in objects:
                _require_original_clocks(request)
                raw, retain = drafts[obj.evidence_kind]
                expected_seal = manual_material_expectation(header.metadata, obj)
                body = {"binding": expected_seal, "material_digest": _sha(raw)}
                seal = canonical_json_bytes(
                    {"body": body, "signature": _signature(sign(_MATERIAL_DOMAIN + canonical_json_bytes(body)))}
                )
                self.verifier.verify_material(seal, raw, expected=expected_seal)
                integrity = canonical_json_bytes(
                    {"payload_ref": obj.payload_ref, "integrity_ref": obj.integrity_ref, "digest": _sha(raw)}
                )
                for directory, name, value in (
                    ("payloads", _ref_name(obj.payload_ref, "payload"), raw),
                    ("integrities", _ref_name(obj.integrity_ref, "integrity"), integrity),
                    ("attestations", _ref_name(obj.attestation_ref, "seal"), seal),
                ):
                    _write_once(directories[directory], name, value)
                    self._arrive("publication-" + directory + "-durable")
                if self._read_object(directories, header.metadata, obj) != raw:
                    raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
                published.append(
                    SealedObjectDescriptor(**obj.model_dump(), retained_material_digest=_sha(raw) if retain else None)
                )
            _require_original_clocks(request)
            self._require_binding(request)
            self._arrive("publication-complete")
            return PublishedAdmission(
                request=request,
                publication_key=request.publication_key,
                claim_ref=material.claim_ref,
                upload_version=request.upload_version,
                objects=tuple(published),
            )

    def _read_object(
        self, directories: dict[str, int], metadata: PublicationReceiptMetadata, obj: PublicationObjectRef
    ) -> bytes:
        raw = _read_file(directories["payloads"], _ref_name(obj.payload_ref, "payload"), limit=2_097_152)
        integrity = _read_file(directories["integrities"], _ref_name(obj.integrity_ref, "integrity"), limit=65_536)
        if integrity != canonical_json_bytes(
            {"payload_ref": obj.payload_ref, "integrity_ref": obj.integrity_ref, "digest": _sha(raw)}
        ):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        seal = _read_file(directories["attestations"], _ref_name(obj.attestation_ref, "seal"), limit=65_536)
        self.verifier.verify_material(seal, raw, expected=manual_material_expectation(metadata, obj))
        return raw

    async def read_verified(
        self, envelope: AdmissionEnvelope, *, object_ref: str, permit: AdmissionReadPermit
    ) -> bytes:
        return await asyncio.to_thread(self._read_verified, envelope, object_ref, permit)

    def _read_verified(self, envelope: AdmissionEnvelope, object_ref: str, permit: AdmissionReadPermit) -> bytes:
        envelope = AdmissionEnvelope.model_validate(envelope.model_dump())
        permit = AdmissionReadPermit.model_validate(permit.model_dump())
        self._require_binding(envelope.request)
        _require_read(envelope, permit)
        selected = [obj for obj in envelope.objects if obj.payload_ref == object_ref]
        if len(selected) != 1 or envelope.claim_ref is None:
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        with self._locked() as directories:
            _require_read(envelope, permit)
            _require_unblocked(directories, (envelope.request.publication_key, object_ref))
            header = self._lookup_receipt(envelope.request.publication_key)
            if header is None:
                raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
            expected = manual_publication_metadata(
                envelope.request,
                envelope.claim_ref,
                tuple(PublicationObjectRef.from_descriptor(o) for o in envelope.objects),
            )
            self.verifier.verify_receipt(canonical_json_bytes(header), expected=expected)
            raw = self._read_object(directories, header.metadata, selected[0])
            if selected[0].retained_material_digest not in (None, _sha(raw)):
                raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
            _require_read(envelope, permit)
            self._require_binding(envelope.request)
            return raw

    async def delete_exact(self, closure: AdmissionClosureIntent) -> AdmissionDeletionReceipt:
        return await asyncio.to_thread(self._delete_exact, closure)

    def _delete_exact(self, closure: AdmissionClosureIntent) -> AdmissionDeletionReceipt:
        closure = AdmissionClosureIntent.model_validate(closure.model_dump())
        if (
            (closure.user_id, closure.project_name) != (self.user_id, self.project_name)
            or closure.phase != "CLEANUP_PENDING"
            or closure.version != 2
        ):
            raise OpportunityError(StopCode.M9_INVALIDATION_INCOMPLETE)
        with self._locked() as directories:
            job_name = _key_name(closure.closure_id)
            try:
                job = _DeletionJob.model_validate_json(_read_file(directories["closures"], job_name, limit=2_097_152))
            except FileNotFoundError:
                header_keys = [ref for ref in closure.object_refs if _REF.fullmatch(ref) is None]
                headers = tuple(self._lookup_receipt(key) for key in header_keys)
                if not headers or any(header is None for header in headers):
                    raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH) from None
                job = _DeletionJob(
                    closure=closure, headers=tuple(header for header in headers if header is not None), receipt=None
                )
                _verify_job(self, job, closure)
                _write_once(directories["closures"], job_name, canonical_json_bytes(job))
                self._arrive("deletion-plan-durable")
            _verify_job(self, job, closure)
            targets = _deletion_targets(job.headers)
            if job.receipt is not None:
                if any(_exists(directories[directory], name) for directory, name in targets):
                    raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
                if job.receipt.deleted_at > datetime.now(UTC):
                    raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
                return job.receipt
            for ref in closure.object_refs:
                _write_once(
                    directories["blocked"], _key_name(ref), canonical_json_bytes({"closure_id": closure.closure_id})
                )
            self._arrive("deletion-fence-durable")
            for directory, name in sorted(targets):
                try:
                    info = os.stat(name, dir_fd=directories[directory], follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
                os.unlink(name, dir_fd=directories[directory])
                os.fsync(directories[directory])
                self._arrive("deletion-" + directory + "-durable")
            if any(_exists(directories[directory], name) for directory, name in targets):
                raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
            receipt = AdmissionDeletionReceipt(
                closure=closure, absent_refs=closure.object_refs, retained_proofs=(), deleted_at=datetime.now(UTC)
            )
            completed = job.model_copy(update={"receipt": receipt})
            atomic_write_bytes(
                Path(f"/proc/self/fd/{directories['closures']}") / job_name, canonical_json_bytes(completed)
            )
            os.fsync(directories["closures"])
            self._arrive("deletion-receipt-durable")
            return receipt

    async def fence_recovery_publications(
        self, requests: tuple[AdmissionRequest, ...], *, closure_id: str
    ) -> tuple[PublicationHeader, ...]:
        try:
            return await asyncio.to_thread(self._fence_recovery_publications, requests, closure_id)
        except OpportunityError:
            raise
        except Exception:
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH) from None

    def _fence_recovery_publications(
        self, requests: tuple[AdmissionRequest, ...], closure_id: str
    ) -> tuple[PublicationHeader, ...]:
        requests = tuple(AdmissionRequest.model_validate(request.model_dump()) for request in requests)
        if not requests or not closure_id or len({r.publication_key for r in requests}) != len(requests):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        for request in requests:
            _recovery_request_scope(self, request)
        with self._locked(create=True) as directories:
            for request in requests:
                _write_once(
                    directories["blocked"],
                    _key_name(request.publication_key),
                    canonical_json_bytes({"closure_id": closure_id}),
                )
            self._arrive("recovery-publication-fence-durable")
            return tuple(
                header for request in requests if (header := self._lookup_receipt(request.publication_key)) is not None
            )

    async def delete_recovery_exact(
        self, closure: AdmissionClosureIntent, *, proof: CustodianSpendReceipt, requests: tuple[AdmissionRequest, ...]
    ) -> AdmissionDeletionReceipt:
        try:
            return await asyncio.to_thread(self._delete_recovery_exact, closure, proof, requests)
        except OpportunityError:
            raise
        except Exception:
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH) from None

    def _delete_recovery_exact(
        self, closure: AdmissionClosureIntent, proof: CustodianSpendReceipt, requests: tuple[AdmissionRequest, ...]
    ) -> AdmissionDeletionReceipt:
        expected = _RecoveryDeletionJob(
            schema_version="m9.manual-recovery-deletion.v1",
            closure=closure,
            proof=proof,
            requests=requests,
            receipt=None,
        )
        _verify_recovery_job(self, expected)
        if len(canonical_json_bytes(expected)) * 2 + 8192 > 33_554_432:
            raise OpportunityError(StopCode.M9_OPERATIONAL_ENVELOPE_EXCEEDED)
        with self._locked(create=True) as directories:
            name = _key_name(closure.closure_id)
            try:
                raw = _read_file(directories["closures"], name, limit=33_554_432)
                job = _RecoveryDeletionJob.model_validate_json(raw)
                if canonical_json_bytes(job) != raw:
                    raise ValueError("recovery deletion job is not canonical")
            except FileNotFoundError:
                job = expected
                _write_once(directories["closures"], name, canonical_json_bytes(job))
                self._arrive("recovery-deletion-plan-durable")
            if job.model_dump(exclude={"receipt"}) != expected.model_dump(exclude={"receipt"}):
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
            headers, keys = _verify_recovery_job(self, job)
            targets = _deletion_targets(headers) | {("headers", _key_name(key)) for key in keys}
            if job.receipt is not None:
                if any(_exists(directories[directory], target) for directory, target in targets):
                    raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
                return job.receipt
            originals = {header.metadata.publication_key: header for header in headers}
            for key in keys:
                present = self._lookup_receipt(key)
                if present is not None and present != originals.get(key):
                    raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
            for ref in closure.object_refs:
                _write_once(
                    directories["blocked"], _key_name(ref), canonical_json_bytes({"closure_id": closure.closure_id})
                )
            self._arrive("recovery-deletion-fence-durable")
            for directory, target in sorted(targets):
                try:
                    info = os.stat(target, dir_fd=directories[directory], follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
                os.unlink(target, dir_fd=directories[directory])
                os.fsync(directories[directory])
                self._arrive("recovery-deletion-" + directory + "-durable")
            if any(_exists(directories[directory], target) for directory, target in targets):
                raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
            receipt = AdmissionDeletionReceipt(
                closure=closure, absent_refs=closure.object_refs, retained_proofs=(), deleted_at=datetime.now(UTC)
            )
            job = job.model_copy(update={"receipt": receipt})
            _verify_recovery_job(self, job)
            atomic_write_bytes(Path(f"/proc/self/fd/{directories['closures']}") / name, canonical_json_bytes(job))
            os.fsync(directories["closures"])
            self._arrive("recovery-deletion-receipt-durable")
            return receipt


_MATERIAL_DOMAIN = b"m9.manual-material-seal.v1\x00"
_HEADER_DOMAIN = b"m9.manual-publication-receipt.v1\x00"
_REF = re.compile(r"m9-manual-(payload|integrity|seal):([0-9a-f]{32})\Z")


@dataclass(frozen=True, slots=True, kw_only=True)
class OriginalManualUpload:
    request: AdmissionRequest
    claim_ref: str
    payload: bytes = field(repr=False)
    declared_origin: str
    uploader_id: str
    original_header: PublicationHeader | None = None


class _DeletionJob(M9ContractModel):
    closure: AdmissionClosureIntent
    headers: tuple[PublicationHeader, ...]
    receipt: AdmissionDeletionReceipt | None


class _RecoveryDeletionJob(M9ContractModel):
    schema_version: Literal["m9.manual-recovery-deletion.v1"]
    closure: AdmissionClosureIntent
    proof: CustodianSpendReceipt
    requests: tuple[AdmissionRequest, ...] = Field(min_length=1)
    receipt: AdmissionDeletionReceipt | None


def _recovery_request_scope(store: FileManualPublicationStore, request: AdmissionRequest) -> None:
    if (
        (request.context.user_id, request.context.project_name) != (store.user_id, store.project_name)
        or request.descriptor.verification_key_id != store.verifier.verification_key_id
        or request.descriptor.verification_key_digest != _sha(store.verifier.public_key)
        or not request.publication_key
        or len(request.publication_key) > 4096
    ):
        raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)


def _verify_recovery_job(
    store: FileManualPublicationStore, job: _RecoveryDeletionJob
) -> tuple[tuple[PublicationHeader, ...], tuple[str, ...]]:
    closure, proof = job.closure, job.proof
    root = next((r for r in job.requests if r.attempt_id == closure.attempt_id), None)
    if (
        root is None
        or root != proof.metadata.root_request
        or (closure.user_id, closure.project_name) != (store.user_id, store.project_name)
        or closure.phase != "CLEANUP_PENDING"
        or closure.version != 3
        or closure.attempt_version < root.attempt_version
        or proof.metadata.deleted_at < closure.fenced_at
        or not proof.metadata.inventory_complete
        or len({r.publication_key for r in job.requests}) != len(job.requests)
    ):
        raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
    verify_custodian_spent(
        canonical_json_bytes(proof),
        public_key=store.verifier.public_key,
        expected_request=root,
        closure_id=closure.closure_id,
    )
    publications = {p.request.publication_key: p for p in proof.metadata.publications}
    for request in job.requests:
        _recovery_request_scope(store, request)
        original = publications.get(request.publication_key)
        if original is not None and original.request != request:
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        if original is None:
            publications[request.publication_key] = CustodianPublicationDisposition(
                request=request, state="NEVER_ISSUED", header=None
            )
    subject = CustodianSpendSubject(
        root_request=root, claim_ref=proof.metadata.claim_ref, publications=tuple(publications.values())
    )
    headers = tuple(p.header for p in subject.publications if p.header is not None)
    keys = tuple(sorted(publications))
    refs = {
        ref
        for header in headers
        for obj in header.metadata.objects
        for ref in (obj.payload_ref, obj.integrity_ref, obj.attestation_ref)
    }
    if set(keys).intersection(refs) or set(closure.object_refs) != set(keys) | refs:
        raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
    if job.receipt is not None and (
        job.receipt.closure != closure
        or job.receipt.retained_proofs
        or job.receipt.deleted_at < proof.metadata.deleted_at
        or job.receipt.deleted_at > datetime.now(UTC)
    ):
        raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
    return headers, keys


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifiedManualCleanup:
    """Original storage/config binding and public verification, without a signing key."""

    descriptor: ManualBindingDescriptor
    publication: FileManualPublicationStore
    custodian: ManualCustodianClosurePort = field(repr=False)
    declared_origin: str
    uploader_id: str

    def __post_init__(self) -> None:
        descriptor = ManualBindingDescriptor.model_validate(self.descriptor.model_dump())
        store = self.publication
        if (
            (descriptor.user_id, descriptor.project_name) != (store.user_id, store.project_name)
            or descriptor.verification_key_id != store.verifier.verification_key_id
            or descriptor.verification_key_digest != _sha(self.public_key)
            or descriptor.config_digest
            != manual_publication_config_digest(
                store.root,
                declared_origin=self.declared_origin,
                uploader_id=self.uploader_id,
                store_namespace=descriptor.store_namespace,
                resolver_namespace=descriptor.resolver_namespace,
            )
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)

    @property
    def public_key(self) -> bytes:
        return self.publication.verifier.public_key

    def _request(self, request: AdmissionRequest) -> None:
        if request.descriptor != self.descriptor:
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)

    async def fence_publications(
        self, requests: tuple[AdmissionRequest, ...], *, closure_id: str
    ) -> tuple[PublicationHeader, ...]:
        for request in requests:
            self._request(request)
        return await self.publication.fence_recovery_publications(requests, closure_id=closure_id)

    async def spend_original(
        self, request: AdmissionRequest, *, claim_ref: str | None, closure_id: str
    ) -> CustodianSpendReceipt:
        self._request(request)
        raw = await self.custodian.close_original(request, claim_ref=claim_ref, closure_id=closure_id)
        receipt = verify_custodian_spent(
            raw, public_key=self.public_key, expected_request=request, closure_id=closure_id
        )
        if not receipt.metadata.inventory_complete or (
            claim_ref is not None and receipt.metadata.claim_ref != claim_ref
        ):
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        return receipt

    async def delete_exact(
        self, closure: AdmissionClosureIntent, *, proof: CustodianSpendReceipt, requests: tuple[AdmissionRequest, ...]
    ) -> AdmissionDeletionReceipt:
        for request in requests:
            self._request(request)
        return await self.publication.delete_recovery_exact(closure, proof=proof, requests=requests)


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def manual_publication_measurements() -> dict[str, str]:
    from r2.opportunity.acquisition_v2 import OpportunityAcquisitionServiceV2
    from r2.opportunity.normalization import normalize_manual_page

    root = Path(__file__).resolve().parents[2]
    components = (
        "server/services/m9_manual_publication.py",
        "server/services/m9_manual_authenticity.py",
        "r2/opportunity/manual_import.py",
        "server/services/m9_evidence_store.py",
        "lib/json_io.py",
        "r2/advanced_creative/digests.py",
        "r2/contracts/opportunity.py",
        "r2/opportunity/manual_admission.py",
        "r2/opportunity/acquisition_v2.py",
        "server/services/opportunity_acquisition_v2.py",
        "server/services/opportunity.py",
    )
    dependency_files = {}
    for name in (
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        "cryptography.hazmat.bindings._rust",
        "pydantic_core._pydantic_core",
    ):
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
        dependency_files[name] = _sha(Path(spec.origin).read_bytes())
    dependencies = {
        "python": sys.version,
        "lock": _sha((root / "uv.lock").read_bytes()),
        "files": dependency_files,
        "versions": {name: importlib.metadata.version(name) for name in ("cryptography", "pydantic", "pydantic-core")},
    }
    normalization = _sha((root / "r2/opportunity/normalization.py").read_bytes())
    decoder = _sha(
        canonical_json_bytes(
            {
                "source": normalization,
                "code": _sha(canonical_json_bytes(_code_state(decode_manual_payload.__code__))),
                "definitions": _sha(
                    canonical_json_bytes(_constant_state(decode_manual_payload.__globals__.get("_FIELDS")))
                ),
            }
        )
    )
    normalizer = _sha(
        canonical_json_bytes(
            {
                "decoder": decoder,
                "material_code": _sha(canonical_json_bytes(_code_state(original_manual_materials.__code__))),
                "object_code": _sha(canonical_json_bytes(_code_state(original_manual_object_specs.__code__))),
                "response_normalizer": _sha(canonical_json_bytes(_code_state(normalize_manual_page.__code__))),
                "checkpoint_verifier": _sha(
                    canonical_json_bytes(_code_state(OpportunityAcquisitionServiceV2._checkpoint.__code__))
                ),
            }
        )
    )
    return {
        "implementation_digest": _sha(
            canonical_json_bytes({name: _sha((root / name).read_bytes()) for name in components})
        ),
        "decoder_digest": decoder,
        "normalizer_digest": normalizer,
        "dependencies_digest": _sha(canonical_json_bytes(dependencies)),
    }


def manual_publication_config_digest(
    root: Path, *, declared_origin: str, uploader_id: str, store_namespace: str, resolver_namespace: str
) -> str:
    return _sha(
        canonical_json_bytes(
            {
                "root": str(root.absolute()),
                "declared_origin": declared_origin,
                "uploader_id": uploader_id,
                "store_namespace": store_namespace,
                "resolver_namespace": resolver_namespace,
            }
        )
    )


def _key_name(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest() + ".json"


def _ref_name(ref: str, kind: str) -> str:
    match = _REF.fullmatch(ref)
    if match is None or match[1] != kind:
        raise ValueError("invalid original publication reference")
    return match[2] + (".bin" if kind == "payload" else ".json")


def _read_file(directory: int, name: str, *, limit: int) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("publication object must be one regular file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("publication object exceeds bound")
    return raw


def _write_once(directory: int, name: str, raw: bytes) -> None:
    temporary = ".publication-stage." + name + "." + uuid4().hex + ".tmp"
    try:
        atomic_write_bytes(Path(f"/proc/self/fd/{directory}") / temporary, raw)
        try:
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            if _read_file(directory, name, limit=max(2_097_152, len(raw))) != raw:
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT) from None
        os.fsync(directory)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)


def _exists(directory: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _require_unblocked(directories: dict[str, int], refs: tuple[str, ...]) -> None:
    if any(_exists(directories["blocked"], _key_name(ref)) for ref in refs):
        raise OpportunityError(StopCode.M9_EVIDENCE_RETENTION_EXPIRED)


def _require_original_clocks(request: AdmissionRequest) -> None:
    now = datetime.now(UTC)
    if any(clock.captured_at > now for clock in request.original_clocks):
        raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
    if any(
        bound is not None and now >= bound
        for clock in request.original_clocks
        for bound in (clock.refresh_due_at, clock.retention_due_at)
    ):
        raise OpportunityError(StopCode.M9_EVIDENCE_RETENTION_EXPIRED)


def _require_read(envelope: AdmissionEnvelope, permit: AdmissionReadPermit) -> None:
    now = datetime.now(UTC)
    require_admission_access(envelope, now=now, operational=permit.operational)
    if envelope.deadlines is None or envelope.admitted_at is None:
        raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
    limits = [envelope.deadlines.retention_due_at]
    if permit.operational:
        limits.append(envelope.deadlines.refresh_due_at)
    deadline = min((bound for bound in limits if bound is not None), default=None)
    if permit.issued_at < envelope.admitted_at or permit.access_deadline != deadline:
        raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
    if (
        (permit.user_id, permit.project_name, permit.attempt_id, permit.envelope_version)
        != (
            envelope.request.context.user_id,
            envelope.request.context.project_name,
            envelope.request.attempt_id,
            envelope.version,
        )
        or not permit.issued_at <= now < permit.expires_at
        or (permit.expires_at - permit.issued_at).total_seconds() > 30
    ):
        raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
    require_admission_access(envelope, now=now, operational=permit.operational)


def manual_publication_metadata(
    request: AdmissionRequest, claim: str, objects: tuple[PublicationObjectRef, ...]
) -> PublicationReceiptMetadata:
    return manual_publication_metadata_for_request(request, claim, objects)


def manual_material_expectation(metadata: PublicationReceiptMetadata, obj: PublicationObjectRef) -> SealExpectation:
    return SealExpectation.model_validate(
        {
            **metadata.model_dump(exclude={"schema_version", "objects"}),
            **obj.model_dump(exclude={"retained_material_digest"}),
            "schema_version": "m9.manual-material-seal.v1",
        }
    )


def _signature(signature: bytes) -> str:
    if type(signature) is not bytes or len(signature) != 64:
        raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
    return base64.urlsafe_b64encode(signature).decode().rstrip("=")


def _new_object(request: AdmissionRequest, kind: str, classes: tuple[str, ...]) -> PublicationObjectRef:
    return PublicationObjectRef(
        payload_ref="m9-manual-payload:" + uuid4().hex,
        integrity_ref="m9-manual-integrity:" + uuid4().hex,
        attestation_ref="m9-manual-seal:" + uuid4().hex,
        evidence_kind=kind,
        data_classes=classes,
        data_rules=tuple(rule for rule in request.data_rules if rule.data_class in classes),
        original_clocks=tuple(clock for clock in request.original_clocks if clock.data_class in classes),
    )


def _original_rows(material: OriginalManualUpload) -> tuple[dict[str, object], ...]:
    if type(material.payload) is not bytes or re.fullmatch(r"m9-upload-claim:[0-9a-f]{32}", material.claim_ref) is None:
        raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
    body, rows = decode_manual_payload(material.payload)
    if (
        body["origin"] != material.declared_origin
        or body["uploader"] != material.uploader_id
        or (rows and {row["data_class"] for row in rows} != {rule.data_class for rule in material.request.data_rules})
    ):
        raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
    return rows


def original_manual_object_specs(material: OriginalManualUpload) -> tuple[tuple[str, tuple[str, ...]], ...]:
    rows = _original_rows(material)
    classes = tuple(sorted(rule.data_class for rule in material.request.data_rules))
    specs = [("raw-page", classes)]
    identities = sorted({str(row["source_native_id"]) for row in rows})
    for ordinal, native in enumerate(identities, 1):
        specs.append(
            (
                f"source-identity-{ordinal}",
                tuple(sorted({str(row["data_class"]) for row in rows if row["source_native_id"] == native})),
            )
        )
    specs.extend((f"native-field-{ordinal}", (str(row["data_class"]),)) for ordinal, row in enumerate(rows, 1))
    specs.append(("manual-native-index", classes))
    return tuple(specs)


def original_manual_materials(
    material: OriginalManualUpload, objects: tuple[PublicationObjectRef, ...]
) -> dict[str, tuple[bytes, bool]]:
    rows = _original_rows(material)
    by_kind = {obj.evidence_kind: obj for obj in objects}

    def retain(kind: str) -> bool:
        return all(rule.digest_proof_may_be_retained for rule in by_kind[kind].data_rules)

    result = {"raw-page": (material.payload, retain("raw-page"))}
    identities = {}
    for ordinal, native in enumerate(sorted({str(row["source_native_id"]) for row in rows}), 1):
        kind = f"source-identity-{ordinal}"
        identities[native] = by_kind[kind].payload_ref
        result[kind] = (
            canonical_json_bytes(
                {
                    "schema": "m9.manual-source-identity.v1",
                    "source_kind": "manual-import",
                    "source_contract_version": "manual-import.v1",
                    "native_id": native,
                }
            ),
            retain(kind),
        )
    fields = []
    for ordinal, row in enumerate(rows, 1):
        kind = f"native-field-{ordinal}"
        missing = row["missing_reason"] is not None
        body = {
            "schema": "m9.manual-native-value.v1",
            "source_kind": "manual-import",
            "source_contract_version": "manual-import.v1",
            **{key: value for key, value in row.items() if key not in ("source_native_id", "value", "missing_reason")},
            **({"missing_reason": row["missing_reason"]} if missing else {"value": row["value"]}),
        }
        raw = canonical_json_bytes(body)
        result[kind] = (raw, not missing and retain(kind))
        obj = by_kind[kind]
        fields.append(
            NativeFieldMaterial.model_validate(
                {
                    **{key: value for key, value in row.items() if key not in ("source_native_id", "value")},
                    "source_identity_ref": identities[str(row["source_native_id"])],
                    "material_ref": obj.payload_ref,
                    "material_integrity_ref": obj.integrity_ref,
                    "value_ref": None if missing else obj.payload_ref,
                    "value_integrity_ref": None if missing else obj.integrity_ref,
                    "retained_normalized_value_digest": _sha(raw) if not missing and retain(kind) else None,
                }
            )
        )
    result["manual-native-index"] = (
        canonical_json_bytes({"schema": "m9.manual-native-index.v1", "fields": fields}),
        retain("manual-native-index"),
    )
    return result


def _deletion_targets(headers: tuple[PublicationHeader, ...]) -> set[tuple[str, str]]:
    result = {("headers", _key_name(header.metadata.publication_key)) for header in headers}
    for header in headers:
        for obj in header.metadata.objects:
            result.update(
                (
                    ("payloads", _ref_name(obj.payload_ref, "payload")),
                    ("integrities", _ref_name(obj.integrity_ref, "integrity")),
                    ("attestations", _ref_name(obj.attestation_ref, "seal")),
                )
            )
    return result


def _verify_job(store: FileManualPublicationStore, job: _DeletionJob, closure: AdmissionClosureIntent) -> None:
    if job.closure != closure or not any(
        header.metadata.attempt_id == closure.attempt_id and header.metadata.attempt_version <= closure.attempt_version
        for header in job.headers
    ):
        raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
    refs = set()
    for header in job.headers:
        store.verifier.verify_receipt(canonical_json_bytes(header), expected=header.metadata)
        if (header.metadata.context.user_id, header.metadata.context.project_name) != (
            store.user_id,
            store.project_name,
        ):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        refs.add(header.metadata.publication_key)
        refs.update(
            ref for obj in header.metadata.objects for ref in (obj.payload_ref, obj.integrity_ref, obj.attestation_ref)
        )
    if refs != set(closure.object_refs) or (
        job.receipt is not None and (job.receipt.closure != closure or job.receipt.retained_proofs)
    ):
        raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)


def _constant_state(value: object) -> object:
    if isinstance(value, CodeType):
        return {"code": _code_state(value)}
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, float):
        return {"float": value.hex()}
    if isinstance(value, complex):
        return {"complex": [value.real.hex(), value.imag.hex()]}
    if isinstance(value, tuple):
        return {"tuple": [_constant_state(item) for item in value]}
    if isinstance(value, frozenset):
        return {"frozenset": sorted((_constant_state(item) for item in value), key=canonical_json_bytes)}
    if isinstance(value, dict):
        return {
            "dict": sorted(
                ([_constant_state(key), _constant_state(item)] for key, item in value.items()), key=canonical_json_bytes
            )
        }
    if value is Ellipsis:
        return {"ellipsis": True}
    raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)


def _code_state(code: CodeType) -> dict[str, object]:
    return {
        "bytecode": code.co_code.hex(),
        "constants": [_constant_state(value) for value in code.co_consts],
        "names": code.co_names,
        "variables": code.co_varnames,
        "freevars": code.co_freevars,
        "cellvars": code.co_cellvars,
        "args": (code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount),
        "flags": code.co_flags,
        "stacksize": code.co_stacksize,
        "locals": code.co_nlocals,
        "name": code.co_qualname,
        "filename": code.co_filename,
        "first_line": code.co_firstlineno,
        "line_table": code.co_linetable.hex(),
        "exception_table": code.co_exceptiontable.hex(),
    }
