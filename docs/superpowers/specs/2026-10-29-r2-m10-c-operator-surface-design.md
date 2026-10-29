# R2 M10-C — Quality operator surface (design r2)

Status: design r2 for delta review, 2026-10-29 (r1 REWORK: `docs/r2/evidence/m10-c-reviews/design-codex-review.json`).
Branch `design/r2-m10-c-operator-surface` from the accepted M10 record `5256a9d72`.

## 1. Problem (facts)

- M10-A (profiles, probes, narrative observations, run closure, dispositions) is accepted as services only; the A
  designs exclude routers (A5 §1, A6 §1, A4 route qualification limits). The M10 plan's file map lists
  `server/routers/quality.py`, never built.
- M10-B's Packaging page needs a sealed run, a published V2 profile and a PASS disposition; on a deployed host no
  operator can create them. The B7 pilots used scripts calling the services.
- Services verify a client-supplied `AssessedSubject` (`server/services/quality_runs.py` `_subject_authoritative`);
  production builds none. Real V2 manifests carry R2 metadata with `approved_master` and `direct_dependencies`.
- The production probe catalog is empty (`DEFAULT_PROBE_CATALOG`); A4 requires code-embedded, source-reviewed,
  same-fixture qualified catalogs.

## 2. Scope and stop conditions

Wiring over the accepted A3–A6 and B services, unchanged: a subject resolver, an embedded host probe catalog, a
prepare/submit router, one UI page, Packaging prefill. No new contract model, authority, adapter, migration or
evidence custody. Any need to change an accepted service's semantics, add DB persistence, or act on the production
host without the sponsor stops the packet.

## 3. Decisions

**D1 Subject resolver** (`server/services/quality_subjects.py`), the accepted `MasterBindingV1` closure exactly:
start from the root artifact key; read its R2 metadata from the manifest snapshot; follow only
`direct_dependencies` whose `ref` starts with `master:`; the child key is
`episode_video_key(parent_episode, ref.removeprefix("master:"))` with the parent episode from
`decode_episode_video_key(parent)`, the child metadata must be a `ShotSpec`, and the dependency's `version` and
`fingerprint` must equal the child head's `selected_candidate_id@host_version_ref` and content digest — the exact
rules of `MasterBindingV1.coherent` (`r2/contracts/quality.py:236-293`); a mismatch, unknown key or cycle refuses
before any service call. Other refs (`claim:` …) stay in the metadata body and create no edge. Each closure member's head comes from `DatabaseMasterResolver.get_exact`
(absent, diverged, or metadata without `approved_master` refuses `M10_SUBJECT_STALE`). Heads, snapshots and edges
are built as the contract normalizes them (validators sort them; the resolver does not re-sort by hand); digests use
the existing domains (`m10.master-binding.v1`, artifact digest from the root content digest, `content_basis_digest`
from the root metadata exactly as `r2/quality/digests.py` defines it); caption/audio digests are `None` (no caption or
audio slot in the template). The service still runs `_subject_authoritative` and master locks. Tests compare the
resolver's subject byte-for-byte with the accepted fixture subject (`tests/unit/r2/quality/test_quality_digests.py`
`valid_subject`) for the fixture manifest.

**D2 Embedded host probe catalog** (`r2/quality/host_catalog.py`). Source-reviewed `ProbeConfig` bodies for
`CONTAINER_STREAM` and `DECODE` only, with the A4 qualified bodies (parameters, parser version/digest, applicability
`REQUIRED`, threshold `EVIDENCE_COMPLETE`) and the tool identities of the qualified host (`/usr/bin/ffmpeg` and
`/usr/bin/ffprobe`, ffmpeg 8.0.1; executable digest and `-version` build digest pinned as literals). Qualification:
the A4 recipe suite runs these exact bodies against the recipe fixtures and asserts the pinned digests equal the
host's tools; the probe route qualification is requalified with this catalog (an appended entry, as `0299b0a11`).
The app enables the catalog only when `ARCREEL_QUALITY_PROBE_CATALOG=host-v1`; otherwise probe *new* submissions
answer 503 `m10_quality_unavailable` but receipts replay (replay never consults the catalog — A4 receipt-first).
A different host needs a new reviewed catalog body; it is never generated at runtime.

**D3 Profile template.** Requirements are one requirement per probe, so independence groups never collide:
`technical-container` (slot CONTAINER_STREAM), `technical-decode` (slot DECODE), `review` (NARRATIVE/HUMAN), each
`ALL` with one slot; freshness 7 days. Platform constraints are the operator's (dimensions, duration window,
locales, title/description bounds, banned phrases, asset roles), with every packaging check rule declared. The
template is a complete V2 policy whose digest the server computes. A PG test drives template → publish → both probes
→ review → seal → PASS disposition through the unchanged closure rules.

**D4 Prepare/submit with server signatures** (stable retry, H4). Each mutation is two calls:
`POST …/<action>/prepare` builds the complete service request server-side — resolved subject, profile revision,
generated identities (`uuid7`) and times (`created_at`, `requested_expires_at`), computed digests — and returns it with
an HMAC-SHA256 seal over its canonical bytes, keyed by a key derived from `AUTH_TOKEN_SECRET` with the purpose
`m10-quality-prepare` and bound to `(user_id, actor_id, project_name, action)`. `POST …/<action>` accepts only that
exact sealed request (seal verified in constant time, actor re-checked). Retries after a lost response or a reload
resend the same sealed request, kept in the browser under its command id until a result is shown, so the service
replays its receipt; drift is the service's decision (replay of a committed command, or its typed refusal). The seal
proves the server built the request; every authority check stays in the services. Rejected: rebuilding requests on
retry (generated fields change, H4); a server-side draft table (new persistence).

**D5 Human gates and custody** (H5). Publication and disposition keep the accepted custodians, which take a fresh
startup proof per issuance (`InteractiveProfilePublicationCustodian.for_request`, `DispositionCustodian.for_request`)
— a freshness property of A3/A6, not changed. The attestor refuses while busy; the route maps that to a retryable
503 `m10_quality_busy`, and the UI retries once after a short delay. Probe, review and seal take the app's
startup-verified reader (`app.state.governance_grants`), as packaging does. Custody owner is host config (root by
default). Every mutation requires `InteractiveUser`; the embedded-agent token is refused.

**D6 Revisions and CAS** (M1). `GET /profiles` lists profile ids with their current revision; `GET
/profiles/{id}/revisions` lists immutable revisions. Publishing a new revision of an existing profile prepares with
`expected_profile_revision` = the revision the operator edited and the same cohort/surface; a stale head refuses.
Probe, review and seal prepare against an explicit `(profile_id, revision)`. Disposition prepares with the run id, the
disposition head version read by `GET /runs/{id}` and `requested_expires_at` chosen at prepare (default 7 days,
bounded by the A6 policy).

**D7 Human review evidence** (M2). Rubric: one code-embedded rubric `m10.narrative-rubric.v1` (criteria: story
coherence, legibility of on-screen text, audio presence, visible defects) whose digest is `rubric_digest`.
Segment closure: the whole master, `compute_digest("m10.review-segments.v1", {"subject_digest", "segments":
[{"start": "0", "end": "END"}]})`. Notes: written content-addressed under the project
(`quality/reviews/<sha256>.md`, regular file, no-follow), `reviewer_evidence_digest` = notes digest, `evidence_refs`
= `["project:quality/reviews/<sha256>.md"]`, `evidence_digest` = digest of the refs; the file is a reference, not
authority (the observation's digests are). Findings come from the operator's structured rows (rule id, severity,
locator) with server-generated finding ids.

**D8 Reads and states** (M3). `GET /masters`; `GET /probes?profile_id&revision&root` (technical observations plus the
M7 attempt state of each probe command: PLANNED, ACCEPTED, FAILED_BEFORE_ACCEPTANCE, unknown → "needs a new
command"); `GET /reviews?…`; `GET /runs?root` (every run of the root across subjects and profiles, with validity and
readiness; stale/superseded runs stay listed). Reads require an authenticated user; the quality routes answer 503
when authentication is disabled. Errors are sanitized through the packaging error map; i18n en/vi/zh.

**D9 UI** (`frontend/src/features/quality/`, route `quality`, sidebar before Packaging): master → profile (template,
edit, publish/revise) → probes (two) → review (rubric, findings, notes) → seal → disposition, with pending sealed
requests resumed from browser storage, then "Package this run" opening Packaging with `run`, `digest`, `artifact`,
`cohort`, `surface` prefilled.

## 4. Verification

Resolver unit tests (closure, non-master refs, unknown ref, missing approval, diverged head) and byte equality with
the fixture subject; PG route tests with real custodians and the real confined probe runtime for the full chain, the
Packaging flow on that run, agent token refused, seal tampering refused, retry after a lost response replaying,
drift after prepare refused by the service; catalog qualification (A4 suite + requalification); UI tests, `pnpm
check`, live Chrome axe; local Chrome acceptance with no scripts; then the sponsor's activated-host qualification and
deploy. Carry `R2_M10_ACCEPTANCE.json` C1–C6 (root-owned activated custody, LOCAL_REGULAR_FILE_IO, trusted root,
single operator, release/production exclusions).
