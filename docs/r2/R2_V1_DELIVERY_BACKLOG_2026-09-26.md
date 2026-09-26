# R2 V1 delivery backlog — real products before V2

Date: 2026-09-26
Baseline: `feat/r2-m7e-v1-lineage` at `057706e43ebbd83abfc4b9d6b19d6feac23599fc`
Authority: [accepted V1 release strategy](R2_V1_PRODUCTION_RELEASE_STRATEGY.md)

This is a sequencing/checkpoint map, not H6 design approval, a production
operation authorization, or evidence that historical green results apply to a
later HEAD. The objective is the narrow single-operator V1: one factual and
one drama video, both playable and reopenable, with Human Gates A–D, controlled
export/manual publication, and a verified database-plus-media recovery path.
V2 begins only from the released V1 tag and verified recovery baseline.

## Current position

| Surface | Current evidence | Remaining acceptance |
| --- | --- | --- |
| V1 direction | ADR-0089 and the release strategy are accepted. | No new product-scope decision needed. |
| Real media | `R2_M3_REAL_MEDIA_CLOSURE.json` records both corpus products rendered with real content, accepted by human override. | Re-run both through the complete operator workflow on the exact V1 candidate; prior fixture evidence is not release acceptance. |
| Human Gates A–D | `R2_P1_GATE_SURFACE.json` records backend/routes and partial UI; its status note says pending human review. | Review exact lineage; prove all four human decisions bind the selected products and revisions. B/C operator UI is still API-only in that evidence. |
| Recovery and telemetry | H6 design remains draft; H7 has open findings; `R2_M7_E1_INTEGRATION_STOP_2026-09-25.json` records M7-D and E1 as CHANGES_REQUIRED. | Close H6/H7, clean-target drill and independent exact-HEAD M7-D review. |
| V1 release | No V1 release acceptance is claimed by this document. | Finish E1/E2/E3, operator runbook, exact-HEAD gates and annotated clean tag. |

## Ordered work packets

| ID | Work and purpose | Exit evidence / stop condition |
| --- | --- | --- |
| V1-01 (now) | Research project liveness and deletion semantics so H6 can distinguish a live DB-only project from historical rows left after deletion. | Source-backed row-type/liveness table; filesystem-only, intentionally deleted and corrupt DB-only cases; no manifest schema freeze before review. |
| V1-02 | Close H6 file-reference inventory, including project metadata, formal files, candidate media, DB-bound global assets, absent manifests/roots, duplicate paths and orphans. Purpose: restored DB must not point to uncaptured bytes. | Complete authority/role/path map with missing/out-of-root/drift fixtures and an approved policy for each ambiguous class. |
| V1-03 | Approve the V1 manifest/inventory/verdict field map, then implement pure contracts, deployment-scoped persistence, capture, restore verifier and fault tests in separately reviewed disposable packets. Purpose: make backup evidence complete and crash-safe without changing the disposable API in place. | Canonical schema and digest samples; visible PREPARING refs before copy; clean-target DB/file/media/master closure; typed failures and exact test evidence. Fixture custody does not authorize production. |
| V1-04 | Approve custody policy and bind production repository, authenticated encryption/keys, signatures, evidence store, retention and operator procedures. Purpose: archive confidentiality, authenticity and recoverability. | Approved policy/profile, real encrypted archive adapter and custody receipt, audited failure/disposition tests and updated backup/restore runbook. Without this, no production `RECOVERY_VERIFIED`. |
| V1-05 | Close H7 request-to-usage/master telemetry and redaction, then re-review M7-D on one clean HEAD. Purpose: make restored production behavior diagnosable without leaking secrets. | Correlation and canary evidence, clean-target no-provider Golden review/export, measured RPO/RTO, full affected gates, independent M7-D acceptance. |
| V1-06 | Remediate existing E1 compatibility/qualification findings, enumerate all paid outbound routes and disable or exactly qualify each release route. Purpose: prevent unsupported provider calls and false compatibility claims. | Executable provenance/mapping/evidence checks, correct test tiers, exact-version route inventory; E1 independently accepted. Paid canaries/credentials require separate authorization. |
| V1-07 | Run E2 Golden A/B and browser/operator workflow from a restore-derived disposable target; repair only observed product gaps. Purpose: demonstrate the two selected products from source through A–D, restart, reopen, preview and export. | Two real playable deliverables, exact gate receipts and export digests, no-provider or approved qualified-route evidence, browser/cross-scope and failure/retry tests. |
| V1-08 | Run E3/release gates and prepare an annotated V1 tag from a clean candidate. Purpose: create a reproducible single-operator release, not merely a passing test branch. | Full affected/backend/frontend/static/migration/browser gates on exact SHA, reviewed runbooks and deferred-capability disclosure, `PRODUCTION_CANDIDATE` dossier, separate Human/operations approval before live actions, clean tag only after V1 release gate. |
| V2-01 (later) | Preserve V1 maintenance line and restore its tagged DB/media baseline into isolated V2 staging. Purpose: start V2 from a recoverable real product rather than a copied worktree. | V1 tag, verified recovery baseline, one stable operator release cycle and evidence-backed V2 gap; then decide portfolio identity/resource/pause semantics before code. |

## Execution rule

Work one acceptance packet at a time. Research and reuse existing Host contracts
before adding a schema or authority. A design/research note, self-review,
historical human override or fixture-only test does not advance a packet's
acceptance state. If an exact field map or operator policy is unresolved,
record the competing options and stop that dependent implementation while
continuing independent in-scope research. Production migration, provider
spend, credential use, live restore, deployment and publication require their
separate operational approvals.
