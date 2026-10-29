# M10-C handoff (live)

Rewrite in place; resume entry for the quality operator surface.

## State
- Worktree `.worktrees/r2-m10-c`, branch `design/r2-m10-c-operator-surface`, base `5256a9d72` (M10 accepted with
  conditions, `R2_M10_ACCEPTANCE.json`). `design/r2-m10-b` is pushed to origin by the sponsor.
- Why: M10-A has no router/UI, so deploying M10 ships a Packaging page whose prerequisites (published V2 profile,
  sealed run, PASS disposition) no operator can create. Sponsor order 2026-10-29: do step 1 (put M10 into the
  release) then step 2 (M9-B); do not stop to ask.
- Design: `docs/superpowers/specs/2026-10-29-r2-m10-c-operator-surface-design.md` (subject resolver, host probe
  catalog, quality router, Quality page, Packaging prefill).

## Reviews
- Design r1 **REWORK** (`m10-c-reviews/design-codex-review.json`): H1 one TECHNICAL requirement with two probe slots
  can never PASS (shared independence group → INDETERMINATE); H2 closure follows only `master:` refs; H3 a host
  catalog must be code-embedded, source-reviewed and qualified (A4), not generated JSON; H4 stable command
  reconstruction / receipt-first replay for every POST; H5 A3/A6 custodians re-verify startup per issuance (no
  supplied-reader API); M1 profile revision/CAS, disposition head/expiry inputs; M2 Human rubric/segment/evidence
  derivations; M3 reloadable probe/observation states and authenticated reads.

- Design r2 delta1 REWORK (N1 notes file = new custody, N2 unregistered digest domain, N3 busy not
  distinguishable, N4 HMAC protocol underspecified) → r3 (`613caa59e`) delta2 **ACCEPT_WITH_CONDITIONS**
  (`design-delta2-codex-review.json`; implementation conditions I1 subject/template tests, I2 transport security, …).

## Next step
C1 done `3bdb59b03` (resolver). C2 done `fc707e802` (embedded host-v1 catalog, 9 qualification tests). Template done (server/services/quality_template.py, 6 unit tests). Next: C3
embedded host catalog (`r2/quality/host_catalog.py`) + requalification, C3 prepare/submit seal + quality router
(`server/routers/quality.py`), C4 Quality page + Packaging prefill; then Codex review, local Chrome acceptance, sponsor
activated-host qualification + deploy (sudo), then M9-B.

## C2/D3 implementation notes (facts found while implementing)
- A4 test configs use `rule_id: "probe"` for both recipes and a placeholder `parser_digest` (`sha256:1…`). The
  embedded catalog gives each config its own rule id (`probe-container`, `probe-decode`) so policy probe rules are
  unique, and pins `parser_digest` to the sha256 of `server/services/quality_probe_worker.py`; the qualification test
  asserts it equals the current file (a worker change forces a catalog revision).
- Tool identities (this host, ffmpeg 8.0.1): ffprobe exe `fad19fce…c445` build `57a3cf6c…b59e`; ffmpeg exe
  `84d2f486…4c7d` build `fb056f85…dec2` (values from `config_for` at `3bdb59b03`).
- `close_run` checks technical slots by rule id + `config_digest` only; Human slots must carry
  `HUMAN_SHOWRUNNER_POLICY_ID` + `human_showrunner_policy_digest()`. The template's technical slot qualification and
  disagreement policies are private schema-tagged digests (`m10-c.qualification.host-deterministic-probe.v1`,
  `m10-c.disagreement.single-slot.v1`), not test placeholders.

## C3 router plan (checkpoint)
- Seal module done `7767bba08` (`server/services/quality_prepare.py`, 9 tests).
- `server/routers/quality.py`, prefix `/projects/{p}/quality`; `QualityDeps` like `PackagingDeps` + catalog
  (`HOST_CATALOG` iff `ARCREEL_QUALITY_PROBE_CATALOG=host-v1`), probe runtime, `AUTH_TOKEN_SECRET`.
- Prepare/submit pairs, request builders mirror the accepted test helpers:
  publish (`publication_request`: draft user/project/profile_id/revision/parent/cohort/surface/policy/policy_digest/
  supersession_effect/created_by/created_at → subject with draft digest + expected revision → command PUBLISH_PROFILE);
  probe (`ProbeRequest`: execution_ref = command id, requirement/slot from template, rule from slot rule ids);
  review (`HumanObservationRequest`, D7 digests); seal (`completion`: bindings from stored observations);
  dispose (`request_for` in test_quality_dispositions, bounded expiry).
- Services: `InteractiveProfilePublicationCustodian.for_request` + `ProfilePublicationService.publish`;
  `QualityProbeService.for_request(request, sessions, interactive_token, project_root, catalog, runtime).observe`;
  `HumanObservationService.for_request(..., grant_reader, project_root).record`;
  `QualityRunService.for_request(...).complete`; `DispositionCustodian.for_request` + `DispositionService.issue`.
- Reads needing additive read-only repository methods: profile heads/revisions list, observations per
  profile/subject, runs per root.
- Request builders done `8812d7fe1` (`server/services/quality_requests.py`); PG chain test
  `tests/integration/server/services/test_quality_operator_chain.py` reaches READY PASS through the real custodians and
  host-v1 probes. Next: `server/routers/quality.py` (prepare/submit + reads) and route tests, then the Quality page.
- C3 router done (`server/routers/quality.py`, registered in `server/app.py`; 5 PG route tests incl. full chain to READY,
  replay, seal tamper/other actor, agent refused, auth disabled). Next: C4 Quality page + Packaging prefill, then
  Codex implementation review.

