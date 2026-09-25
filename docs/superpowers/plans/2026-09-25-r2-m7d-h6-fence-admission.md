# R2 M7-D H6 Fence-Evidence Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a fail-closed, independently testable V1 capture-fence preflight for the later capture caller to run before writing a backup row or archive file.

**Architecture:** Add immutable wire contracts in `r2/contracts/backup_fence.py` and a pure verifier in `r2/host_hardening/fence_evidence.py`. The verifier receives an independently supplied expectation, signature verifier and bounded immutable-evidence reader; it never fetches from an arbitrary caller path, signs data, changes backup state, or claims to stop processes. There is no production signature/evidence-store adapter in this packet, and the existing legacy disposable `create_backup_set` remains unchanged. A later H6 capture packet must call this preflight before registry admission, PREPARING insert or file write.

**Tech Stack:** Python 3.13, Pydantic 2, existing `r2.contracts.fingerprints.canonical_json_bytes` inside contracts and `lib.content_digest` in the host verifier, pytest. No new dependency or infrastructure.

**Spec:** `docs/superpowers/specs/2026-09-25-r2-v1-m7d-recovery-closure-design.md` §4.1 and §5.1.

## Global Constraints

- Schema version is integer `1`; unknown versions, duplicate JSON keys, non-finite numbers and noncanonical bytes reject.
- The signer algorithm is Ed25519. This packet defines a verifier port but does not install a production key or trust anchor. A fixture verifier is test-only and cannot authorize production custody.
- `BACKUP_FENCE_EVIDENCE_INVALID` is the sole sanitized outward failure code; diagnostics contain field categories, never paths, command output, DSNs, raw evidence or signatures.
- The independent expectation supplies exact set/deployment/release/root IDs, approved writer inventory and signing-key allowlist; the submitted record cannot approve itself.
- Every referenced evidence blob is fetched by store/object/version with an explicit byte bound, then checked for nonempty bytes, exact size and SHA-256. The production reader's no-follow and immutable-store guarantees are a later adapter gate.
- No backup/restore, DB migration, repository adapter, production signing key, provider call or `RECOVERY_VERIFIED` claim is part of this packet.
- Test selection follows `CONTRIBUTING.md:71-79`; a changed test file also requires `scripts/audit_tests.py --check`.

## Review Focus

1. A syntactically valid signed record with a missing or altered status blob must reject; Task 2 pins both cases.
2. A complete-looking start record that omits one approved writer, reports a DB writer, or admits a root alias must reject; Task 2 pins all three.
3. Duplicate keys, NaN, unknown schema and different but equivalent JSON whitespace must reject before a verifier/reader call; Task 1 pins these.
4. A closure from another set or after fence expiry must reject even with valid test signature/blobs; Task 3 pins both.
5. A signer key supplied only by the record, an invalid detached signature, or an oversized blob must reject without leaking evidence bytes; Tasks 2–3 pin these.

---

### Task 1: Canonical V1 wire contracts

**Files:**
- Create: `r2/contracts/backup_fence.py`
- Create: `tests/unit/r2/contracts/test_backup_fence.py`

**Interfaces:**
- Produces `EvidenceBlobRefV1`, `ServiceStopEvidenceV1`, `PostgresWriterCheckV1`, `RootMountCheckV1`, `CaptureFenceStartV1`, `CaptureFenceClosureV1`, `FenceRecordInvalid`, and `parse_canonical_fence_record(raw: bytes, model: type[T]) -> tuple[T, dict[str, object]]`.
- `CaptureFenceStartV1` fields: `schema_version=1`, set/deployment/release Git/image IDs, logical DB/file-root IDs, `writer_inventory_digest`, custodian ID/role, three aware UTC start/quiescence/expiry times, service items, DB/root checks, signer key ID and detached signature.
- `CaptureFenceClosureV1` repeats exact identities and checks and adds `capture_checks_completed_at`/`fenced_capture_ended_at`.
- Evidence references carry protected store ID, object key, immutable version, positive byte size and lowercase `sha256:` digest. Each service item carries service kind (`app|worker|recovery_scanner|gc_cleanup`), instance ID, `STOPPED|DRAINED`, observation time, `SERVICE_MANAGER_STATUS|OPERATOR_COMMAND_TRANSCRIPT`, and one reference. DB check carries DB/monitor identities, zero active writer session/transaction counts, observation time and reference; root check carries the exact logical root IDs and mount identities, true no-alias/no-symlink observations, time and reference.

- [ ] **Step 1: Write failing contract tests.** In `test_backup_fence.py`, build a minimal valid start mapping with one `app`, `worker`, `recovery_scanner`, and `gc_cleanup` item; assert parsing returns schema `1` and an unsigned mapping. Parametrize `raw.replace(b'"schema_version":1', b'"schema_version":2')`, `b'{"a":1,"a":2}'`, `b'{"a":NaN}'`, and a whitespace-reformatted valid record; each must raise `FenceRecordInvalid`. Assert a zero-size evidence reference and naive timestamp reject. Use `canonical_json_bytes(mapping, allow_nan=False)` for the valid fixture.

```python
def test_duplicate_keys_are_not_signature_equivalent() -> None:
    raw = b'{"schema_version":1,"schema_version":1}'
    with pytest.raises(FenceRecordInvalid):
        parse_canonical_fence_record(raw, CaptureFenceStartV1)
```

- [ ] **Step 2: Run the selected test to see RED.** `DATABASE_URL=sqlite+aiosqlite:///:memory: /home/anhtuan/content-production-os-m7/.venv/bin/python -m pytest tests/unit/r2/contracts/test_backup_fence.py -q`; expected import/contract failures, not zero collected tests.
- [ ] **Step 3: Implement immutable models and parser.** Use `ConfigDict(frozen=True, extra="forbid")`; `Literal[1]`, `AwareDatetime`, `NonEmptyStr`, `StrictInt` for counts, `Field(strict=True, ge=1)` for byte size, and a lowercase digest pattern. Strict mode on the whole model would reject valid JSON timestamp strings; keep strictness on fields where coercion is unsafe. Decode UTF-8 strictly; call `json.loads(..., object_pairs_hook=reject_duplicate_pairs, parse_constant=reject_nonfinite)`, require a top-level object, compare its original bytes with the existing contract-layer `canonical_json_bytes(ensure_json_value(decoded))`, then call `model.model_validate(decoded)`. Return the validated model and original decoded dict so the signature payload can exclude only `signature` without reformatting timestamps. Map decoding/validation failures to `FenceRecordInvalid` without embedding raw values. Contract modules must not import `lib` (the architecture-boundary test covers this).

```python
def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FenceRecordInvalid("duplicate_key")
        result[key] = value
    return result

def reject_nonfinite(value: str) -> None:
    raise FenceRecordInvalid("nonfinite_number")
```

- [ ] **Step 4: Run GREEN plus adjacent contract tests.** Use the Step-2 command plus `tests/unit/r2/contracts/test_host_hardening.py`; expect all selected tests to pass.
- [ ] **Step 5: Commit only the two task files.** `git add -- r2/contracts/backup_fence.py tests/unit/r2/contracts/test_backup_fence.py`; `git diff --cached --check`; commit `feat(r2): define canonical H6 fence evidence contracts`.

### Task 2: Independent start-evidence preflight

**Files:**
- Create: `r2/host_hardening/fence_evidence.py`
- Create: `tests/unit/r2/host_hardening/test_fence_evidence.py`

**Interfaces:**
- Consumes Task-1 contracts/parser.
- Produces frozen `FenceExpectationV1` with exact `backup_set_id`, `source_deployment_id`, `release_git_sha`, `release_image_digest`, `db_root_id`, `file_root_ids`, `approved_writers: tuple[tuple[ServiceKind, str], ...]`, `allowed_signer_ids`, `allowed_evidence_store_ids`, `custodian_id`, `custodian_role`, and UTC `evaluated_at`. It also produces `EvidenceReader` with `read_exact(ref: EvidenceBlobRefV1, *, max_bytes: int) -> bytes`, `SignatureVerifier` with `verify_ed25519(key_id: str, payload: bytes, signature: str) -> bool`, and `verify_capture_fence_start(raw: bytes | None, *, expected: FenceExpectationV1, reader: EvidenceReader, signatures: SignatureVerifier) -> CaptureFenceStartV1`.
- Raises `FenceEvidenceError` with enum `FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID` and safe category only. Define `MAX_EVIDENCE_BYTES = 65_536` and `evidence_refs(record)` over every service, DB and root reference. The two protocols have no default implementation.

- [ ] **Step 1: Write RED tests for start admission.** Use test-only in-memory immutable blob reader and deterministic payload-bound signature verifier. Verify one valid signed start. Parametrize removal of any writer, positive DB writer count, root alias/symlink flag, wrong set/deployment/release/root, unknown signer, wrong signature, stale/expired window, missing blob, changed blob, wrong size, oversized declared blob, and a reader that returns more bytes than the bound. Every invalid case raises the typed code; absent/malformed start must fail before reader or signature calls. Assert exception string excludes blob contents and absolute paths.

```python
def test_absent_start_is_typed_and_has_no_side_effects() -> None:
    class UnusedPort:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"unexpected port access: {name}")

    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_start(None, expected=UnusedPort(), reader=UnusedPort(), signatures=UnusedPort())
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID
```

- [ ] **Step 2: Run RED.** `DATABASE_URL=sqlite+aiosqlite:///:memory: /home/anhtuan/content-production-os-m7/.venv/bin/python -m pytest tests/unit/r2/host_hardening/test_fence_evidence.py -q`; expect import/function failures.
- [ ] **Step 3: Implement the preflight.** Parse canonical record; compare each exact identity and the set of `(service_kind, instance_id)` pairs with the approved inventory, rejecting duplicates or missing entries and requiring all four service kinds. Recompute `writer_inventory_digest` over the sorted approved `(service_kind, instance_id)` pairs using `"sha256:" + canonical_json_digest(..., allow_nan=False)`; the repository's `prefixed_canonical_json_digest` uses the incompatible `sha256-v1:` prefix. Compare the recomputed digest with the record. Require `fence_started_at <= quiescence_confirmed_at <= expected.evaluated_at < fence_expires_at`, with UTC offsets and exact custodian role. Require zero active DB writer sessions/transactions, exact root IDs and true root no-alias/no-symlink flags. Check signer ID against the independently supplied allowlist and call `verify_ed25519` on `canonical_json_bytes({k:v for k,v in decoded.items() if k != "signature"}, allow_nan=False)`. For every service, DB and root reference, require its store ID on the independent allowlist and `1 <= byte_size <= MAX_EVIDENCE_BYTES`, call `read_exact(ref, max_bytes=byte_size)`, compare nonempty length and `sha256:` digest; map all port failures to the sanitized code. Do not mutate backup state or disk.

```python
unsigned = {key: value for key, value in decoded.items() if key != "signature"}
signed_bytes = canonical_json_bytes(unsigned, allow_nan=False)
if record.signer_key_id not in expected.allowed_signer_ids or not signatures.verify_ed25519(
    record.signer_key_id, signed_bytes, record.signature
):
    raise FenceEvidenceError(FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID, "signature")
for ref in evidence_refs(record):
    if not 1 <= ref.byte_size <= MAX_EVIDENCE_BYTES:
        raise FenceEvidenceError(FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID, "blob_size")
    blob = reader.read_exact(ref, max_bytes=ref.byte_size)
    if len(blob) != ref.byte_size or "sha256:" + hashlib.sha256(blob).hexdigest() != ref.sha256:
        raise FenceEvidenceError(FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID, "blob_integrity")
```

- [ ] **Step 4: Run GREEN, adjacent units and test audit.** Run the Step-2 command plus Task-1 tests and existing `test_backup.py`; then `/home/anhtuan/content-production-os-m7/.venv/bin/python scripts/audit_tests.py --check`. No required skip or zero-test result counts as green.
- [ ] **Step 5: Commit only the two task files.** `git add -- r2/host_hardening/fence_evidence.py tests/unit/r2/host_hardening/test_fence_evidence.py`; `git diff --cached --check`; commit `feat(r2): verify H6 capture fence before admission`.

### Task 3: Closure-window preflight and final review

**Files:**
- Modify: `r2/host_hardening/fence_evidence.py`
- Modify: `tests/unit/r2/host_hardening/test_fence_evidence.py`
- Modify: `docs/r2/runbooks/m7-backup-restore.md` only to point out that the new verifier is not wired to the legacy disposable backup command.

**Interfaces:**
- Consumes the verified start record and independent expectation from Task 2.
- Produces `verify_capture_fence_closure(raw, *, start, expected, reader, signatures) -> CaptureFenceClosureV1`; it accepts no caller-supplied `fenced_capture_ended_at` fallback.

- [ ] **Step 1: Write RED closure tests.** Reuse Task-2 test helpers `valid_start()`, `valid_expectation()`, `unused_reader()`, and `unused_signatures()`; define them in `test_fence_evidence.py` before the closure test. A signed closure with exact start identity, complete final writer/DB/root evidence and `quiescence_confirmed_at <= capture_checks_completed_at <= fenced_capture_ended_at <= fence_expires_at` passes. A missing/tampered final blob, different set/deployment/release/root/writer inventory, incomplete service inventory, end after expiry, end before check completion, or invalid signature fails with `BACKUP_FENCE_EVIDENCE_INVALID`. Assert all referenced final blobs were fetched by immutable version.

```python
def test_closure_missing_is_not_a_window_end() -> None:
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_closure(None, start=valid_start(), expected=valid_expectation(),
                                     reader=unused_reader(), signatures=unused_signatures())
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID
```

- [ ] **Step 2: Run RED.** Use the Task-2 pytest command with `-k closure`; expect failures, not zero collected tests.
- [ ] **Step 3: Implement closure verification by reusing Task-2 signature/blob helpers.** Require exact start/closure bindings; verify every final evidence item, then enforce the full window. Do not synthesize closure time or release an operator fence. Add one runbook sentence explicitly distinguishing the unwired new validator from the current `create_backup_set` API.

```python
if not (start.quiescence_confirmed_at <= closure.capture_checks_completed_at
        <= closure.fenced_capture_ended_at <= start.fence_expires_at):
    raise FenceEvidenceError(FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID, "capture_window")
```

- [ ] **Step 4: Run relevant gates.** Run both new unit files plus existing backup/contract/retention unit files with the explicit in-memory `DATABASE_URL`; run `scripts/audit_tests.py --check`, `ruff check`/`ruff format --check` on the changed Python files, `basedpyright --warnings`, and `git diff --check`. If DB integration remains unavailable, report that limitation instead of calling the packet H6 closure.
- [ ] **Step 5: Self-review and commit exact files.** Compare each §4.1 condition against a named test, inspect the whole diff for an implicit production adapter or secret leak, and commit only the three task files as `feat(r2): verify H6 fence closure evidence`.

## Packet exit and next dependency

This packet ends with a typed, pure verifier and adversarial tests, **not** a running H6 backup. The next independently reviewable packet must design/migrate deployment-scoped backup state and global retention with CAS and audited disposal; only after that may the capture orchestrator invoke this preflight before mutation. Production custody/repository/key/signature adapters, live restores and `RECOVERY_VERIFIED` remain blocked by the separate deployment-bound design gate.

## Review remediation before packet exit

The exact-HEAD reviews of `1768d0fe` and `21fbde8a` found that hash-valid but contradictory evidence blobs were accepted, and that closure accepted a publicly constructible, unverified start model. These are authority gaps, not optional production polish. The initial Task 3 commit is only a checkpoint; packet exit is blocked until both fixes have RED/GREEN tests and a fresh exact-HEAD review.

### Task 4: Require type-specific semantic evidence inspection

- Add a required `EvidenceSemantics` protocol with `validate_service(item, bytes)`, `validate_postgres(check, bytes)`, and `validate_roots(check, bytes)` methods returning exact `True` on success. It is supplied by the trusted composition root, never by evidence bytes or a backup caller. No permissive default and no production implementation are added in this packet.
- After signature, size and hash checks, call the matching method for *every* service, PostgreSQL and root blob. Missing method, exception or non-`True` result fails sanitized `BACKUP_FENCE_EVIDENCE_INVALID`. The service method receives the declared `SERVICE_MANAGER_STATUS`/`OPERATOR_COMMAND_TRANSCRIPT` type and must interpret it; an adapter that merely repeats record fields is not sufficient for H6 admission.
- Replace the test fixture's one arbitrary sentence with distinct, canonical type-specific observation blobs. RED tests submit hash-valid contradictory service/DB/root contents and assert the semantic port rejects them; GREEN tests pin exact method coverage on start and closure. The production adapter remains a separate acceptance gate and cannot be replaced by the test fixture.

### Task 5: Reverify the start at closure

- Change closure input from constructible `start: CaptureFenceStartV1` to `start_raw: bytes | None`. On every closure check, invoke the same start verifier with the independent expectation, signature verifier, reader and semantic inspector; then compare exact start/closure bindings and final evidence. A missing, malformed, bad-signature or altered/missing-blob start fails before closure is accepted.
- RED tests use a valid closure with invalid start signature and with tampered start blob; both reject. GREEN tests assert start and final references are each read by immutable version, and both signatures are checked. This repeats bounded I/O deliberately to remove an unenforced provenance assumption.

### Task 6: Bound untrusted record parsing

- Cap each raw canonical JSON record at `1_048_576` bytes before UTF-8 decode. Reject empty/oversized input and map `RecursionError` from deeply nested JSON or validation to `FenceRecordInvalid`; the public verifier maps that to `BACKUP_FENCE_EVIDENCE_INVALID` without retaining raw values or an exception context.
- RED tests submit a one-byte-over-limit record and a roughly 2,000-level nested JSON payload through parser and public start/closure APIs; assert typed/sanitized rejection before any signature or evidence reader call. A future production ingress may impose a tighter release-approved maximum.

### Task 7: Bind signer authority to the named custodian

- Keep the independently supplied release signer allowlist, and add a release-trust-root-sourced `custodian_signer_bindings: frozenset[tuple[key_id, custodian_id, role]]` to `FenceExpectationV1`. The record may neither invent this binding nor widen it. Require a nonempty binding set and membership of the exact `(record.signer_key_id, expected.custodian_id, expected.custodian_role)` tuple before signature verification; a valid Ed25519 signature from another allowlisted operator is not custody authority for the named custodian.
- RED tests use two cryptographically valid fixture keys, globally allowlist both, bind each to a different custodian, and re-sign start and closure as key B while claiming custodian A. Both must reject with `BACKUP_FENCE_EVIDENCE_INVALID`; an exact key A binding passes. The production trust-root adapter must supply these bindings from policy outside the evidence-submitting caller.

## Plan self-review (2026-09-25)

- Spec coverage: §4.1 start schema/canonical signature/blob preflight maps to Tasks 1–2; closure/window maps to Task 3. Registry, migration, inventory, archive custody and restore are explicitly excluded and remain dependent packets.
- No unresolved design placeholders are used as acceptance criteria. Port names, record fields, typed failure and maximum blob size are fixed above; the production adapters remain intentionally absent, not silently mocked.
- Type/interface check: Task 1 produces the models/parser consumed by Tasks 2–3; Task 2 produces the expectation, ports and typed error consumed by Task 3.
- Each of the five Review Focus failure classes has a named RED test in the owning task. The legacy API remains disposable-only until a later capture packet wires this verifier before mutation.
- Baseline: 33 existing backup/contract/retention unit tests passed using the installed M7 venv with explicit in-memory `DATABASE_URL`. The default `uv` run could not fetch an uncached dependency in the network-restricted sandbox; the default shared SQLite migration fixture timed out before tests ran. Neither result is a product-test pass for DB/integration work.
