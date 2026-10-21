"""Test-only original-upload ledger; issuer processes own every private file."""

from __future__ import annotations

import asyncio
import base64
import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import AwareDatetime, Field

from lib.json_io import atomic_write_bytes
from r2.advanced_creative.digests import canonical_json_bytes
from r2.contracts.opportunity import M9ContractModel
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.manual_admission import (
    AdmissionRequest,
    PublicationHeader,
    PublicationReceiptMetadata,
    PublishedAdmission,
    SealedObjectDescriptor,
    SealExpectation,
    publication_metadata_digest,
)
from r2.opportunity.normalization import decode_manual_payload
from server.services.m9_manual_publication import (
    FileManualPublicationStore,
    ManualSealVerifier,
    OriginalManualUpload,
    manual_material_expectation,
    manual_publication_metadata,
    original_manual_materials,
    original_manual_object_specs,
)

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class FixtureUploadAuthority(M9ContractModel):
    """Provisioned by the test owner, independently of an acquisition request."""

    request: AdmissionRequest
    declared_origin: str
    uploader_id: str


class _UploadIdentity(M9ContractModel):
    user_id: str
    project_name: str
    source_kind: Literal["manual-import"]
    source_contract_version: Literal["manual-import.v1"]
    opaque_upload_id: str
    upload_version: int = Field(ge=1, strict=True)


class _UploadIndex(M9ContractModel):
    schema_version: Literal["m9.fixture-upload-ledger.v1"]
    identity: _UploadIdentity
    claim_ref: str = Field(pattern=r"^m9-upload-claim:[0-9a-f]{32}$")
    public_key_digest: str
    phase: Literal["ACTIVE", "SPENT"]
    spent_at: AwareDatetime | None


class FixtureManualUploadCustodian:
    """Keep original comparison material outside the application publication root."""

    def __init__(
        self, private_root: Path, *, publication_root: Path | None = None, boundary: Callable[[str], None] | None = None
    ) -> None:
        self._root = private_root.absolute()
        self._boundary = boundary
        self._publication_root = publication_root.absolute() if publication_root is not None else None
        if self._publication_root is not None and (
            self._root.is_relative_to(self._publication_root) or self._publication_root.is_relative_to(self._root)
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)

    @contextmanager
    def _locked(self) -> Generator[int]:
        directory = lock = -1
        try:
            directory = os.open(self._root.anchor, _DIRECTORY)
            for part in self._root.parts[1:]:
                child = os.open(part, _DIRECTORY, dir_fd=directory)
                os.close(directory)
                directory = child
            self._private(os.fstat(directory), directory=True)
            lock = os.open("lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
            self._private(os.fstat(lock))
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield directory
        except OpportunityError:
            raise
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH) from None
        finally:
            for descriptor in (lock, directory):
                if descriptor >= 0:
                    os.close(descriptor)

    @staticmethod
    def _private(info: os.stat_result, *, directory: bool = False) -> None:
        kind = stat.S_ISDIR if directory else stat.S_ISREG
        if not kind(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("issuer private ownership differs")
        if not directory and info.st_nlink != 1:
            raise ValueError("issuer file cannot have another hard link")

    @classmethod
    def _read_bytes(cls, directory: int, name: str, *, limit: int = 4_194_304) -> bytes:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            cls._private(os.fstat(stream.fileno()))
            raw = stream.read(limit + 1)
        if not 0 < len(raw) <= limit:
            raise ValueError("issuer file exceeds bound")
        return raw

    @classmethod
    def _read_json(cls, directory: int, name: str) -> object:
        raw = cls._read_bytes(directory, name)
        value = json.loads(raw)
        if canonical_json_bytes(value) != raw:
            raise ValueError("issuer record is not canonical")
        return value

    @staticmethod
    def _write(directory: int, name: str, raw: bytes) -> None:
        atomic_write_bytes(Path(f"/proc/self/fd/{directory}") / name, raw)
        os.fsync(directory)

    @classmethod
    def _key(cls, directory: int) -> Ed25519PrivateKey:
        try:
            raw = cls._read_bytes(directory, "issuer.key", limit=32)
        except FileNotFoundError:
            # Missing original key with retained authority is never a new issuer identity.
            if set(os.listdir(directory)) - {"lock"}:
                raise ValueError("original issuer key missing") from None
            raw = Ed25519PrivateKey.generate().private_bytes_raw()
            cls._write(directory, "issuer.key", raw)
        return Ed25519PrivateKey.from_private_bytes(raw)

    @property
    def public_key(self) -> bytes:
        with self._locked() as directory:
            return self._key(directory).public_key().public_bytes_raw()

    @staticmethod
    def _identity(request: AdmissionRequest) -> _UploadIdentity:
        return _UploadIdentity(
            user_id=request.context.user_id,
            project_name=request.context.project_name,
            source_kind=request.descriptor.source_kind,
            source_contract_version=request.descriptor.source_contract_version,
            opaque_upload_id=request.opaque_upload_id,
            upload_version=request.upload_version,
        )

    @classmethod
    def _authority(cls, directory: int, request: AdmissionRequest) -> FixtureUploadAuthority:
        # Provisioning JSON may use whitespace; it is trusted input, never a ledger record.
        authority = FixtureUploadAuthority.model_validate_json(cls._read_bytes(directory, "authority.json"))
        original = authority.request
        if (
            cls._identity(request) != cls._identity(original)
            or request.context.actor_id != original.context.actor_id
            or request.descriptor != original.descriptor
            or request.data_rules != original.data_rules
            or request.original_clocks != original.original_clocks
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        public = cls._key(directory).public_key().public_bytes_raw()
        if request.descriptor.verification_key_digest != "sha256:" + hashlib.sha256(public).hexdigest():
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        return authority

    @classmethod
    def _index(cls, directory: int, name: str, request: AdmissionRequest) -> _UploadIndex:
        index = _UploadIndex.model_validate(cls._read_json(directory, name))
        if (
            index.identity != cls._identity(request)
            or index.public_key_digest != request.descriptor.verification_key_digest
            or (index.phase == "SPENT") != (index.spent_at is not None)
        ):
            raise ValueError("original upload index binding differs")
        return index

    @classmethod
    def _names(cls, request: AdmissionRequest) -> tuple[str, str, str]:
        upload = hashlib.sha256(canonical_json_bytes(cls._identity(request))).hexdigest()
        command = hashlib.sha256(
            canonical_json_bytes(
                {
                    "user_id": request.context.user_id,
                    "actor_id": request.context.actor_id,
                    "operation": "acquire",
                    "command_id": request.context.command_id,
                }
            )
        ).hexdigest()
        return "upload-" + upload + ".json", "material-" + upload + ".json", "command-" + command + ".json"

    def claim_original(self, request: AdmissionRequest) -> str:
        """Conditionally retain one random claim for exact original upload-version material."""
        request = AdmissionRequest.model_validate(request.model_dump())
        with self._locked() as directory:
            return self._claim_locked(directory, request)

    def _claim_locked(self, directory: int, request: AdmissionRequest) -> str:
        authority = self._authority(directory, request)
        index_name, material_name, command_name = self._names(request)
        try:
            index = self._index(directory, index_name, request)
        except FileNotFoundError:
            index = None
        if index is not None and index.phase == "SPENT":
            raise OpportunityError(StopCode.M9_EVIDENCE_RETENTION_EXPIRED)
        now = datetime.now(UTC)
        if any(
            bound is not None and now >= bound
            for clock in request.original_clocks
            for bound in (clock.refresh_due_at, clock.retention_due_at)
        ):
            raise OpportunityError(StopCode.M9_EVIDENCE_RETENTION_EXPIRED)
        raw = self._read_bytes(directory, "original.json", limit=2_097_152)
        body, rows = decode_manual_payload(raw)
        if (
            body["origin"] != authority.declared_origin
            or body["uploader"] != authority.uploader_id
            or (rows and {row["data_class"] for row in rows} != {rule.data_class for rule in request.data_rules})
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        comparison = {"raw": base64.b64encode(raw).decode(), "authority": authority.model_dump(mode="json")}
        expected_command = {"request": request.model_dump(mode="json")}
        try:
            command = self._read_json(directory, command_name)
        except FileNotFoundError:
            command = None
        if command is not None and (
            not isinstance(command, dict)
            or set(command) != {"request", "claim_ref"}
            or command["request"] != expected_command["request"]
            or index is None
            or command["claim_ref"] != index.claim_ref
        ):
            raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
        if index is not None:
            if self._read_json(directory, material_name) != comparison:
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
        else:
            try:
                os.stat(material_name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError("orphaned original comparison requires recovery")
            index = _UploadIndex(
                schema_version="m9.fixture-upload-ledger.v1",
                identity=self._identity(request),
                claim_ref="m9-upload-claim:" + uuid4().hex,
                public_key_digest=request.descriptor.verification_key_digest,
                phase="ACTIVE",
                spent_at=None,
            )
            self._write(directory, material_name, canonical_json_bytes(comparison))
            self._write(directory, index_name, canonical_json_bytes(index))
        if command is None:
            self._write(
                directory, command_name, canonical_json_bytes({**expected_command, "claim_ref": index.claim_ref})
            )
        return index.claim_ref

    def mark_spent(self, request: AdmissionRequest, *, claim_ref: str) -> None:
        """Fence reissue before unlinking comparison/ingest material without reading it."""
        request = AdmissionRequest.model_validate(request.model_dump())
        with self._locked() as directory:
            self._authority(directory, request)
            index_name, material_name, _ = self._names(request)
            index = self._index(directory, index_name, request)
            if index.claim_ref != claim_ref:
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
            if index.phase == "ACTIVE":
                index = index.model_copy(update={"phase": "SPENT", "spent_at": datetime.now(UTC)})
                self._write(directory, index_name, canonical_json_bytes(index))
            temporary_names = tuple(
                name
                for name in os.listdir(directory)
                if (name.startswith(".rollback.") and name.endswith(".tmp"))
                or (name.startswith("seal-") and name.endswith(".json"))
            )
            for name in (material_name, "original.json", *temporary_names):
                with suppress(FileNotFoundError):
                    os.unlink(name, dir_fd=directory)
            os.fsync(directory)

    @classmethod
    def _seal_name(cls, request: AdmissionRequest, kind: str) -> str:
        command = cls._names(request)[2].removeprefix("command-").removesuffix(".json")
        return "seal-" + command + "." + hashlib.sha256(kind.encode()).hexdigest() + ".json"

    @classmethod
    def _original_header(cls, directory: int, request: AdmissionRequest) -> PublicationHeader | None:
        try:
            record = cls._read_json(directory, cls._seal_name(request, "header"))
        except FileNotFoundError:
            return None
        if not isinstance(record, dict) or set(record) != {"preimage", "signature"}:
            raise ValueError("invalid original header issuance")
        preimage = base64.b64decode(record["preimage"], validate=True)
        domain = b"m9.manual-publication-receipt.v1\x00"
        if not preimage.startswith(domain):
            raise ValueError("original header issuance domain differs")
        body = json.loads(preimage[len(domain) :])
        return PublicationHeader.model_validate({**body, "signature": record["signature"]})

    def _sign_original(
        self, directory: int, request: AdmissionRequest, material: OriginalManualUpload, preimage: bytes
    ) -> bytes:
        header_domain = b"m9.manual-publication-receipt.v1\x00"
        material_domain = b"m9.manual-material-seal.v1\x00"
        if preimage.startswith(header_domain):
            body = json.loads(preimage[len(header_domain) :])
            if set(body) != {"metadata", "metadata_digest"} or header_domain + canonical_json_bytes(body) != preimage:
                raise ValueError("invalid original header signing preimage")
            metadata = PublicationReceiptMetadata.model_validate(body["metadata"])
            if metadata != manual_publication_metadata(request, material.claim_ref, metadata.objects) or body[
                "metadata_digest"
            ] != publication_metadata_digest(metadata):
                raise ValueError("original header authority differs")
            PublishedAdmission(
                request=request,
                publication_key=request.publication_key,
                claim_ref=material.claim_ref,
                upload_version=request.upload_version,
                objects=tuple(SealedObjectDescriptor(**obj.model_dump()) for obj in metadata.objects),
            )
            if {obj.evidence_kind: obj.data_classes for obj in metadata.objects} != dict(
                original_manual_object_specs(material)
            ):
                raise ValueError("original header material classes differ")
            kind = "header"
        elif preimage.startswith(material_domain):
            body = json.loads(preimage[len(material_domain) :])
            if set(body) != {"binding", "material_digest"} or material_domain + canonical_json_bytes(body) != preimage:
                raise ValueError("invalid original material signing preimage")
            header = self._original_header(directory, request)
            if header is None:
                raise ValueError("original planned header missing")
            expected = SealExpectation.model_validate(body["binding"])
            selected = [obj for obj in header.metadata.objects if obj.evidence_kind == expected.evidence_kind]
            if len(selected) != 1 or expected != manual_material_expectation(header.metadata, selected[0]):
                raise ValueError("original material object binding differs")
            drafts = original_manual_materials(material, header.metadata.objects)
            raw, _ = drafts[expected.evidence_kind]
            if body["material_digest"] != "sha256:" + hashlib.sha256(raw).hexdigest():
                raise ValueError("original source normalization differs")
            kind = "material:" + expected.evidence_kind
        else:
            raise ValueError("unapproved signing domain")
        name = self._seal_name(request, kind)
        try:
            record = self._read_json(directory, name)
        except FileNotFoundError:
            record = None
        encoded = base64.b64encode(preimage).decode()
        if record is not None:
            if (
                not isinstance(record, dict)
                or set(record) != {"preimage", "signature"}
                or record["preimage"] != encoded
            ):
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
            return base64.urlsafe_b64decode(record["signature"] + "==")
        signature = self._key(directory).sign(preimage)
        self._write(
            directory,
            name,
            canonical_json_bytes(
                {"preimage": encoded, "signature": base64.urlsafe_b64encode(signature).decode().rstrip("=")}
            ),
        )
        if self._boundary is not None:
            self._boundary("issuer-" + kind + "-seal-durable")
        return signature

    async def admit(self, request: AdmissionRequest) -> PublishedAdmission:
        return await asyncio.to_thread(self._admit, request)

    def _admit(self, request: AdmissionRequest) -> PublishedAdmission:
        if self._publication_root is None:
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
        request = AdmissionRequest.model_validate(request.model_dump())
        with self._locked() as directory:
            claim_ref = self._claim_locked(directory, request)
            authority = self._authority(directory, request)
            material = OriginalManualUpload(
                request=request,
                claim_ref=claim_ref,
                payload=self._read_bytes(directory, "original.json", limit=2_097_152),
                declared_origin=authority.declared_origin,
                uploader_id=authority.uploader_id,
                original_header=self._original_header(directory, request),
            )
            store = FileManualPublicationStore(
                self._publication_root,
                boundary=self._boundary,
                user_id=request.context.user_id,
                project_name=request.context.project_name,
                verifier=ManualSealVerifier(
                    public_key=self._key(directory).public_key().public_bytes_raw(),
                    verification_key_id=request.descriptor.verification_key_id,
                ),
            )
            return asyncio.run(
                store.publish_if_absent(
                    request, material, sign=lambda preimage: self._sign_original(directory, request, material, preimage)
                )
            )
