# R2 V1 H6 Recovery Configuration Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the V1 backup configuration fingerprint exact, canonical and fail-closed without changing the current disposable backup interface.

**Architecture:** Add a separate pure contract module that validates a complete non-secret source/release/tool/root/service-policy record and hashes its validated canonical bytes. Reuse the existing bounded canonical fence-record parser and its writer-digest domain; do not introduce a DB, archive, custody or production adapter in this packet.

**Tech Stack:** Python 3.13, Pydantic 2, pytest, SHA-256, existing `r2.contracts` parser.

**Spec:** `docs/superpowers/specs/2026-09-25-r2-v1-h6-recovery-config-contract-design.md`

## Global Constraints

- V1 schema version is JSON integer `1`; bytes are canonical UTF-8 JSON at most 1,048,576 bytes.
- `backup_mechanism` is exactly `logical_pg_dump_v1`; physical/PITR needs a new reviewed profile/schema.
- Every field is required and unknown fields reject; IDs are logical, not paths/URLs/credentials.
- `writer_inventory_digest` uses the existing fence verifier's sorted `(kind, instance_id)` pair domain and `sha256:` prefix.
- The old unversioned `BackupSetManifest`, `BackupVerdict` and `create_backup_set` are unchanged.
- No fixture, digest or parser pass authorizes production capture or `RECOVERY_VERIFIED`.
- Changed tests require `scripts/audit_tests.py --check`; affected tests and static gates use the M7 venv with explicit test DB URL.

## Review Focus

1. A changed field outside the writer list must change the whole-record fingerprint; Task 1 tests the release-image mutation.
2. A caller must not smuggle DSN/password fields into config; Task 1 tests `database_url` and nested `password` extras.
3. A valid-looking but unsorted, duplicate or incomplete writer list must reject; Task 1 tests each.
4. A boolean/float/string schema version or `paid_routes_enabled=true` must reject; Task 1 tests each.
5. A matching self-declared writer digest with an unauthorized service identity must not count as independent attestation; Task 1 asserts parsing alone returns no approval/verdict and the spec limits its authority.

---

### Task 1: Canonical `RecoveryConfigV1` and fingerprint

**Files:**
- Create: `r2/contracts/recovery_config.py`
- Create: `tests/unit/r2/contracts/test_recovery_config.py`

**Interfaces:**
- Consumes `r2.contracts.backup_fence.parse_canonical_fence_record` and `FenceRecordInvalid`; this bounded, generic parser already rejects duplicate keys, non-finite values, oversized/deep/noncanonical JSON.
- Produces frozen `ToolIdentityV1`, `ServiceIdentityV1`, `RecoveryConfigV1`, safe `RecoveryConfigInvalid`, and `parse_recovery_config_v1(raw: bytes) -> tuple[RecoveryConfigV1, str]` where the second result is the full-record `sha256:` digest.
- Does not export an `approved` flag, a restore authorization, or any DB/file writer.

- [ ] **Step 1: Write the failing tests.** Build one literal valid mapping with one `postgres` service and one writer of each required kind. Use the hand-computed writer digest `sha256:b57fb25e3a2aa2b588f820b8e34a81366cfeda8c58eb4d2bcfad6dac282927e4` for `app-1`, `gc-1`, `scan-1`, `worker-1`. The first test expects successful parsing and `sha256:` of the exact raw bytes; a second changes only `release_image_digest` and expects a changed fingerprint. Parametrize absence/extra `database_url`, nested `password`, noncanonical JSON, duplicate keys, schema `2`/`true`/`1.0`/`"1"`, wrong backup mechanism, paid routes `true`, wrong writer digest, duplicate/unsorted service or instance, missing writer kind, root alias, malformed digest, and URL/path logical ID; all raise `RecoveryConfigInvalid` without echoing input.

```python
def test_release_identity_changes_full_configuration_fingerprint() -> None:
    first = valid_mapping()
    second = deepcopy(first)
    second["release_image_digest"] = "sha256:" + "e" * 64
    _, first_digest = parse_recovery_config_v1(canonical_json_bytes(first))
    _, second_digest = parse_recovery_config_v1(canonical_json_bytes(second))
    assert first_digest != second_digest
```

- [ ] **Step 2: Run RED.** `DATABASE_URL=sqlite+aiosqlite:///:memory: /home/anhtuan/content-production-os-m7/.venv/bin/python -m pytest tests/unit/r2/contracts/test_recovery_config.py -q --timeout=10 --timeout-method=thread`; expected failure because the module/interface does not exist, never zero tests.
- [ ] **Step 3: Implement the minimal contract.** Use `BaseModel` with `ConfigDict(frozen=True, extra="forbid")`, exact string/digest/version validators, tuple shape checks and a model-level writer-inventory check. Parse with the existing canonical parser and translate only its safe category to `RecoveryConfigInvalid`; compute `"sha256:" + hashlib.sha256(raw).hexdigest()` only after model validation. Recompute the writer digest from sorted `(kind, instance_id)` pairs using `r2.contracts.fingerprints.canonical_json_bytes`, not a new serialization rule.

```python
def parse_recovery_config_v1(raw: bytes) -> tuple[RecoveryConfigV1, str]:
    try:
        record, _ = parse_canonical_fence_record(raw, RecoveryConfigV1)
    except FenceRecordInvalid as exc:
        raise RecoveryConfigInvalid(exc.category) from None
    return record, "sha256:" + hashlib.sha256(raw).hexdigest()
```

- [ ] **Step 4: Run GREEN and neighboring gates.** Run the Step-2 command, `tests/unit/r2/contracts/test_backup_fence.py`, `tests/unit/r2/host_hardening/test_fence_evidence.py`, then `scripts/audit_tests.py --check`, Ruff check/format-check of the two new files, basedpyright with `--venvpath /home/anhtuan/content-production-os-m7 --warnings`, and `git diff --check`. An existing full backend xdist worker crash is reported, never called green.
- [ ] **Step 5: Inspect and commit exactly this packet.** Review the whole diff for secret/absolute-path leakage and backward-compatibility impact. Stage the spec, plan, module and test only; run `git diff --cached --check`; commit `feat(r2): define canonical H6 recovery configuration`.

## Exit and next packet

This packet ends with a typed fingerprint only. A separate V1 inner-manifest/inventory/verdict packet must bind it; migration and capture orchestration then consume those contracts. Production custody requires its independently approved crypto/repository/key/signing profile and a clean-target drill; this packet claims neither.
