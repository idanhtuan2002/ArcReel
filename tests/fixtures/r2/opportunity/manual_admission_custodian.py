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
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import AwareDatetime, Field, model_validator

from lib.json_io import atomic_write_bytes
from r2.advanced_creative.digests import canonical_json_bytes
from r2.contracts.opportunity import M9ContractModel
from r2.opportunity.acquisition_v2 import (
    CustodianPublicationDisposition,
    CustodianSpendMetadata,
    CustodianSpendReceipt,
    CustodianSpendSubject,
    custodian_spend_metadata_digest,
    custodian_spend_preimage,
)
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
    verify_custodian_spent,
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


class _CustodyPublication(M9ContractModel):
    request: AdmissionRequest
    header: PublicationHeader | None = None


class _CustodyLedger(M9ContractModel):
    schema_version: Literal["m9.fixture-original-custody.v2"]
    public_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_key_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    history_complete: bool = Field(strict=True)
    phase: Literal["FRESH", "ACTIVE", "SPENT"]
    authority: FixtureUploadAuthority | None
    claim_ref: str | None
    publications: tuple[_CustodyPublication, ...]
    spent_at: AwareDatetime | None
    closure_id: str | None = None
    closing_request: AdmissionRequest | None = None
    receipt: CustodianSpendReceipt | None = None

    @model_validator(mode="after")
    def original_history(self) -> Self:
        if "sha256:" + hashlib.sha256(bytes.fromhex(self.public_key)).hexdigest() != self.public_key_digest:
            raise ValueError("original custody public key differs")
        if self.phase == "FRESH":
            if (
                self.authority is not None
                or self.claim_ref is not None
                or self.publications
                or self.spent_at is not None
                or self.closure_id is not None
                or self.closing_request is not None
                or self.receipt is not None
                or not self.history_complete
            ):
                raise ValueError("fresh custody must be its original empty ingestion state")
            return self
        if self.authority is None or not self.publications or (self.phase == "SPENT") != (self.spent_at is not None):
            raise ValueError("original custody history is incomplete")
        if self.phase == "ACTIVE" and self.claim_ref is None:
            raise ValueError("active original custody requires its recorded claim")
        if (self.closure_id is None) != (self.closing_request is None):
            raise ValueError("original closure binding is incomplete")
        if self.phase != "SPENT" and (self.closure_id is not None or self.receipt is not None):
            raise ValueError("original closure requires a spent fence")
        if self.receipt is not None and (
            self.receipt.metadata.root_request != self.closing_request
            or self.receipt.metadata.closure_id != self.closure_id
            or self.receipt.metadata.claim_ref != self.claim_ref
            or self.receipt.metadata.spent_at != self.spent_at
            or self.receipt.metadata.inventory_complete != self.history_complete
        ):
            raise ValueError("original closure receipt differs")
        commands = [(p.request.context.actor_id, p.request.context.command_id) for p in self.publications]
        keys = [p.request.publication_key for p in self.publications]
        if len(commands) != len(set(commands)) or len(keys) != len(set(keys)):
            raise ValueError("original custody publication identities conflict")
        source = self.authority.request
        for publication in self.publications:
            request = publication.request
            if (
                request.context.user_id,
                request.context.project_name,
                request.context.actor_id,
                request.descriptor,
                request.opaque_upload_id,
                request.upload_version,
                request.data_rules,
                request.original_clocks,
            ) != (
                source.context.user_id,
                source.context.project_name,
                source.context.actor_id,
                source.descriptor,
                source.opaque_upload_id,
                source.upload_version,
                source.data_rules,
                source.original_clocks,
            ):
                raise ValueError("original custody contains another upload authority")
            if publication.header is not None and (
                self.claim_ref is None or publication.header.metadata.claim_ref != self.claim_ref
            ):
                raise ValueError("original custody header claim differs")
        if self.receipt is not None and tuple(
            (p.request, p.header) for p in self.receipt.metadata.publications
        ) != tuple((p.request, p.header) for p in self.publications):
            raise ValueError("original receipt publication inventory differs")
        return self


class _SpendPlan(CustodianSpendSubject):
    schema_version: Literal["m9.fixture-custodian-spend.v1"]
    closure_id: str = Field(min_length=1)
    public_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    inventory_complete: bool = Field(strict=True)
    receipt: CustodianSpendReceipt | None = None

    @model_validator(mode="after")
    def original_receipt(self) -> Self:
        if self.claim_ref is None and (
            not self.inventory_complete or any(p.state != "NEVER_ISSUED" for p in self.publications)
        ):
            raise ValueError("unclaimed private spending requires positive no-issuance custody")
        if self.receipt is not None:
            metadata = self.receipt.metadata
            if (
                metadata.root_request,
                metadata.claim_ref,
                metadata.closure_id,
                metadata.publications,
                metadata.inventory_complete,
            ) != (
                self.root_request,
                self.claim_ref,
                self.closure_id,
                self.publications,
                self.inventory_complete,
            ):
                raise ValueError("private spending receipt differs from its original plan")
        return self


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
    def _read_json(cls, directory: int, name: str, *, limit: int = 4_194_304) -> object:
        raw = cls._read_bytes(directory, name, limit=limit)
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
            public = Ed25519PrivateKey.from_private_bytes(raw).public_key().public_bytes_raw()
            cls._write(
                directory,
                "custody.json",
                canonical_json_bytes(
                    _CustodyLedger(
                        schema_version="m9.fixture-original-custody.v2",
                        public_key=public.hex(),
                        public_key_digest="sha256:" + hashlib.sha256(public).hexdigest(),
                        history_complete=True,
                        phase="FRESH",
                        authority=None,
                        claim_ref=None,
                        publications=(),
                        spent_at=None,
                    )
                ),
            )
        return Ed25519PrivateKey.from_private_bytes(raw)

    @classmethod
    def _custody(cls, directory: int) -> _CustodyLedger | None:
        try:
            return _CustodyLedger.model_validate(cls._read_json(directory, "custody.json", limit=16_777_216))
        except FileNotFoundError:
            return None

    @classmethod
    def _write_custody(cls, directory: int, custody: _CustodyLedger) -> None:
        raw = canonical_json_bytes(custody)
        if len(raw) > (16_777_216 if custody.phase == "SPENT" else 4_194_304):
            raise OpportunityError(StopCode.M9_OPERATIONAL_ENVELOPE_EXCEEDED)
        cls._write(directory, "custody.json", raw)

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
        custody = cls._custody(directory)
        if custody is not None and (
            custody.public_key_digest != request.descriptor.verification_key_digest
            or (custody.authority is not None and custody.authority != authority)
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
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
        custody = self._custody(directory)
        if custody is not None and custody.phase == "SPENT":
            raise OpportunityError(StopCode.M9_EVIDENCE_RETENTION_EXPIRED)
        index_name, material_name, command_name = self._names(request)
        try:
            os.stat(self._spend_name(request), dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise OpportunityError(StopCode.M9_EVIDENCE_RETENTION_EXPIRED)
        try:
            index = self._index(directory, index_name, request)
        except FileNotFoundError:
            index = None
        if index is None and (custody is None or custody.phase != "FRESH"):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        if (
            index is not None
            and custody is not None
            and (custody.phase != "ACTIVE" or custody.claim_ref != index.claim_ref)
        ):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        if index is None and any(
            (name.endswith(".json") and name.startswith(("upload-", "material-", "command-", "seal-", "closure-")))
            or (name.startswith(".rollback.") and name.endswith(".tmp"))
            for name in os.listdir(directory)
        ):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
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
            if custody is None and command is None:
                raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        else:
            try:
                os.stat(material_name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError("orphaned original comparison requires recovery")
            claim_ref = "m9-upload-claim:" + uuid4().hex
            if custody is None:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            custody = _CustodyLedger.model_validate(
                {
                    **custody.model_dump(),
                    "phase": "ACTIVE",
                    "authority": authority,
                    "claim_ref": claim_ref,
                    "publications": (_CustodyPublication(request=request),),
                }
            )
            self._write_custody(directory, custody)
            index = _UploadIndex(
                schema_version="m9.fixture-upload-ledger.v1",
                identity=self._identity(request),
                claim_ref=claim_ref,
                public_key_digest=request.descriptor.verification_key_digest,
                phase="ACTIVE",
                spent_at=None,
            )
            self._write(directory, material_name, canonical_json_bytes(comparison))
            self._write(directory, index_name, canonical_json_bytes(index))
        if custody is not None:
            matches = [p for p in custody.publications if self._names(p.request)[2] == command_name]
            if matches and matches[0].request != request:
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
            if not matches:
                custody = _CustodyLedger.model_validate(
                    {
                        **custody.model_dump(),
                        "publications": (*custody.publications, _CustodyPublication(request=request)),
                    }
                )
                self._write_custody(directory, custody)
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
            self._spend_locked(directory, request, claim_ref=claim_ref)

    @classmethod
    def _spend_name(cls, request: AdmissionRequest) -> str:
        return "closure-" + cls._names(request)[0].removeprefix("upload-")

    @classmethod
    def _private_material_names(cls, directory: int, request: AdmissionRequest) -> tuple[str, ...]:
        material = cls._names(request)[1]
        return tuple(
            name
            for name in os.listdir(directory)
            if name in (material, "original.json")
            or (name.startswith(".rollback.") and name.endswith(".tmp"))
            or (name.startswith("seal-") and name.endswith(".json"))
        )

    def _spend_locked(
        self, directory: int, request: AdmissionRequest, *, claim_ref: str | None, plan: _SpendPlan | None = None
    ) -> datetime:
        index_name = self._names(request)[0]
        try:
            index = self._index(directory, index_name, request)
        except FileNotFoundError:
            index = None
        custody = self._custody(directory)
        if index is not None and index.claim_ref != claim_ref:
            raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
        if custody is not None and custody.claim_ref != claim_ref:
            raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
        if index is None and custody is None:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        spent_at = (
            custody.spent_at
            if custody is not None and custody.spent_at is not None
            else index.spent_at
            if index is not None and index.spent_at is not None
            else datetime.now(UTC)
        )
        if index is not None and index.spent_at is not None and index.spent_at != spent_at:
            raise ValueError("original spent timestamps differ")
        if custody is not None:
            changes = {"phase": "SPENT", "spent_at": spent_at}
            if plan is not None:
                if custody.closure_id is not None and (
                    custody.closure_id != plan.closure_id or custody.closing_request != request
                ):
                    raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
                changes.update(
                    authority=self._authority(directory, request),
                    publications=tuple(
                        _CustodyPublication(request=p.request, header=p.header) for p in plan.publications
                    ),
                    closure_id=plan.closure_id,
                    closing_request=request,
                )
            custody = _CustodyLedger.model_validate({**custody.model_dump(), **changes})
            self._write_custody(directory, custody)
        if claim_ref is not None:
            index = _UploadIndex(
                schema_version="m9.fixture-upload-ledger.v1",
                identity=self._identity(request),
                claim_ref=claim_ref,
                public_key_digest=request.descriptor.verification_key_digest,
                phase="SPENT",
                spent_at=spent_at,
            )
            self._write(directory, index_name, canonical_json_bytes(index))
        if self._boundary is not None:
            self._boundary("custodian-spent-fence-durable")
        for name in self._private_material_names(directory, request):
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            self._private(info)
            os.unlink(name, dir_fd=directory)
            os.fsync(directory)
            if self._boundary is not None:
                self._boundary("custodian-private-object-unlinked")
                header_suffix = "." + hashlib.sha256(b"header").hexdigest() + ".json"
                kind = (
                    "original"
                    if name == "original.json"
                    else "comparison"
                    if name.startswith("material-")
                    else "header"
                    if name.startswith("seal-") and name.endswith(header_suffix)
                    else "material-seal"
                    if name.startswith("seal-")
                    else "temporary"
                )
                self._boundary("custodian-" + kind + "-unlinked")
        if self._private_material_names(directory, request):
            raise ValueError("private original material remains")
        return spent_at

    def _new_spend_plan(
        self, directory: int, request: AdmissionRequest, *, claim_ref: str | None, closure_id: str
    ) -> _SpendPlan:
        custody = self._custody(directory)
        if custody is not None and custody.receipt is not None:
            receipt = verify_custodian_spent(
                canonical_json_bytes(custody.receipt),
                public_key=bytes.fromhex(custody.public_key),
                expected_request=request,
                closure_id=closure_id,
            )
            if claim_ref is not None and receipt.metadata.claim_ref != claim_ref:
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
            return _SpendPlan(
                schema_version="m9.fixture-custodian-spend.v1",
                root_request=request,
                claim_ref=receipt.metadata.claim_ref,
                closure_id=closure_id,
                public_key=custody.public_key,
                publications=receipt.metadata.publications,
                inventory_complete=receipt.metadata.inventory_complete,
                receipt=receipt,
            )
        self._authority(directory, request)
        publications = []
        if custody is not None:
            if claim_ref is not None and claim_ref != custody.claim_ref:
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
            claim_ref = custody.claim_ref
            if custody.closure_id is not None and (
                custody.closure_id != closure_id or custody.closing_request != request
            ):
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
            for entry in custody.publications:
                header = self._original_header(directory, entry.request)
                publications.append(
                    CustodianPublicationDisposition(
                        request=entry.request,
                        state="ORIGINAL_HEADER"
                        if header is not None
                        else ("NEVER_ISSUED" if custody.history_complete else "UNRESOLVED"),
                        header=header,
                    )
                )
            if request not in tuple(p.request for p in publications):
                if any(self._names(p.request)[2] == self._names(request)[2] for p in publications):
                    raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
                publications.append(
                    CustodianPublicationDisposition(
                        request=request,
                        state="NEVER_ISSUED" if custody.history_complete else "UNRESOLVED",
                        header=None,
                    )
                )
            public = bytes.fromhex(custody.public_key)
            complete = custody.history_complete
        else:
            index = self._index(directory, self._names(request)[0], request)
            if claim_ref is not None and index.claim_ref != claim_ref:
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
            claim_ref = index.claim_ref
            for command_name in sorted(os.listdir(directory)):
                if not (command_name.startswith("command-") and command_name.endswith(".json")):
                    continue
                command = self._read_json(directory, command_name)
                if not isinstance(command, dict) or set(command) != {"request", "claim_ref"}:
                    raise ValueError("invalid original command ledger")
                original = AdmissionRequest.model_validate(command["request"])
                self._authority(directory, original)
                if command["claim_ref"] != claim_ref or self._names(original)[2] != command_name:
                    raise ValueError("original command claim differs")
                header = self._original_header(directory, original)
                publications.append(
                    CustodianPublicationDisposition(
                        request=original,
                        state="ORIGINAL_HEADER" if header is not None else "UNRESOLVED",
                        header=header,
                    )
                )
            if request not in tuple(p.request for p in publications):
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            public = self._key(directory).public_key().public_bytes_raw()
            complete = False
        return _SpendPlan(
            schema_version="m9.fixture-custodian-spend.v1",
            root_request=request,
            claim_ref=claim_ref,
            closure_id=closure_id,
            public_key=public.hex(),
            publications=tuple(publications),
            inventory_complete=complete,
            receipt=custody.receipt if custody is not None else None,
        )

    def close_original(
        self, request: AdmissionRequest, *, claim_ref: str | None, closure_id: str
    ) -> CustodianSpendReceipt:
        """Retain original header inventory before spending and erasing private material."""
        request = AdmissionRequest.model_validate(request.model_dump())
        with self._locked() as directory:
            name = self._spend_name(request)
            try:
                plan = _SpendPlan.model_validate(self._read_json(directory, name, limit=16_777_216))
            except FileNotFoundError:
                plan = self._new_spend_plan(directory, request, claim_ref=claim_ref, closure_id=closure_id)
                if len(canonical_json_bytes(plan)) * 3 + 16384 > 16_777_216:
                    raise ValueError("private spending inventory exceeds bound") from None
                self._write(directory, name, canonical_json_bytes(plan))
                if self._boundary is not None:
                    self._boundary("custodian-spend-plan-durable")
            if claim_ref is None:
                claim_ref = plan.claim_ref
            if (plan.root_request, plan.claim_ref, plan.closure_id) != (request, claim_ref, closure_id):
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
            public = bytes.fromhex(plan.public_key)
            if "sha256:" + hashlib.sha256(public).hexdigest() != request.descriptor.verification_key_digest:
                raise ValueError("private spending original verification key differs")
            verifier = ManualSealVerifier(public_key=public, verification_key_id=request.descriptor.verification_key_id)
            for publication in plan.publications:
                if publication.header is not None:
                    PublishedAdmission(
                        request=publication.request,
                        publication_key=publication.request.publication_key,
                        claim_ref=claim_ref,
                        upload_version=publication.request.upload_version,
                        objects=tuple(
                            SealedObjectDescriptor(**obj.model_dump()) for obj in publication.header.metadata.objects
                        ),
                    )
                    expected = manual_publication_metadata(
                        publication.request, claim_ref, publication.header.metadata.objects
                    )
                    verifier.verify_receipt(canonical_json_bytes(publication.header), expected=expected)
            custody = self._custody(directory)
            if custody is not None:
                original_plan = self._new_spend_plan(directory, request, claim_ref=claim_ref, closure_id=closure_id)
                if plan.model_dump(exclude={"receipt"}) != original_plan.model_dump(exclude={"receipt"}):
                    raise ValueError("private spending plan differs from original custody")
                if original_plan.receipt is not None:
                    if plan.receipt is not None and plan.receipt != original_plan.receipt:
                        raise ValueError("private spending cached receipts differ")
                    plan = original_plan
            try:
                index = self._index(directory, self._names(request)[0], request)
            except FileNotFoundError:
                index = None
            if index is not None and index.claim_ref != plan.claim_ref:
                raise ValueError("private spending original index claim differs")
            if custody is not None and custody.claim_ref != plan.claim_ref:
                raise ValueError("private spending original custody claim differs")
            if plan.receipt is not None:
                if (
                    self._private_material_names(directory, request)
                    or (
                        index is not None
                        and (index.phase != "SPENT" or index.spent_at != plan.receipt.metadata.spent_at)
                    )
                    or (
                        custody is not None
                        and (custody.phase != "SPENT" or custody.spent_at != plan.receipt.metadata.spent_at)
                    )
                    or (index is None and custody is None)
                ):
                    raise ValueError("private spending receipt no longer proves absence")
                return verify_custodian_spent(
                    canonical_json_bytes(plan.receipt),
                    public_key=public,
                    expected_request=request,
                    closure_id=closure_id,
                )
            self._authority(directory, request)
            spent_at = self._spend_locked(directory, request, claim_ref=claim_ref, plan=plan)
            metadata = CustodianSpendMetadata(
                schema_version="m9.manual-custodian-spent.v2",
                operation="spend-original-upload",
                closure_id=closure_id,
                root_request=request,
                claim_ref=claim_ref,
                publications=plan.publications,
                inventory_complete=plan.inventory_complete,
                spent_at=spent_at,
                deleted_at=datetime.now(UTC),
            )
            signature = (
                base64.urlsafe_b64encode(self._key(directory).sign(custodian_spend_preimage(metadata)))
                .decode()
                .rstrip("=")
            )
            receipt = CustodianSpendReceipt(
                metadata=metadata, metadata_digest=custodian_spend_metadata_digest(metadata), signature=signature
            )
            verify_custodian_spent(
                canonical_json_bytes(receipt), public_key=public, expected_request=request, closure_id=closure_id
            )
            custody = self._custody(directory)
            if custody is not None:
                custody = _CustodyLedger.model_validate({**custody.model_dump(), "receipt": receipt})
                self._write_custody(directory, custody)
            self._write(directory, name, canonical_json_bytes(plan.model_copy(update={"receipt": receipt})))
            if self._boundary is not None:
                self._boundary("custodian-spend-receipt-durable")
            return receipt

    @classmethod
    def _seal_name(cls, request: AdmissionRequest, kind: str) -> str:
        command = cls._names(request)[2].removeprefix("command-").removesuffix(".json")
        return "seal-" + command + "." + hashlib.sha256(kind.encode()).hexdigest() + ".json"

    @classmethod
    def _original_header(cls, directory: int, request: AdmissionRequest) -> PublicationHeader | None:
        custody = cls._custody(directory)
        recorded = None
        if custody is not None:
            matches = [p for p in custody.publications if cls._names(p.request)[2] == cls._names(request)[2]]
            if len(matches) != 1 or matches[0].request != request:
                raise ValueError("original custody command binding missing")
            recorded = matches[0].header
        try:
            record = cls._read_json(directory, cls._seal_name(request, "header"))
        except FileNotFoundError:
            return recorded
        if not isinstance(record, dict) or set(record) != {"preimage", "signature"}:
            raise ValueError("invalid original header issuance")
        preimage = base64.b64decode(record["preimage"], validate=True)
        domain = b"m9.manual-publication-receipt.v1\x00"
        if not preimage.startswith(domain):
            raise ValueError("original header issuance domain differs")
        body = json.loads(preimage[len(domain) :])
        header = PublicationHeader.model_validate({**body, "signature": record["signature"]})
        if custody is not None and header != recorded:
            raise ValueError("original custody header contradicts its issuance record")
        return header

    def _retain_header(
        self,
        directory: int,
        request: AdmissionRequest,
        material: OriginalManualUpload,
        preimage: bytes,
        signature: bytes,
    ) -> None:
        custody = self._custody(directory)
        if custody is None:
            raise ValueError("original custody issuance ledger missing")
        if custody.phase != "ACTIVE" or custody.claim_ref != material.claim_ref:
            raise ValueError("original custody cannot issue a publication")
        body = json.loads(preimage[len(b"m9.manual-publication-receipt.v1\x00") :])
        header = PublicationHeader.model_validate(
            {
                **body,
                "signature": base64.urlsafe_b64encode(signature).decode().rstrip("="),
            }
        )
        matches = [p for p in custody.publications if self._names(p.request)[2] == self._names(request)[2]]
        if len(matches) != 1 or matches[0].request != request:
            raise ValueError("original custody publication command differs")
        if matches[0].header is not None and matches[0].header != header:
            raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
        publications = tuple(
            p.model_copy(update={"header": header}) if p.request == request else p for p in custody.publications
        )
        updated = _CustodyLedger.model_validate({**custody.model_dump(), "publications": publications})
        self._write_custody(directory, updated)
        if self._boundary is not None:
            self._boundary("custodian-original-header-durable")

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
            signature = base64.urlsafe_b64decode(record["signature"] + "==")
            if kind == "header" and self._custody(directory) is not None:
                self._retain_header(directory, request, material, preimage, signature)
            return signature
        if kind == "header" and self._custody(directory) is None:
            raise ValueError("missing original custody cannot become a new issuance")
        signature = self._key(directory).sign(preimage)
        if kind == "header":
            self._retain_header(directory, request, material, preimage, signature)
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
