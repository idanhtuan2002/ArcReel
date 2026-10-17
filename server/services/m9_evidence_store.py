"""Scoped erasable host files; publication and deletion serialize across processes."""

from __future__ import annotations

import asyncio
import base64
import fcntl
import hashlib
import json
import os
import re
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from lib.json_io import atomic_write_bytes
from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical
from r2.contracts.opportunity import ErasableEvidencePayload, PayloadDeletionRequest, PayloadDeletionResult, PayloadRef
from r2.opportunity.errors import OpportunityError, StopCode

_REF = re.compile(r"m9-(payload|integrity|identity):([0-9a-f]{32}):[0-9a-f]{32}")
_OPEN_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class FileSnapshotEvidenceStore:
    def __init__(self, root: Path, *, user_id: str, project_name: str) -> None:
        self._root = root.absolute()
        self._scope = {"user_id": user_id, "project_name": project_name}
        self._scope_key = hashlib.sha256(canonical_json_bytes(self._scope)).hexdigest()
        if any(p.is_symlink() for p in (self._root, *self._root.parents)):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def _locked(self) -> Generator[tuple[int, int]]:
        root = os.open(self._root, _OPEN_DIR)
        scope = lock = objects = keys = -1
        try:
            with suppress(FileExistsError):
                os.mkdir(self._scope_key, mode=0o700, dir_fd=root)
            scope = os.open(self._scope_key, _OPEN_DIR, dir_fd=root)
            lock = os.open("lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=scope)
            fcntl.flock(lock, fcntl.LOCK_EX)
            for name in ("objects", "keys"):
                with suppress(FileExistsError):
                    os.mkdir(name, mode=0o700, dir_fd=scope)
            objects = os.open("objects", _OPEN_DIR, dir_fd=scope)
            keys = os.open("keys", _OPEN_DIR, dir_fd=scope)
            for directory in (objects, keys):
                for name in os.listdir(directory):
                    if name.startswith(".rollback.") and name.endswith(".tmp"):
                        os.unlink(name, dir_fd=directory)
                os.fsync(directory)
            os.fsync(scope)
            os.fsync(root)
            yield objects, keys
            os.fsync(scope)
        finally:
            for fd in (keys, objects, lock, scope, root):
                if fd >= 0:
                    os.close(fd)

    @staticmethod
    def _read(directory: int, name: str) -> dict[str, Any]:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            import stat

            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("not a regular file")
            raw = stream.read(8_388_609)
            if len(raw) > 8_388_608:
                raise ValueError("evidence envelope exceeds host bound")
            value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("evidence object must be a mapping")
        return value

    @staticmethod
    def _write(directory: int, name: str, body: dict[str, Any]) -> None:
        # A stable directory descriptor prevents traversing a swapped child symlink.
        raw = canonical_json_bytes(body)
        if len(raw) > 8_388_608:
            raise OpportunityError(StopCode.M9_OPERATIONAL_ENVELOPE_EXCEEDED)
        atomic_write_bytes(Path(f"/proc/self/fd/{directory}") / name, raw)
        os.fsync(directory)

    def _object(self, objects: int, ref: str, kind: str) -> tuple[str, dict[str, Any]]:
        match = _REF.fullmatch(ref)
        if match is None or match[1] != kind:
            raise ValueError("invalid opaque evidence reference")
        object_id = match[2]
        name = ("identity." if kind == "identity" else "") + object_id + ".json"
        body = self._read(objects, name)
        if body["scope"] != self._scope:
            raise ValueError("evidence scope differs")
        expected = (body["identity_ref"],) if kind == "identity" else (body[kind + "_ref"],)
        if ref not in expected:
            raise ValueError("unknown evidence reference")
        return object_id, body

    def _identity(self, keys: int, native_id: str) -> str:
        for name in os.listdir(keys):
            if not re.fullmatch(r"identity\.[0-9a-f]{32}\.json", name):
                continue
            body = self._read(keys, name)
            if body["scope"] != self._scope:
                raise ValueError("identity scope differs")
            if body["native_id"] == native_id:
                return str(body["identity_ref"])
        object_id = uuid4().hex
        ref = f"m9-identity:{object_id}:{uuid4().hex}"
        name = "identity." + object_id + ".json"
        try:
            os.stat(name, dir_fd=keys, follow_symlinks=False)
        except FileNotFoundError:
            self._write(keys, name, {"scope": self._scope, "identity_ref": ref, "native_id": native_id})
        else:
            raise ValueError("opaque identity collision")
        return ref

    @staticmethod
    def _binding(body: dict[str, Any]) -> str:
        return digest_canonical(
            {
                key: body[key]
                for key in (
                    "scope",
                    "key",
                    "payload_ref",
                    "integrity_ref",
                    "raw_payload",
                    "media_type",
                    "data_classes",
                    "identity_refs",
                    "retain_digest_proof",
                )
            }
        )

    @staticmethod
    def _payload_ref(body: dict[str, Any]) -> PayloadRef:
        return PayloadRef(
            payload_ref=body["payload_ref"],
            payload_integrity_ref=body["integrity_ref"],
            source_identity_refs=tuple(body["identity_refs"]),
            retained_content_digest=body["retained_content_digest"],
            raw_size_bytes=body["raw_size_bytes"],
        )

    async def put_if_absent(self, payload: ErasableEvidencePayload) -> PayloadRef:
        return await self._safe(lambda: self._put(payload))

    def _put(self, payload: ErasableEvidencePayload) -> PayloadRef:
        if {"user_id": payload.user_id, "project_name": payload.project_name} != self._scope:
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        key = hashlib.sha256(
            canonical_json_bytes(
                {
                    "scope": self._scope,
                    "attempt_id": payload.attempt_id,
                    "ordinal": payload.page_ordinal,
                    "kind": payload.evidence_kind,
                }
            )
        ).hexdigest()
        with self._locked() as (objects, keys):
            try:
                object_id = self._read(keys, key + ".json")["object_id"]
                if not re.fullmatch("[0-9a-f]{32}", object_id):
                    raise ValueError("invalid evidence index")
                body = self._read(objects, object_id + ".json")
            except FileNotFoundError:
                matches = []
                for name in os.listdir(objects):
                    if not re.fullmatch(r"[0-9a-f]{32}\.json", name):
                        # Unpublished fsynced temporary files have no public refs.
                        continue
                    candidate = self._read(objects, name)
                    if candidate["key"] == key:
                        matches.append((name[:-5], candidate))
                if len(matches) > 1:
                    raise ValueError("ambiguous evidence publication") from None
                if matches:
                    object_id, body = matches[0]
                else:
                    object_id = uuid4().hex

                    def new_ref(kind: str) -> str:
                        return f"m9-{kind}:{object_id}:{uuid4().hex}"

                    raw_digest = _sha(payload.raw_payload)
                    body = {
                        "schema": "m9.erasable-bundle.v1",
                        "scope": self._scope,
                        "key": key,
                        "payload_ref": new_ref("payload"),
                        "integrity_ref": new_ref("integrity"),
                        "identity_refs": {self._identity(keys, native): None for native in payload.source_native_ids},
                        "raw_payload": base64.b64encode(payload.raw_payload).decode("ascii"),
                        "media_type": payload.raw_media_type,
                        "data_classes": payload.data_classes,
                        "retain_digest_proof": payload.retain_digest_proof,
                        "retained_content_digest": raw_digest if payload.retain_digest_proof else None,
                        "raw_size_bytes": len(payload.raw_payload),
                        "erased": False,
                    }
                    body["integrity"] = {"content_digest": raw_digest, "binding_digest": self._binding(body)}
                    try:
                        os.stat(object_id + ".json", dir_fd=objects, follow_symlinks=False)
                    except FileNotFoundError:
                        self._write(objects, object_id + ".json", body)
                    else:
                        raise ValueError("opaque object identity collision") from None
                self._write(keys, key + ".json", {"object_id": object_id})
            if body["scope"] != self._scope or body["key"] != key:
                raise ValueError("evidence index binding differs")
            if body["erased"]:
                raise OpportunityError(StopCode.M9_EVIDENCE_RETENTION_EXPIRED)
            raw = self._verified(body, body["payload_ref"], body["integrity_ref"])
            if (
                raw != payload.raw_payload
                or body["media_type"] != payload.raw_media_type
                or tuple(body["data_classes"]) != payload.data_classes
                or tuple(sorted(self._object(keys, ref, "identity")[1]["native_id"] for ref in body["identity_refs"]))
                != tuple(sorted(payload.source_native_ids))
                or body["retain_digest_proof"] is not payload.retain_digest_proof
            ):
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
            return self._payload_ref(body)

    def _verified(self, body: dict[str, Any], payload_ref: str, integrity_ref: str) -> bytes:
        if body["payload_ref"] != payload_ref or body["integrity_ref"] != integrity_ref or body["scope"] != self._scope:
            raise ValueError("evidence reference pair differs")
        if body["erased"] or body["raw_payload"] is None or body["integrity"] is None:
            raise ValueError("evidence erased")
        raw = base64.b64decode(body["raw_payload"], validate=True)
        if (
            len(raw) != body["raw_size_bytes"]
            or _sha(raw) != body["integrity"]["content_digest"]
            or self._binding(body) != body["integrity"]["binding_digest"]
        ):
            raise ValueError("evidence integrity differs")
        return raw

    async def verify_and_read(self, payload_ref: str, integrity_ref: str) -> bytes:
        def read() -> bytes:
            with self._locked() as (objects, keys):
                _, body = self._object(objects, payload_ref, "payload")
                self._object(objects, integrity_ref, "integrity")
                if any(self._object(keys, ref, "identity")[1]["native_id"] is None for ref in body["identity_refs"]):
                    raise ValueError("source identity erased")
                return self._verified(body, payload_ref, integrity_ref)

        return await self._safe(read)

    async def delete_exact(self, request: PayloadDeletionRequest) -> PayloadDeletionResult:
        return await self._safe(lambda: self._delete(request))

    def _delete(self, request: PayloadDeletionRequest) -> PayloadDeletionResult:
        if {"user_id": request.user_id, "project_name": request.project_name} != self._scope:
            raise ValueError("deletion scope differs")
        with self._locked() as (objects, keys):
            identities: dict[str, dict[str, Any]] = {}
            edits: dict[str, dict[str, Any]] = {}
            for kind, refs in (
                ("payload", request.payload_refs),
                ("identity", request.source_identity_refs),
                ("integrity", request.payload_integrity_refs),
            ):
                for ref in refs:
                    object_id, body = self._object(keys if kind == "identity" else objects, ref, kind)
                    (identities if kind == "identity" else edits).setdefault(object_id, body)
            for object_id, identity in identities.items():
                identity["native_id"] = None
                self._write(keys, "identity." + object_id + ".json", identity)
            proofs = set()
            for object_id, body in edits.items():
                if body["payload_ref"] in request.payload_refs:
                    body["raw_payload"] = None
                if body["integrity_ref"] in request.payload_integrity_refs:
                    body["integrity"] = None
                for ref in request.source_identity_refs:
                    if ref in body["identity_refs"]:
                        body["identity_refs"][ref] = None
                body["erased"] = True
                if not request.retain_permitted_digest_proofs or body["retain_digest_proof"] is not True:
                    body["retained_content_digest"] = None
                if body["retained_content_digest"] is not None:
                    proofs.add(body["retained_content_digest"])
                self._write(objects, object_id + ".json", body)
            fields = {
                "erased_payload_refs": request.payload_refs,
                "erased_identity_refs": request.source_identity_refs,
                "erased_integrity_refs": request.payload_integrity_refs,
                "retained_proof_digests": tuple(sorted(proofs)),
                "completed_at": datetime.now(UTC),
            }
            return PayloadDeletionResult(
                **fields, result_digest=digest_canonical({"domain": "m9.payload-deletion-result.v1", "body": fields})
            )

    @staticmethod
    async def _safe[T](operation: Callable[[], T]) -> T:
        try:
            return await asyncio.to_thread(operation)
        except OpportunityError:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH) from None
