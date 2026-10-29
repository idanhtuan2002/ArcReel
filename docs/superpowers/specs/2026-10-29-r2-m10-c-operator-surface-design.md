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

**D1 Subject resolver** (`server/services/quality_subjects.py`), the accepted `MasterBindingV1` closure exactly.
1. Read the manifest snapshot once (`ProjectArtifactManifestAdapter(project_root).snapshot_entries()`); metadata
   bodies are `R2ArtifactMetadata.model_validate(entry.r2).model_dump(mode="json")` (normalized, as
   `_subject_authoritative` compares them).
2. Heads: `DatabaseMasterResolver(authorities=MasterAuthorityRepository(session),
   legacy_projection=file_master_projection(project_root, session)).get_exact(...)` — the same construction as
   `_subject_authoritative`, so a diverged file projection refuses. Absent head, divergence, or metadata without
   `approved_master` whose `approval_record` equals the head's refuses `M10_SUBJECT_STALE`.
3. Closure: from the root, follow only `direct_dependencies` refs starting with `master:`; the child key is
   `episode_video_key(parent_episode, ref.removeprefix("master:"))` (`parent_episode` from
   `decode_episode_video_key(parent)`); the child metadata's `contract_ref.contract_type` must be `ShotSpec` and the
   dependency `version` must equal the child **metadata** `approved_master.selected_candidate_id + "@" +
   host_version_ref`, its `fingerprint` media the child head's content digest (`MasterBindingV1.coherent`,
   `r2/contracts/quality.py:236-293`). Unknown key, mismatch or cycle refuses before any service call. Other refs stay
   in the body and create no edge.
4. Build `ArtifactMetadataSnapshot(artifact_key, body, metadata_digest)` with `m10.artifact-metadata.v1`,
   then `MasterBindingV1` (its validators order heads/snapshots/edges), then `master_binding_digest` with
   `m10.master-binding.v1`, `artifact_ref = root.object_ref`, `artifact_digest = "sha256:" + media(root
   content_digest)`, `content_basis_digest` = `m10.content-basis.v1` over the root metadata
   `content_basis`, caption/audio `None` (no companion caption/audio evidence; it does not claim the media has no
   audio). Finish with `verify_caches`. Every digest uses an existing registered domain; none is added.

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

**D4 Prepare/submit with server seals** (stable retry, H4/N4).
- Actions (allowlist): `publish_profile`, `probe`, `review`, `seal_run`, `dispose`. Each prepare endpoint accepts
  only its action's intent fields (§D6–D8) and builds the complete typed service request itself; there is no
  generic "sign this" endpoint.
- Key: `HKDF-SHA256(ikm=AUTH_TOKEN_SECRET utf-8 bytes, salt=b"arcreel.m10-c", info=b"m10-quality-prepare.v1",
  length=32)`. Seal: `base64url(HMAC-SHA256(key, canonical_json_bytes({"schema": "m10-c.prepared.v1", "action":
  action, "user_id", "actor_id", "project_name", "request_type": <class name>, "request": request.model_dump(mode=
  "json")})))`. Submit re-derives the envelope from its own authenticated principal and the posted request, verifies
  with `hmac.compare_digest`, re-validates the typed request, and passes it to the service unchanged; it never
  rebuilds. Rotating `AUTH_TOKEN_SECRET` invalidates every pending seal (the UI drops them and re-prepares).
- Decision table: committed command resent → service replay of its receipt; first submission → service;
  root/master drift after prepare → the service's typed refusal (`M10_SUBJECT_STALE`); a newer profile revision after
  prepare → not refused by M10-C: the prepared request names its exact immutable revision and the services decide
  (an older revision may be consumed where the services allow it); probe ACCEPTED-but-unfinalized → resending the same
  sealed request finalizes without a new tool start (A4); probe SUBMIT_OUTCOME_UNKNOWN or FAILED_BEFORE_ACCEPTANCE →
  never retried under the same command; a new probe needs a deliberate new `execution_ref` chosen by the operator.
- Browser persistence: the full sealed request is saved under `(user, project, action, command_id)` before the first
  submit and removed after a result is shown. Losing browser storage or the prepare response loses that envelope;
  recovery is then a new prepare (a new command), bounded by the services' CAS and duplicate rules — a disclosed
  limit, since a server draft store would be new persistence.

**D5 Human gates and custody** (H5/N3/N5). Publication and disposition use the accepted public factories
(`InteractiveProfilePublicationCustodian.for_request`, `DispositionCustodian.for_request`) with the caller's bearer
token, the configured read/attestor directories and the configured custody uid/gid; each issuance takes its own fresh
startup proof (A3/A6, unchanged). Their refusals stay sanitized: `ProfilePublicationUnauthorizedError` /
`DispositionUnauthorizedError` → 403 with the existing i18n message, which tells the operator to retry; M10-C does not
claim to distinguish an attestor that was busy from other unavailability. Review and seal pass the startup-verified
reader (`app.state.governance_grants`) to the services that accept a reader factory; the probe service takes no
grant reader (it authenticates the interactive actor and checks profile/root authority itself). Every mutation
requires `InteractiveUser`; the embedded-agent token is refused.

**D6 Revisions, supersession and disposition** (M1). `GET /profiles` and `GET /profiles/{id}/revisions` list
immutable revisions with their digests. Publication intent: `{profile_id | null, expected_profile_revision, cohort_id,
product_surface, policy}` where the draft/policy field `supersession_effect` (`r2/contracts/quality.py:409,660`) is the operator's explicit choice between
`HISTORICAL_ONLY` and `REEVALUATE_CURRENT`, shown before confirmation (default `HISTORICAL_ONLY`); cohort/surface are
fixed for an existing profile id. Probe/review/seal intents name `(profile_id, revision)`. Disposition intent: `{run_id,
decision, reason, waiver_bindings, expected_disposition_version, requested_ttl_seconds}`; prepare computes the absolute
`requested_expires_at = now + min(requested_ttl, policy.max_disposition_ttl_seconds, 604800)` and for `WAIVE`
additionally `min(…, policy.max_waiver_ttl_seconds, 86400)`, and refuses a request above those bounds rather than
silently widening it; the prepared absolute expiry is kept unchanged and final DB-time admission stays authoritative.
The decision, waiver bindings and expiry are displayed before the Human confirms.

**D7 Human review evidence** (M2/N1/N2). No new storage: notes are not retained by M10 (the operator keeps their
own notes); only digests are bound. Private projections, all `"sha256:" + sha256(canonical_json_bytes(body))` with a
`schema` field in the body, used only as data the accepted service copies (no registered domain is added):
- rubric: code-embedded `{"schema": "m10-c.narrative-rubric.v1", "criteria": [coherence, on-screen text legibility,
  audio presence, visible defects]}` → `rubric_id = "m10-c.narrative-rubric.v1"`, `rubric_digest`;
- segments: `{"schema": "m10-c.review-segments.v1", "subject_digest", "segments": [{"start": "0", "end": "END"}]}`;
- reviewer evidence: `{"schema": "m10-c.reviewer-evidence.v1", "criteria_verdicts", "notes_digest"}` where
  `notes_digest` hashes the UTF-8 notes text (≤ 20 000 chars) → `reviewer_evidence_digest`; `evidence_refs =
  ["m10-c-review:" + hex(reviewer_evidence_digest)]`; `evidence_digest` hashes `{"schema": "m10-c.review-refs.v1",
  "refs"}`;
- each finding: the slot rule id `review`, severity `BLOCKING|ADVISORY`, subject locator `<criterion>@whole|<criterion>@t=<ms>`
  (the rubric criterion travels in the locator because a finding rule id must be the slot's rule), server
  `finding_id = uuid7()`, `evidence_digest` hashing `{"schema": "m10-c.review-finding.v1", "rule_id", "severity",
  "locator", "notes_digest"}`.
Requirement/slot are fixed to the template's `review`/`human`; status is `PASS|FAIL`; ≤ 32 findings. The operator
confirms the summary before submit. Identity, qualification and independence stay service-owned.

**D8 Reads and recovery states** (M3). `GET /masters`; `GET /probes?profile_id&revision&root` (technical observations
and each probe command's M7 attempt: PLANNED → pending; ACCEPTED → "finish" (resend the sealed request);
FAILED_BEFORE_ACCEPTANCE → known failure with its recorded ResourceEvidence; SUBMIT_OUTCOME_UNKNOWN → "needs
review", only a deliberate new `execution_ref` runs a new probe; historical attempts stay listed); `GET /reviews`;
`GET /runs?root` (every run across subjects and profiles with validity, readiness and disposition versions;
stale/superseded/expired/invalidated stay visible). "Package this run" is enabled only when the server reports the run
current and READY. Custody, schema and runtime unavailability are distinct typed states (403 authorization, 503
`m10_quality_unavailable`, 409 typed M10 errors). Reads require an authenticated user; with authentication disabled
the quality routes answer 503.

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
