# M9-B Recovery V2 admission-side closure handoff to E

Status: implementation evidence for isolated, synthetic admission-side cleanup.
E global closure acceptance is pending. This document neither creates an E job
nor authorizes production, provider access, activation, push, or merge.

Authority: `R2_M9_B_RECOVERY_V2_RELEASE.json`, the approved
`2026-10-20-r2-m9b-manual-recovery-v2-design.md` and its implementation plan.
The immutable original request, descriptor, clocks and issuer verification key
remain authoritative. A current upload mapping or an empty successor store is
not original custody evidence. V1 contracts, signatures and closure serialization
retain their existing meaning.

## Logical closure and stages

The existing `m9_manual_closure_intents` table carries a distinct private record
`m9.manual-recovery-closure.v1`. Its original fence binds the sorted dependency
inventory, original SQL metadata and audited read permits. The record includes
both the independently signed private spending proof and exact public deletion
receipt before completion. It does not invent an external E identity.

| Recovery intent version | Phase | Required evidence / permitted next operation |
| --- | --- | --- |
| 1 | CLEANUP_PENDING | SQL admission/upload fences committed; fence original public publication keys |
| 2 | CLEANUP_PENDING | Original audited reads released or expired; private original custody may be spent and physically erased |
| 3 | CLEANUP_PENDING | SQL independently verifies original private proof, complete header inventory and drained-before-erased chronology; authorize exact public deletion |
| 4 | ERASED | Exact public deletion receipt and SQL tombstones committed together |

These versions belong to the new recovery record. The old V1 closure/deletion
record retains its three-stage protocol. Admission-envelope versions advance
from each member's original version by one for CLEANUP_PENDING and by two for
ERASED; the first admission time and all original clocks remain unchanged.

## Inventory and boundaries

| Authority / object | Identity and retained evidence | Fence / deletion behavior |
| --- | --- | --- |
| `m9_acquisition_attempts` and command receipt | Original scoped command, request digest, attempt/provider/quota history and exact receipt | Cleanup does not redispatch, reinterpret delivery, refund quota, or rewrite a terminal result |
| `m9_manual_admissions` | Exact original request, refs, first admitted time, deadlines and dispatch claim | SQL erasure fence precedes physical deletion; new read permits and operational finalization refuse under the fence |
| `m9_manual_publication_intents` | Original publication key and independent copy of admission metadata | RESERVED may contain an actual unattached publication; cleanup never fabricates READY or an admission clock |
| `m9_manual_upload_leases` | Original opaque upload/version, stable claim and scoped member | ACTIVE/1 -> CLOSING/2 -> SPENT/3 with the same closure; live shared peers prevent cleanup |
| `m9_manual_read_leases` | Original scoped permit, issued/expiry times and audited release | Freeze complete inventory and drain it before private or public erasure; FK targets the attempt, so lost admission rows cannot imply no readers |
| `m9_manual_closure_intents` | Frozen dependency inventory, original presence flags, four-stage intent, pinned public key, private proof, public receipt | Independently audited state event for each version; missing/contradictory fence or state evidence refuses |
| `m9_events` | `MANUAL_RECOVERY_ADMISSION_FENCED`, `MANUAL_RECOVERY_CLOSURE_STATE`, read/attempt/snapshot audits | Recompute full typed authority and digests; digest columns alone do not establish integrity |
| Material-loss audit | `MANUAL_MATERIAL_UNAVAILABLE`, original immutable admission fields and observed envelope version | Actual material/seal verification failure blocks later reads and operational use even if original files reappear; metadata replay and cleanup remain possible |
| Private issuer original/comparison/material seals and temporary files | Original claim authority plus signed content-free header inventory | Durable SPENT before erasure; original/comparison/material seals erased without content reads; cached spending receipt follows verified absence |
| Private custody/index/spending records and key | Original scope, claim, no-issuance control and exact cached receipt | Positive complete inventory required; lost authority never means fresh, never generates a successor key or claim |
| Public headers | Original signed publication metadata and all exact paired refs | Public-key verification only; original private header can recover a lost public header for deletion, without material/seal reads |
| Public payloads, integrity objects and material attestations | Exact independently authenticated payload/integrity/attestation refs | Durable key/ref blocks before no-follow, regular-file, single-link unlink/fsync; verify actual absence before returning or replaying receipt |
| Public recovery deletion job / blocks | `m9.manual-recovery-deletion.v1`, exact proof/requests/version-3 intent and cached receipt | Same durable job and receipt after interruption; reappeared data refuses cached completion |
| Snapshots / checkpoints / observations | Existing immutable metadata and original provenance / receipts | Cleanup does not turn retained metadata into operational permission; E must classify retained fields against its actual retention policy |

Lock order is command -> policy/adaptation -> capability/cohort/query -> original
opaque upload -> original claim -> object refs -> attempt rows. Additional refs
learned only from signed private inventory participate in sorted object guards
before row locks; SQL dependency discovery runs again before public deletion.
A newly discovered external dependency refuses the current closure rather than
silently deleting its shared public object. Such a refused closure stays pending;
this packet does not claim an E-wide resolution of that dependency.

A lost admission row is recoverable only from its independently retained intent;
a lost intent is recoverable only from its retained admission. Cleanup validates
original metadata, leases and terminal checkpoint/snapshot/receipt history, then
creates only the missing CLEANUP_PENDING row under complete guards. Normal
read/acquisition paths remain strict. Loss of both original SQL anchors remains
unresolved before custodian or store I/O. This implementation does not promote
historical snapshots or current paths into replacement admission authority.

## Reproducible fixture evidence

The source-bound qualification report and logs live in the ignored execution
workspace `.superpowers/sdd/2026-10-20-r2-m9b-manual-recovery-v2/`; the committed
source seal identifies the exact blobs. Focused execution evidence:

| Scenario / exact fixture | Observed result |
| --- | --- |
| `test_v2_cleanup_commits_only_after_real_private_and_public_erasure` | READY, published-unattached and never-published shapes; actual private/public file absence, same command receipt, no fake claim or admission clock |
| `test_v2_cleanup_drains_admitted_reads_before_any_private_erasure` | Durable live read prevents private erasure; same closure completes after release |
| `test_v2_cleanup_retry_reconciles_physical_erasure_with_sql_rollback` | 11 commit/ACK/interruption boundaries; stable retained authority and receipts, pending until SQL completion, no ports after ERASED replay |
| `test_v2_cleanup_uses_retained_sql_anchor_without_recreating_ready` | Four one-anchor loss cases across RUNNING/SUCCEEDED recover; both-anchor loss refuses before physical deletion |
| `test_v2_material_loss_is_audited_and_blocks_reuse_after_files_reappear` | Real payload/attestation loss, durable audit, restored-file refusal and subsequent cleanup |
| `test_v2_cleanup_preserves_live_shared_upload_then_erases_expired_dependency_group` | Unclaimed peer and admitted peer/read protected while live; all expired members share the same completed closure |
| `test_v2_cleanup_rechecks_newly_discovered_public_refs_before_deleting_a_shared_object` | Synthetic SQL alias to real original public objects refuses; native `pg_blocking_pids` proves the expanded object guard blocks authorization before dependency recheck |
| `test_recovery_deletion_uses_original_private_inventory_without_content_reads` | Original header, lost header, positive never-issued and seven abrupt deletion boundaries; child reaped, fresh PID, exact receipt replay, content opens denied |
| `test_cleanup_cannot_prove_absence_in_an_empty_successor_publication_root` | Original config/root/key binding refuses before custodian contact |

The private custodian, original repository and original evidence-store suites
supply additional inventory/tamper/lease/interleaving checks. Consult exact logs,
not this table, for collection counts and source bindings. Earlier failed or
interrupted reports are retained and are not successful execution evidence.

## Remaining acceptance work

T8 must qualify the full parent-survives kill/reap/fresh-interpreter inventory,
including all changed boundaries and actual separate-UID runtime custody. The
abrupt child `os._exit` checks above are useful deterministic recovery evidence;
they do not replace that parent-kill gate. T9 API/read/i18n and T10 current full
backend/evidence/final independent review remain separate gates.

E must qualify its actual traversal, global guards, complete dependency closure,
shared references, deadlines, permitted tombstone fields and external deletion
receipts. No source-only B result or focused test constitutes E global closure
acceptance or production activation.
