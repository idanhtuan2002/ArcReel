# M9-B custody source research — `cryptography` Ed25519 primitive

Date: 2026-10-20  
Repository baseline: `4c4861e9ae6fe74ca6828d676791ae203252e139` (`impl/r2-m9b-acquisition-observations`)  
Status: **QUALIFIED_PRIMITIVE_ONLY** — research evidence for the exact byte-signing primitive and API. This is not an upload-claim authority, implementation plan, release amendment, or acceptance pass.

## Question and bounded conclusion

Question: can the already installed `cryptography` Ed25519 implementation be qualified as the cryptographic primitive for a new, purpose-separated, erasable manual-upload material seal without treating the existing grant signer as upload authority?

**Conclusion:** yes, for the primitive only. At the locked and installed version `cryptography==50.0.0`, the direct API can serialize 32-byte raw keys, sign exact application-supplied bytes into a 64-byte signature, reconstruct a verifier from the raw public key, and reject a changed message, wrong key, or changed application binding. A deterministic synthetic probe demonstrated separate raw-payload and source-native-ID objects and rejected material, domain, opaque-ref, scope, key, and cross-object substitutions.

This result does **not** provide the manual-upload claim system required by the recovery amendment. The library signs bytes presented by its caller. It does not decide whether a signer may issue a claim, enforce one immutable `(owner, project, source kind/version, opaque upload ID, upload version)` record, durably remember spent/erased versions, prevent rollback, isolate the private key, reconcile publication, enforce clocks, or erase every dependent object. Those remain host/custodian protocol responsibilities and require their own implementation and fresh-process qualification.

## Exact dependency and primary-source pin

### Repository and installed environment facts

- `pyproject.toml:23` declares `cryptography>=50.0.0`.
- `uv.lock:831-838` resolves `cryptography` to exactly `50.0.0` and records the sdist SHA-256 as `eeac2acb5a20ed25e0ad6d1df9891a520b78b404266b6d11778f25d5d691a6c9`. This is a lockfile record; this research did not redownload and independently hash the sdist.
- The required interpreter `/home/anhtuan/content-production-os/.worktrees/r2-v2-main/.venv/bin/python` reported Python `3.13.14`, `cryptography 50.0.0`, and `OpenSSL 4.0.1 9 Jun 2026`.

### Pinned upstream source

The upstream `50.0.0` annotated tag resolves as follows:

- tag object: `f07c254c8d9b6c9b89d127129bf73a8550ad9fbd`
- source commit: `dcb7050b807b00392fa9fe2eac7cb362fcf355cc`

Primary-source links:

- [official `cryptography` 50.0.0 Ed25519 documentation](https://cryptography.io/en/50.0.0/hazmat/primitives/asymmetric/ed25519/)
- [50.0.0 tag reference API](https://api.github.com/repos/pyca/cryptography/git/ref/tags/50.0.0)
- [annotated tag object pointing to the source commit](https://api.github.com/repos/pyca/cryptography/git/tags/f07c254c8d9b6c9b89d127129bf73a8550ad9fbd)
- [Python Ed25519 API at the pinned commit](https://github.com/pyca/cryptography/blob/dcb7050b807b00392fa9fe2eac7cb362fcf355cc/src/cryptography/hazmat/primitives/asymmetric/ed25519.py)
- [Rust/OpenSSL implementation at the pinned commit](https://github.com/pyca/cryptography/blob/dcb7050b807b00392fa9fe2eac7cb362fcf355cc/src/rust/src/backend/ed25519.rs)
- [upstream Ed25519 tests at the pinned commit](https://github.com/pyca/cryptography/blob/dcb7050b807b00392fa9fe2eac7cb362fcf355cc/tests/hazmat/primitives/test_ed25519.py)

The GitHub tag-object response mapped the tag to the commit but reported its tag verification as `verified: false`, reason `bad_cert`. The commit is therefore an exact source pin for this qualification; this pass did not independently establish the annotated tag's signature authenticity.

The official 50.0.0 documentation specifies that `from_private_bytes` and `from_public_bytes` consume 32-byte raw keys, `sign(data)` returns a 64-byte signature, and `verify(signature, data)` returns normally on success or raises `InvalidSignature`. It also defines `private_bytes_raw` and `public_bytes_raw` as the raw serialization shortcuts. The pinned Python module delegates generation, raw loading, signing, verification, and serialization to its Rust OpenSSL binding. The pinned Rust source uses `Signer::new_without_digest` plus `sign_oneshot`, and `Verifier::new_without_digest` plus `verify_oneshot`; unsuccessful verification becomes `InvalidSignature`.

[RFC 8032](https://www.rfc-editor.org/rfc/rfc8032.html) defines Ed25519 signatures over the message bytes and explains that contexts separate protocols and uses; a context should be a protocol-defined constant. The `cryptography` API exercised here exposes plain `sign(data)` / `verify(signature, data)`, with no separate context argument. Consequently, the application must make purpose separation part of the exact signed bytes and must reject absent or changed domain/version fields before granting meaning to a valid signature. The probe demonstrates that byte binding; it does not freeze the production wire format.

## Existing repository surfaces and reuse boundary

Tier-2 graph verification used project `r2-m9b`, generation `2026-10-20T00:39:00Z` recorded at `2026-10-20T00:42:36Z`. Relevant graph results had no pagination remainder. Exact source was also read.

- `r2/governance/ceremony.py:1-5,64-88` already exercises the same library primitive with 32-byte raw private keys, raw public-key serialization, canonical bytes, and unpadded base64url signatures. That is positive in-repository API evidence.
- `r2/governance/ceremony.py:178-213` proves why its authority must not be reused by inference: `sign_grant_event` builds `governance.showrunner_grant_event.v1` records for `ISSUE`/`REVOKE`, fixes role `HUMAN_SHOWRUNNER`, and binds grant sequence/predecessor state. It has no upload claim, upload-version ledger, material bytes/ref, custody classes, or erasure call surface.
- `r2/contracts/showrunner_grant.py:100-143` parses the exact canonical grant envelope but explicitly does not verify the signature. `r2/governance/grant_signature.py:18-33` verifies under a caller-pinned grant key and explicitly leaves scope, sequence, and currentness to importers. A correct Ed25519 signature alone is therefore not complete authority even in the existing grant domain.
- `server/services/governance_attestation.py:142-172` handles a startup challenge by preflighting the operator archive and returning public archive digests. It neither accepts material nor issues upload claims.
- `server/services/m9_evidence_store.py:158-250` publishes payload objects with co-located unkeyed SHA-256 and binding digests, then checks those values on read. `:264-308` can erase current evidence fields. These I/O and erasure mechanics do not authenticate bytes against an independent custodian when the filesystem owner can replace the object and recompute ordinary hashes.

The qualified reuse is therefore limited to the installed `cryptography` Ed25519 primitive and its direct key/sign/verify/serialization API. The existing governance key, signer role, grant schemas, grant verifier, archive attestor, and their authorization are **not** qualified as manual-upload authority. No separate external service or signer donor was selected; the pinned library source itself is the external implementation examined.

Graph coverage was checked for `pyproject.toml`, `r2/governance/ceremony.py`, `r2/contracts/showrunner_grant.py`, `r2/governance/grant_signature.py`, `server/services/governance_attestation.py`, and `server/services/m9_evidence_store.py`: all reported `metadata_match` and `no_recorded_issue`. That is a best-effort signal, not proof of exhaustive repository coverage. `uv.lock`, `.superpowers/`, docs, and scripts are excluded from this graph and were read directly. This bounded pass makes no exhaustive reuse-absence claim.

## Synthetic direct-API probe

Artifact: `probe_ed25519_manual_upload_seal.py` in this same ignored directory.

Command:

```bash
/home/anhtuan/content-production-os/.worktrees/r2-v2-main/.venv/bin/python \
  .superpowers/sdd/2026-10-16-r2-m9b-acquisition-observations/probe_ed25519_manual_upload_seal.py
```

The probe uses two fixed, public synthetic 32-byte private seeds. It does not access a production credential, signer endpoint, database, runtime module, or provider. Its canonical JSON claim is a probe-only framing, not a selected public contract. It signs two distinct objects independently:

1. a `RAW_PAYLOAD` object containing the actual synthetic upload bytes;
2. a `SOURCE_NATIVE_ID` object containing the actual synthetic native identifier bytes.

Each signed body includes a fixed purpose domain, schema, object kind, opaque object ref, owner/project scope, stable upload-claim identity, upload version, and the object's material. This demonstrates the primitive's ability to bind all of those bytes. Production must still define and strictly parse a successor schema and must keep each seal and its content proof inside the corresponding erasable object rather than retaining them in SQL when the data class forbids that retention.

### Fresh observation

Exit status: `0`.

| Check | Observation |
|---|---|
| installed version | `50.0.0` |
| raw private-key serialization | 32 bytes; round-trip equal |
| raw public-key serialization | 32 bytes; reconstructed verifier accepted original signatures |
| signature serialization | 64 bytes; unpadded base64url encode/decode round trip verified |
| raw-payload baseline | `VERIFIED` |
| native-ID baseline | `VERIFIED` |
| changed material bytes | `REJECTED_INVALID_SIGNATURE` |
| wrong public key | `REJECTED_INVALID_SIGNATURE` |
| changed purpose domain | `REJECTED_INVALID_SIGNATURE` |
| changed opaque object ref | `REJECTED_INVALID_SIGNATURE` |
| changed project scope | `REJECTED_INVALID_SIGNATURE` |
| native-ID signature substituted for raw payload | `REJECTED_INVALID_SIGNATURE` |

Deterministic fixture outputs:

- public key, base64url: `TLWr9q15-_WrvMr8wmnYXNJlHtS4hbWGnyQa7fCluik`
- raw claim SHA-256: `sha256:750912f3318fa0020c4f9d7fefbf279829e55403097f586de7b9927d7551a775`
- raw signature, base64url: `cjOae1C-8GYbR6040swrYtaTTQeDn5dYg5TWsNlfO1CV_0kdLnOLJqX5bnUgKdtpNuZacjlMfVDlhioR7wgOAQ`
- native claim SHA-256: `sha256:1a562cdc760de75d1ea52a74472d1900c479323dcb37ea56e0755c6454dd6348`
- native signature, base64url: `xKa4VzpU9dqIwFuk_57jUVHo-AwGFDzH8Hk51LBnIXP4Jrmdtq-hxL1nrr75bTYjJTyLAkHcpkzXHWfkJffqCQ`

These are direct observations of the exact installed library under one synthetic fixture. They are not claims about process isolation, persistence, concurrency, or production provisioning.

## What remains unqualified

The following requirements cannot be supplied by the Ed25519 primitive and remain mandatory, separate qualification gates:

- **Immutable upload claim:** a durable private ledger must enforce one original material claim per stable upload version, return equal replay, conflict on different material/metadata, and keep erased versions spent. Signing arbitrary caller-supplied bytes would not meet this requirement.
- **Signer authorization and key isolation:** a separately measured offline custodian issuer process must own the new Ed25519 private key and claim ledger. The host/runtime/test writer must receive only the public verification identity and opaque results. The existing governance key is not authorized for this purpose.
- **Anti-rollback and currentness:** a signature authenticates the signed bytes under a key. It does not prove that the claim is the newest authorized record, that a version was not erased, or that a filesystem owner did not replay an older valid object. Retained authoritative state and monotonic/version guards are still required.
- **Erasure:** the library has no deletion or retention API. Raw material, native identity, each per-object seal, signatures, content proofs, indexes, and comparison material must be included in the same fenced erasure closure. SQL must not retain a forbidden digest/signature merely because verification succeeded.
- **Scope, clocks, and policy:** cryptography verifies byte equality and key possession. Strict schema validation, owner/project/source/ref checks, data-class access deadlines, current policy/scope, frozen binding measurements, and final guarded revalidation remain application responsibilities.
- **Publication and crash recovery:** no header lookup, conditional publication, ACK-loss recovery, orphan reconciliation, lease, exact deletion receipt, or process-safe reopen behavior is provided by Ed25519.
- **Production support:** no production private key, signer endpoint, root, rotation/revocation procedure, or deployment authority was created or selected by this research.

The next plan may depend on `cryptography==50.0.0` as the byte-level primitive without adding a dependency. It must treat the upload claim ledger, custodian issuer, public verifier, per-object erasable storage, authority separation, and recovery/erasure protocol as new bounded work with their own fixtures and acceptance evidence.


## Retained executable probe and main-session reproduction

The following source is a standalone synthetic research probe, not runtime signing authority. The main session independently reran it with the documented interpreter, exit0.

```python
"""Synthetic direct-API probe for a purpose-separated manual-upload seal.

This is research evidence, not the production claim format or an authority implementation.
The fixed private seeds are public test fixtures and must never be used as credentials.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from typing import Any

import cryptography
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


DOMAIN = "arcreel.m9.manual-upload-material-seal.v1"
FIXTURE_PRIVATE_RAW = bytes.fromhex("00" * 31 + "01")
WRONG_PRIVATE_RAW = bytes.fromhex("00" * 31 + "02")


def canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decoded(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def material_claim(*, object_kind: str, object_ref: str, material: bytes) -> dict[str, Any]:
    return {
        "domain": DOMAIN,
        "schema": "probe.manual-upload-material-seal.v1",
        "object_kind": object_kind,
        "object_ref": object_ref,
        "scope": {"owner": "probe-owner", "project": "probe-project"},
        "upload_claim": {
            "source_kind": "MANUAL_IMPORT",
            "source_contract_version": "manual-import.v1",
            "opaque_upload_id": "probe-upload-01",
            "upload_version": 1,
        },
        "material_b64": base64.b64encode(material).decode("ascii"),
    }


def expect_invalid(
    observations: dict[str, str],
    name: str,
    public_key: Ed25519PublicKey,
    signature: bytes,
    claim: dict[str, Any],
) -> None:
    try:
        public_key.verify(signature, canonical(claim))
    except InvalidSignature:
        observations[name] = "REJECTED_INVALID_SIGNATURE"
        return
    raise AssertionError(f"{name} unexpectedly verified")


def main() -> None:
    if cryptography.__version__ != "50.0.0":
        raise AssertionError(f"expected cryptography 50.0.0, got {cryptography.__version__}")

    private_key = Ed25519PrivateKey.from_private_bytes(FIXTURE_PRIVATE_RAW)
    private_raw = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    if private_raw != FIXTURE_PRIVATE_RAW or len(private_raw) != 32 or len(public_raw) != 32:
        raise AssertionError("raw key serialization mismatch")

    reloaded_private = Ed25519PrivateKey.from_private_bytes(private_raw)
    reloaded_public = Ed25519PublicKey.from_public_bytes(public_raw)

    raw_claim = material_claim(
        object_kind="RAW_PAYLOAD",
        object_ref="m9-admission-payload:probe-upload-01:v1:raw",
        material=b"manual upload bytes\x00fixture",
    )
    native_claim = material_claim(
        object_kind="SOURCE_NATIVE_ID",
        object_ref="m9-admission-native-id:probe-upload-01:v1:0",
        material=b"source-native-id-123",
    )
    raw_signature = reloaded_private.sign(canonical(raw_claim))
    native_signature = reloaded_private.sign(canonical(native_claim))
    if len(raw_signature) != 64 or len(native_signature) != 64:
        raise AssertionError("unexpected Ed25519 signature length")

    observations: dict[str, str] = {}
    reloaded_public.verify(decoded(encoded(raw_signature)), canonical(raw_claim))
    observations["baseline_raw"] = "VERIFIED"
    reloaded_public.verify(decoded(encoded(native_signature)), canonical(native_claim))
    observations["baseline_native"] = "VERIFIED"

    mutated = copy.deepcopy(raw_claim)
    mutated["material_b64"] = base64.b64encode(b"manual upload bytes\x00mutated").decode("ascii")
    expect_invalid(observations, "material_mutation", reloaded_public, raw_signature, mutated)

    wrong_public = Ed25519PrivateKey.from_private_bytes(WRONG_PRIVATE_RAW).public_key()
    expect_invalid(observations, "wrong_key", wrong_public, raw_signature, raw_claim)

    mutated = copy.deepcopy(raw_claim)
    mutated["domain"] = "arcreel.m9.some-other-purpose.v1"
    expect_invalid(observations, "domain_mutation", reloaded_public, raw_signature, mutated)

    mutated = copy.deepcopy(raw_claim)
    mutated["object_ref"] = "m9-admission-payload:probe-upload-01:v1:other"
    expect_invalid(observations, "ref_mutation", reloaded_public, raw_signature, mutated)

    mutated = copy.deepcopy(raw_claim)
    mutated["scope"]["project"] = "other-project"
    expect_invalid(observations, "scope_mutation", reloaded_public, raw_signature, mutated)

    expect_invalid(observations, "cross_object_signature", reloaded_public, native_signature, raw_claim)

    output = {
        "cryptography_version": cryptography.__version__,
        "fixture": "synthetic-public-test-key-only",
        "private_raw_bytes": len(private_raw),
        "public_raw_bytes": len(public_raw),
        "signature_bytes": len(raw_signature),
        "public_key_base64url": encoded(public_raw),
        "raw_claim_sha256": "sha256:" + hashlib.sha256(canonical(raw_claim)).hexdigest(),
        "raw_signature_base64url": encoded(raw_signature),
        "native_claim_sha256": "sha256:" + hashlib.sha256(canonical(native_claim)).hexdigest(),
        "native_signature_base64url": encoded(native_signature),
        "observations": observations,
    }
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
```

```json
{
  "exit_code": 0,
  "scope": "DIRECT_PRIMITIVE_ONLY",
  "probe_sha256": "2ba15bdecc265d9a00137b1c31997e1adc7c2e1fce5375cb3b58c354946079b9",
  "result": {
    "cryptography_version": "50.0.0",
    "fixture": "synthetic-public-test-key-only",
    "native_claim_sha256": "sha256:1a562cdc760de75d1ea52a74472d1900c479323dcb37ea56e0755c6454dd6348",
    "native_signature_base64url": "xKa4VzpU9dqIwFuk_57jUVHo-AwGFDzH8Hk51LBnIXP4Jrmdtq-hxL1nrr75bTYjJTyLAkHcpkzXHWfkJffqCQ",
    "observations": {
      "baseline_native": "VERIFIED",
      "baseline_raw": "VERIFIED",
      "cross_object_signature": "REJECTED_INVALID_SIGNATURE",
      "domain_mutation": "REJECTED_INVALID_SIGNATURE",
      "material_mutation": "REJECTED_INVALID_SIGNATURE",
      "ref_mutation": "REJECTED_INVALID_SIGNATURE",
      "scope_mutation": "REJECTED_INVALID_SIGNATURE",
      "wrong_key": "REJECTED_INVALID_SIGNATURE"
    },
    "private_raw_bytes": 32,
    "public_key_base64url": "TLWr9q15-_WrvMr8wmnYXNJlHtS4hbWGnyQa7fCluik",
    "public_raw_bytes": 32,
    "raw_claim_sha256": "sha256:750912f3318fa0020c4f9d7fefbf279829e55403097f586de7b9927d7551a775",
    "raw_signature_base64url": "cjOae1C-8GYbR6040swrYtaTTQeDn5dYg5TWsNlfO1CV_0kdLnOLJqX5bnUgKdtpNuZacjlMfVDlhioR7wgOAQ",
    "signature_bytes": 64
  }
}
```
