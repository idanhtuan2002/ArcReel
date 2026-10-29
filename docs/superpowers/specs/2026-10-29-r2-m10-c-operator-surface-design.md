# R2 M10-C — Quality operator surface (design)

Status: design for review, 2026-10-29. Branch `design/r2-m10-c-operator-surface` from the accepted M10 record
`5256a9d72` (`docs/r2/evidence/R2_M10_ACCEPTANCE.json`).

## 1. Problem (facts)

- M10-A (profiles, probes, narrative observations, run closure, dispositions) is accepted as services only. Every
  A-packet design states "no router, default registration" (A5 §1, A6 §1; A4 route qualification limits). The M10
  plan's file map nevertheless lists `server/routers/quality.py` — "authenticated, migration-gated HTTP interface"
  (`docs/superpowers/plans/2026-09-16-r2-m10-quality-packaging.md` §File map); it was never built.
- M10-B's Packaging page needs a sealed run (`quality_run_id`, `quality_run_digest`), a published V2 profile and a
  PASS disposition. On a deployed host no operator can create any of them, so deploying M10 ships an unusable page.
  The B7 pilots created them with scripts calling the services directly (`m10-b7-pilot/scripts`).
- Services verify a client-built `AssessedSubject` against authority (`server/services/quality_runs.py`
  `_subject_authoritative`) but nothing builds one in production. Real V2 manifests already carry what is needed: each
  approved artifact's R2 metadata has `approved_master` and `direct_dependencies` (checked read-only on the V2 host:
  FINAL → SH01..SH03, each with its approval record).
- The production probe catalog is empty (`r2/quality/probes.py` `DEFAULT_PROBE_CATALOG`); probe configs pin tool
  executable and build digests, so a host must supply a catalog for its own tools.
- Route grant readers must reuse the startup-verified reader (`00912922e`): the attestor serves one proof at a time.

## 2. Scope

Wiring only: a server-side subject resolver, a host probe catalog, one router and one UI page, all calling the
accepted A3–A6 and B services unchanged. No new contract, authority, adapter, model or migration. A need to change an
accepted service's semantics stops this packet for review.

Out of scope: profile policy design beyond the template below, references for REFERENCE_VMAF, captions authoring,
FACTUAL/MODEL observation classes (A5 D1/D2 keep them fail-closed), M11.

## 3. Decisions

**D1 Subject resolver** (`server/services/quality_subjects.py`). Input: `(user_id, project_name, root_artifact_key)`.
Read the manifest snapshot once; the closure is the root plus every artifact reachable through `direct_dependencies`
refs (each ref resolves to an artifact key in the same manifest; unknown or cyclic refs refuse). For every artifact in
the closure: the head is `DatabaseMasterResolver.get_exact` (refuse if absent, diverged or without `approved_master`
metadata), the metadata snapshot is the manifest R2 body, edges are `(parent, dependency.ref, child)`. Build
`MasterBindingV1` and `AssessedSubject` with their digests through the existing digest functions; `artifact_ref`/
`artifact_digest` from the root head; `content_basis_digest` from the root metadata's content basis as the existing
digest helper defines it; caption/audio digests `None` (no caption/audio slots in the template). The service layer
still runs `_subject_authoritative` and the master locks, so the resolver is a convenience that cannot widen authority.
Rejected: client-built subjects (the UI would need the whole closure); caching subjects (staleness is the services'
job).

**D2 Host probe catalog.** `scripts/r2/build_m10_probe_catalog.py` hashes the host's `ffmpeg`/`ffprobe` (executable
digest and `-version` build digest, as the A4 recipe fixtures do) and writes a catalog of the reference-free recipes
`CONTAINER_STREAM`, `DECODE`, `LOUDNESS`, `INTERVALS` with the A4 default parameters. The app reads the path from
`ARCREEL_QUALITY_PROBE_CATALOG` at startup into `app.state`; absent → probe routes answer 503
`m10_quality_unavailable`. The probe runtime already re-verifies tool digests per run, so a drifted tool fails the
probe, not silently. Rejected: computing the catalog per request (unqualified drift becomes invisible).

**D3 Profile template.** `GET /quality/profile-template` returns a draft V2 policy: the operator picks the platform
constraints (dimensions, duration window, locales, title/description bounds, banned phrases, asset roles) and the
requirements are fixed to one TECHNICAL requirement (slots CONTAINER_STREAM and DECODE) and one NARRATIVE/HUMAN
review, freshness 7 days. The operator edits it in the UI and publishes it; the server derives identity fields and the
A3 custodian authorizes (Human, interactive session).

**D4 Routes** (`server/routers/quality.py`, prefix `/projects/{project_name}/quality`). Reads use `CurrentUser`;
every mutation uses `InteractiveUser` (the embedded agent token is refused, as for packaging selection/export); all
requests are server-built with server-computed command digests (`_sealed` pattern from `server/routers/packaging.py`).
- `GET /masters` — approved master roots with their closure status (resolver dry run).
- `GET /profile-template`, `GET /profiles` (current revisions), `POST /profiles` (A3 publication).
- `POST /probes` `{command_id, profile_id, root_artifact_key, requirement_id, slot_id}` → technical observation.
- `POST /reviews` `{command_id, profile_id, root_artifact_key, status, findings, notes}` → narrative observation
  (the notes digest is the reviewer evidence digest; notes are stored as the evidence ref body).
- `POST /runs` `{command_id, profile_id, root_artifact_key, observation_ids}` → seal.
- `GET /runs?root_artifact_key&profile_id` → runs with validity and readiness.
- `POST /dispositions` `{command_id, run_id, decision, reason, waivers}` → A6 disposition.
Errors map through the packaging `_api_error` vocabulary; i18n keys for new codes in en/vi/zh.

**D5 UI** (`frontend/src/features/quality/`, route `quality`, sidebar entry before Packaging). One page, steps in the
real order: master → profile → probes → review → seal → disposition, each showing only server results, with a link
"Package this run" that opens Packaging with `run`, `digest`, `artifact`, `cohort`, `surface` query parameters; the
Packaging page prefills its fields from them (read-only provenance stays server-derived).

**D6 Grant reader and custody.** Same host wiring as packaging: `app.state.governance_grants`, custody owner from
host config (root by default).

## 4. Verification

- Resolver unit tests over manifest fixtures (closure, unknown ref, cycle, missing approval, diverged head) and a PG
  integration test that its subject passes `_subject_authoritative`.
- Route tests on PG with the real custodians and the real confined probe runtime: the full chain to a PASS
  disposition, then the existing Packaging flow on that run; agent token refused on every mutation; stale replays.
- Catalog builder test on the host tools; startup without a catalog answers 503.
- UI tests (states, invalidation, i18n), `pnpm check`, axe in Chrome on the pilot host.
- Acceptance: an operator in Chrome completes master → disposition → package → export with no scripts on the local
  pilot host; then activated-host qualification on V2 staging (B C2/C4) by the sponsor before deploy.

## 5. Stop conditions

Any change to accepted A3–A6/B service behavior, a new authority or contract, or a need for a production-host action
without the sponsor.
