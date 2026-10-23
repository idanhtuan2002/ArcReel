"""Offline recovery workers keep original issuer authority outside the application UID."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import signal
import stat
import sys
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, TextIO

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from r2.advanced_creative.digests import canonical_json_bytes
from r2.advanced_creative.exploration import uuid7
from r2.contracts.opportunity import (
    CapabilityEvaluationRequest,
    EffectiveCapabilityEvaluation,
    SourceCapabilityGrant,
    SourcePageRequest,
    SourcePageResult,
)
from r2.contracts.opportunity_acquisition_v2 import AcquireSourceQueryV2
from r2.opportunity.acquisition_v2 import CustodianSpendReceipt, ManualUploadMetadata, OpportunityAcquisitionServiceV2
from r2.opportunity.capabilities import validate_capability
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.manual_admission import (
    AdmissionClosureIntent,
    AdmissionEnvelope,
    AdmissionReadPermit,
    AdmissionRequest,
    FrozenManualBinding,
    ManualBindingDescriptor,
    ManualBindingRegistry,
    PublicationHeader,
    PublishedAdmission,
)
from scripts.r2.verify_m9_design_acceptance import loads_unique_json

UIDS = {"application": 31002, "issuer": 31001}
HEX = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
CASE = Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
_ACTIVE_SQL = ContextVar("manual_recovery_worker_active_sql", default=0)


class WorkerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    schema_version: Literal["m9.manual-recovery-worker.v1"] = "m9.manual-recovery-worker.v1"
    principal: Literal["application", "issuer"]
    run_id: HEX
    case_id: CASE
    scratch_root: Path
    publication_root: Path
    marker_root: Path
    boundary: str | None = None
    stop_after: str | None = None

    @model_validator(mode="after")
    def owned_paths(self):
        if (
            not self.scratch_root.is_absolute()
            or ".." in self.scratch_root.parts
            or self.publication_root != self.scratch_root / "publication"
            or self.marker_root != self.scratch_root / (self.principal + "-markers")
        ):
            raise ValueError("worker paths must name the explicit owned fixture children")
        return self


class ApplicationConfig(WorkerConfig):
    principal: Literal["application", "issuer"] = "application"
    operation: Literal["acquire", "reconstruct", "publication", "expire", "cleanup", "delete", "inspect"]
    database_url: SecretStr
    database_schema: Annotated[str, Field(pattern=r"^test_[0-9a-f]{12}$")]
    command: AcquireSourceQueryV2
    descriptor: ManualBindingDescriptor
    upload: ManualUploadMetadata
    public_key: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    grant: SourceCapabilityGrant
    evaluation: EffectiveCapabilityEvaluation
    broker_socket: Path
    source_fixture: Path
    source_fixture_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    closure: AdmissionClosureIntent | None = None
    spending_proof: CustodianSpendReceipt | None = None
    deletion_requests: tuple[AdmissionRequest, ...] = ()

    @model_validator(mode="after")
    def application_authority(self):
        if self.principal != "application":
            raise ValueError("application configuration requires its application principal")
        target = make_url(self.database_url.get_secret_value())
        if (target.drivername, target.host, target.port, target.database, target.username) != (
            "postgresql+asyncpg",
            "127.0.0.1",
            32768,
            "m9b",
            "m9test",
        ):
            raise ValueError("application worker requires the explicit disposable PostgreSQL target")
        if self.broker_socket != self.scratch_root / "broker.sock":
            raise ValueError("application worker cannot select another custodian socket")
        if (
            self.descriptor.verification_key_digest
            != "sha256:" + hashlib.sha256(bytes.fromhex(self.public_key)).hexdigest()
        ):
            raise ValueError("worker public key differs from its original descriptor")
        if (self.command.context.user_id, self.command.context.project_name) != (
            self.descriptor.user_id,
            self.descriptor.project_name,
        ):
            raise ValueError("worker command and descriptor scopes differ")
        if self.operation == "delete" and (
            self.closure is None or self.spending_proof is None or not self.deletion_requests
        ):
            raise ValueError("direct deletion requires its original authorized metadata")
        return self


class IssuerConfig(WorkerConfig):
    principal: Literal["application", "issuer"] = "issuer"
    operation: Literal["admit", "close"]
    private_root: Path
    request: AdmissionRequest
    claim_ref: str | None = None
    closure_id: str | None = None

    @model_validator(mode="after")
    def issuer_authority(self):
        if self.principal != "issuer":
            raise ValueError("issuer configuration requires its issuer principal")
        if self.private_root != self.scratch_root / "issuer":
            raise ValueError("issuer root differs from its owned fixture")
        if self.operation == "close" and not self.closure_id:
            raise ValueError("private closure requires its original SQL identity")
        return self


class SetupComplete(Exception):
    """An injected postcommit setup boundary returns retained authoritative state."""


def _directory_sync(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def journal(config: WorkerConfig, event: str) -> None:
    raw = (
        canonical_json_bytes({"event": event, "pid": os.getpid(), "uid": os.geteuid(), "run_id": config.run_id}) + b"\n"
    )
    path = config.marker_root / (config.run_id + ".journal.jsonl")
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "ab") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        _directory_sync(path.parent)


def boundary(config: WorkerConfig, name: str) -> None:
    if name == config.stop_after:
        raise SetupComplete
    if name != config.boundary:
        return
    body = {
        "schema": "m9-manual-recovery-arrival.v1",
        "case_id": config.case_id,
        "boundary": name,
        "pid": os.getpid(),
        "uid": os.geteuid(),
    }
    path = config.marker_root / (config.run_id + ".arrival.json")
    raw = canonical_json_bytes(body)
    durable_marker(path, raw)
    durable_marker(
        config.marker_root / (config.run_id + ".armed.json"),
        canonical_json_bytes(
            {
                "schema": "m9-manual-recovery-armed.v1",
                "case_id": config.case_id,
                "arrival_sha256": hashlib.sha256(raw).hexdigest(),
                "pid": os.getpid(),
            }
        ),
    )
    while True:
        signal.pause()


def durable_marker(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _directory_sync(path.parent)


def _port(config: WorkerConfig, event: str) -> None:
    if _ACTIVE_SQL.get() != 0:
        raise AssertionError("fixture port I/O occurred inside SQL")
    journal(config, event)


def verify_private_boundary(config: ApplicationConfig) -> None:
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    if any(int(status[name].strip(), 16) != 0 for name in ("CapEff", "CapPrm")) or status["NoNewPrivs"].strip() != "1":
        raise AssertionError("application requires unprivileged, non-escalating fixture credentials")
    for name in ("issuer.key", "custody.json"):
        try:
            descriptor = os.open(config.scratch_root / "issuer" / name, os.O_RDONLY | os.O_NOFOLLOW)
        except PermissionError:
            continue
        else:
            os.close(descriptor)
            raise AssertionError("application can open original issuer authority")
    journal(config, "private-authority-denied")


def _network_guard(config: ApplicationConfig) -> None:
    def audit(event, args):
        if event != "socket.connect":
            return
        _, address = args
        if address == str(config.broker_socket):
            return
        if isinstance(address, tuple) and address[:2] == ("127.0.0.1", 32768):
            return
        raise PermissionError("recovery fixture permits only its owned database and custodian socket")

    sys.addaudithook(audit)


def _deny_content_reads(publication_root: Path) -> None:
    forbidden = {
        p.name
        for name in ("payloads", "integrities", "attestations")
        for p in publication_root.rglob(name + "/*")
        if p.is_file()
    }

    def audit(event, args):
        if event != "open":
            return
        path, _, flags = args
        if (
            isinstance(path, str)
            and not flags & (os.O_WRONLY | os.O_RDWR | os.O_DIRECTORY)
            and Path(path).name in forbidden
        ):
            raise AssertionError("cleanup opened original content or a material seal")

    sys.addaudithook(audit)


class BrokerClient:
    def __init__(self, config: ApplicationConfig) -> None:
        self.config = config

    async def exchange(self, body: Mapping[str, object]) -> dict[str, object]:
        reader, writer = await asyncio.open_unix_connection(str(self.config.broker_socket), limit=16_777_217)
        try:
            writer.write(canonical_json_bytes(dict(body)) + b"\n")
            await writer.drain()
            raw = await reader.readline()
            if not raw or len(raw) > 16_777_216:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            result = loads_unique_json(raw)
            if "error" in result:
                raise OpportunityError(StopCode(result["error"]))
            return result
        finally:
            writer.close()
            await writer.wait_closed()

    async def admit(self, request: AdmissionRequest) -> PublishedAdmission:
        _port(self.config, "admit")
        result = await self.exchange({"operation": "admit", "request": request})
        return PublishedAdmission.model_validate(result["publication"])

    async def close_original(self, request: AdmissionRequest, *, claim_ref: str | None, closure_id: str) -> bytes:
        _port(self.config, "close")
        result = await self.exchange(
            {"operation": "close", "request": request, "claim_ref": claim_ref, "closure_id": closure_id}
        )
        return canonical_json_bytes(result["proof"])


class FixtureCapabilities:
    def __init__(self, config: ApplicationConfig) -> None:
        self.config = config

    async def resolve_grant(self, ref: str) -> SourceCapabilityGrant:
        _port(self.config, "resolve-grant")
        if ref != self.config.grant.grant_id:
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        return self.config.grant

    async def evaluate(self, request: CapabilityEvaluationRequest) -> EffectiveCapabilityEvaluation:
        _port(self.config, "evaluate")
        validate_capability(self.config.grant, self.config.evaluation, request, now=datetime.now(UTC))
        return self.config.evaluation


class FixtureSource:
    def __init__(self, config: ApplicationConfig) -> None:
        self.config = config

    async def fetch_page(self, request: SourcePageRequest) -> SourcePageResult:
        from r2.opportunity.manual_import import ManualImportSource

        config = self.config
        _port(config, "fetch")
        raw = config.source_fixture.read_bytes()
        condition = config.grant.conditions[0].model_dump()
        source = ManualImportSource(
            payload=raw,
            grant=config.grant,
            evaluation=config.evaluation,
            actor_id=config.command.context.actor_id,
            upload_ref=config.upload.opaque_upload_id,
            origin_ref=str(condition["origin_ref"]),
            declared_origin="synthetic-fixture",
            uploader_id="fixture-human",
            payload_digest=config.source_fixture_digest,
        )
        return await source.fetch_page(request)


async def application(config: ApplicationConfig) -> object:
    from server.services.m9_manual_publication import (
        FileManualPublicationStore,
        ManualSealVerifier,
        VerifiedManualCleanup,
        manual_publication_config_digest,
        manual_publication_measurements,
    )
    from server.services.opportunity_acquisition_v2 import HostManualAdmissionTransaction, HostManualAdmissionUnitOfWork

    verify_private_boundary(config)
    _network_guard(config)
    engine = create_async_engine(
        config.database_url.get_secret_value(),
        connect_args={"server_settings": {"search_path": config.database_schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    class ObservedStore(HostManualAdmissionUnitOfWork):
        @asynccontextmanager
        async def transaction(self) -> AsyncGenerator[HostManualAdmissionTransaction]:
            token = _ACTIVE_SQL.set(_ACTIVE_SQL.get() + 1)
            try:
                async with super().transaction() as tx:
                    yield tx
            finally:
                _ACTIVE_SQL.reset(token)

    public = FileManualPublicationStore(
        config.publication_root,
        user_id=config.descriptor.user_id,
        project_name=config.descriptor.project_name,
        verifier=ManualSealVerifier(
            public_key=bytes.fromhex(config.public_key), verification_key_id=config.descriptor.verification_key_id
        ),
        boundary=lambda name: boundary(config, name),
    )
    broker = BrokerClient(config)

    class Publication:
        async def lookup_receipt(self, key: str) -> PublicationHeader | None:
            _port(config, "lookup")
            return await public.lookup_receipt(key)

        async def read_verified(
            self, envelope: AdmissionEnvelope, *, object_ref: str, permit: AdmissionReadPermit
        ) -> bytes:
            _port(config, "read")
            return await public.read_verified(envelope, object_ref=object_ref, permit=permit)

        async def delete_exact(self, closure: AdmissionClosureIntent):
            _port(config, "legacy-delete")
            return await public.delete_exact(closure)

    def live_descriptor() -> ManualBindingDescriptor:
        measurements = manual_publication_measurements()
        return config.descriptor.model_copy(
            update={
                **measurements,
                "config_digest": manual_publication_config_digest(
                    config.publication_root,
                    declared_origin="synthetic-fixture",
                    uploader_id="fixture-human",
                    store_namespace=config.descriptor.store_namespace,
                    resolver_namespace=config.descriptor.resolver_namespace,
                ),
            }
        )

    async def checkpoint(name: str) -> None:
        boundary(config, name)

    store = ObservedStore(sessions, user_id=config.descriptor.user_id, project_name=config.descriptor.project_name)
    service = OpportunityAcquisitionServiceV2(
        store=store,
        registry=ManualBindingRegistry(
            (
                FrozenManualBinding(
                    config.descriptor,
                    bytes.fromhex(config.public_key),
                    FixtureSource(config),
                    broker,
                    Publication(),
                    live_descriptor,
                ),
            )
        ),
        descriptor=config.descriptor,
        upload=config.upload,
        capabilities=FixtureCapabilities(config),
        cleanup=VerifiedManualCleanup(
            descriptor=config.descriptor,
            publication=public,
            custodian=broker,
            declared_origin="synthetic-fixture",
            uploader_id="fixture-human",
        ),
        user_id=config.command.context.user_id,
        project_name=config.command.context.project_name,
        actor_id=config.command.context.actor_id,
        new_id=uuid7,
        boundary=checkpoint,
    )
    try:
        if config.operation in ("cleanup", "delete"):
            _deny_content_reads(config.publication_root)
        if config.operation == "delete":
            if config.closure is None or config.spending_proof is None:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            return await public.delete_recovery_exact(
                config.closure, proof=config.spending_proof, requests=config.deletion_requests
            )
        if config.operation == "inspect":
            async with store.transaction() as tx:
                attempt = await tx.manual.get_for_command(config.command)
                if attempt is None:
                    raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
                envelope = await tx.manual.get_envelope(attempt.attempt_id)
                if envelope is None:
                    raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
                permit = await tx.manual.begin_read(
                    attempt.attempt_id, expected_envelope_version=envelope.version, operational=True
                )
            try:
                for obj in envelope.objects:
                    _port(config, "read")
                    await public.read_verified(envelope, object_ref=obj.payload_ref, permit=permit)
                return {
                    "verified_objects": len(envelope.objects),
                    "admitted_at": envelope.admitted_at.isoformat() if envelope.admitted_at is not None else None,
                }
            finally:
                async with store.transaction() as tx:
                    await tx.manual.release_read(permit.lease_id)
        actions = {
            "acquire": service.acquire,
            "reconstruct": service.reconcile_manual_admission,
            "publication": service.reconcile_publication,
            "expire": service.expire_admission,
            "cleanup": service.reconcile_cleanup,
        }
        return await actions[config.operation](config.command)
    finally:
        await engine.dispose()


def issuer(config: IssuerConfig) -> object:
    from tests.fixtures.r2.opportunity.manual_admission_custodian import FixtureManualUploadCustodian

    custodian = FixtureManualUploadCustodian(
        config.private_root, publication_root=config.publication_root, boundary=lambda name: boundary(config, name)
    )
    if config.operation == "admit":
        return {"publication": asyncio.run(custodian.admit(config.request)).model_dump(mode="json")}
    header_suffix = "." + hashlib.sha256(b"header").hexdigest() + ".json"

    def audit(event, args):
        if event != "open":
            return
        path, _, flags = args
        if not isinstance(path, str) or flags & (os.O_WRONLY | os.O_RDWR | os.O_DIRECTORY):
            return
        name = Path(path).name
        if (
            name == "original.json"
            or name.startswith("material-")
            or (name.startswith("seal-") and not name.endswith(header_suffix))
            or (name.startswith(".rollback.") and name.endswith(".tmp"))
        ):
            raise AssertionError("private erasure opened original content or material seals")

    sys.addaudithook(audit)
    if config.closure_id is None:
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
    proof = custodian.close_original(config.request, claim_ref=config.claim_ref, closure_id=config.closure_id)
    return {"proof": proof.model_dump(mode="json")}


def read_configuration(path: Path) -> bytes:
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        authority = os.fstat(directory)
        if authority.st_uid != 0 or stat.S_IMODE(authority.st_mode) != 0o755:
            raise ValueError("worker configuration directory is not its trusted fixture authority")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) != 0o444
            ):
                raise ValueError("worker configuration must be the immutable fixture authority file")
            raw = stream.read(16_777_217)
    finally:
        os.close(directory)
    if not raw or len(raw) > 16_777_216:
        raise ValueError("worker configuration exceeds bound")
    return raw


def main(argv: list[str] | None = None, *, output: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--principal", required=True, choices=tuple(UIDS))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    identity = {"uid": os.geteuid(), "pid": os.getpid()}
    if os.geteuid() != UIDS[args.principal]:
        print(json.dumps({**identity, "error": "M9_WORKER_PRINCIPAL_MISMATCH"}), file=output)
        return 2
    try:
        raw = read_configuration(args.config)
        loads_unique_json(raw)
        kind = ApplicationConfig if args.principal == "application" else IssuerConfig
        config = kind.model_validate_json(raw)
        if config.run_id != args.run_id or config.principal != args.principal:
            raise ValueError("worker run identity differs")
        if args.config != config.scratch_root / "configuration" / (config.run_id + ".config.json"):
            raise ValueError("worker configuration is outside its exact registered fixture path")
    except (OSError, ValueError):
        print(json.dumps({**identity, "error": "M9_WORKER_CONFIGURATION_INVALID"}), file=output)
        return 2
    try:
        result = asyncio.run(application(config)) if isinstance(config, ApplicationConfig) else issuer(config)
        if isinstance(result, BaseModel):
            result = result.model_dump(mode="json")
        print(json.dumps({**identity, "result": result}), file=output)
        return 0
    except OpportunityError as error:
        try:
            code = StopCode(error.code).value
        except ValueError:
            code = "M9_WORKER_EXECUTION_FAILED"
        print(json.dumps({**identity, "error": code}), file=output)
        return 2
    except Exception as error:
        missing = error.name if isinstance(error, ModuleNotFoundError) else None
        if not isinstance(missing, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", missing) is None:
            missing = None
        print(
            json.dumps(
                {
                    **identity,
                    "error": "M9_WORKER_EXECUTION_FAILED",
                    "error_type": type(error).__name__,
                    "missing_module": missing,
                }
            ),
            file=output,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
