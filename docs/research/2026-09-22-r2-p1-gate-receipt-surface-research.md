# R2 research — P1's "smallest host-owned A–D receipt and operator-control surface"

Date: 2026-09-22
Examined checkout: `content-production-os-m7`, branch `feat/r2-m7-host-production-hardening`,
HEAD `97c27f88` (immediately after landing ADR-0089 on this lineage and closing
M3's real-media gap).

**Scope.** This is research only — no architecture decision is made here. It
maps every existing approval/decision/lock mechanism in the current codebase
against ADR-0089's four mandatory Human Gates (`R2_V1_PRODUCTION_RELEASE_STRATEGY.md`
§3, `CONTEXT.md`'s new "V1 发布与 V2 演进" glossary), so that P1 backlog item 6
("add the smallest host-owned A–D receipt and operator-control surface that
binds exact revisions **without creating a new governance database**") can be
designed from facts, not assumption.

## 1. Method

`search_graph`/`search_code` on this session's codebase-memory index returned
nothing for `r2/adaptation/*`, `r2/host_hardening/*`, or M3's render code —
the index was built 2026-09-17 against a different checkout (confirmed: it
*does* resolve `r2/production/*`, which predates that date, but 0 results for
classes that demonstrably exist in this worktree via direct grep, e.g.
`AdaptationAuthorityService`, `ExecutionRecoveryScheduler`). All findings
below are from direct `grep`/`Read` on `content-production-os-m7`, not the
graph. **Action item for a future session:** re-index this worktree
(`index_repository`) before relying on codebase-memory here again.

## 2. Gate-by-gate mapping

### Gate A — Greenlight (project + idea/source selection)

**Does not exist.** No project-level approval, greenlight, or
idea/source-selection decision concept anywhere in `lib/project_manager.py`
or elsewhere (zero case-insensitive matches for "greenlight").

### Gate B — Narrative Lock (source + script revision)

**Exists, close semantic match.** `r2/adaptation/authority.py:582`
`AdaptationAuthorityService.admit_screenplay_for_direction()` takes a
`ScreenplayAdmissionCommand` binding an exact `proposal_ref: ArtifactVersionRef`
(artifact_id + version + content_hash), re-derives and byte-compares the N+1
admission before writing, and appends a `ScreenplayAdmissionDecision` (action
`ADMIT`/`REVOKE`) to an append-only ledger with a real `authorization`
sub-record (`authenticated_principal`, `authority_role: "HUMAN_SHOWRUNNER"`,
`authorized_at`). This *is* a narrative lock in substance: it locks an exact
script revision before production may start from it.

### Gate C — Final Cut (selected master/export candidate)

**Exists, close semantic match, but latest-only, not append-only.**
`r2/production/approval_service.py:22-77` `ProductionApprovalService.promote()`
takes an `artifact_key` + `GenerationCandidate`, validates lifecycle/selection
state and `content_fingerprint`, and writes `ApprovedMasterMetadata`
(`r2/production/artifact_metadata.py:21-26`: `selected_candidate_id`,
`host_version_ref`, `approval_record: NonEmptyStr`, `selected_at`,
`selected_by`) into the artifact's `R2ArtifactMetadata.approved_master` field.
M3's `GoldenAHostIntegration.approve()` (`r2/m3/host_integration.py:253-275`)
calls this directly — the same mechanism already backs M3's production
approvals today.

**Important limitation, verified by reading the write path**
(`r2/production/artifact_bridge.py:116-144` `promote_version_with_r2_metadata`):
this is a **replace, not an append**. `replace_entries_if_matches_atomically`
overwrites the artifact manifest entry's `r2` field in place. When a later
candidate is promoted, the *previous* `ApprovedMasterMetadata` (who approved
what, when) is gone from this store — only whichever promotion is current
survives. The underlying host version manager keeps old *file* versions
around (nothing is deleted), but the *governance metadata* — the actual Gate
C receipt content — is a "what's current" pointer, not a durable audit trail.
Any caller that wants a permanent record of every past Final Cut decision
(which ADR-0089's own language — "**a gate receipt binds** the exact project
plus the input/artifact revision being approved" — reads as wanting) has to
capture it separately today; M3's `GoldenARunner.run()` does this ad hoc by
writing its own `golden_a_evidence.json` per run, which is not a systemic
guarantee for arbitrary future artifacts.

### Gate D — Publish Approval (deliverable + platform intent + visibility)

**Does not exist.** Zero matches for "publish approval"/"publish gate"
anywhere in `lib/`, `server/`, `r2/`. No concept of "platform intent" or
"visibility" attached to any decision. The existing Jianying/export path was
not located as a class (`grep "class.*Export"` → 0 matches); it is likely
function-based and was not traced further in this pass — open item for the
design phase, not yet a confirmed fact either way.

## 3. Three pre-existing decision/receipt shapes — not one, three

This matters directly for "without creating a new governance database": there
are already **three structurally different** decision-ledger patterns in this
codebase, each scoped to its own milestone's domain, none of them a generic
"Human Gate" abstraction:

1. **M5C** (`r2/narrative_lifecycle/acceptance.py`): `NarrativeAcceptanceService`
   + `AuthorityKernel` produce a `NarrativeDecisionReceipt` per decision
   (`decide_revision`, `review_change_set`, `resolve_change_set_conflict`,
   `admit_canon_handoff`). Real append-only history, its own authority-kernel
   machinery, scoped to narrative-revision/Canon-handoff decisions.
2. **M6** (`r2/adaptation/authority.py`, `r2/contracts/adaptation.py:316`):
   `AdaptationDecision` (union of `MapApprovalDecision | ProfileWaiverDecision
   | ScreenplayAdmissionDecision`), each with `sequence`, `decision_digest`,
   `created_at`, a `command` binding an exact `ArtifactVersionRef`, and an
   `authorization` (principal/role/timestamp). Real append-only ledger via
   `AdaptationAuthorityRepositoryPort.append_decision_and_advance_head`
   (`r2/adaptation/ports.py:128-130`), `decision_id` is a global identity
   registry keyed by `(user_id, project_name)`. This is the closest thing to
   a generic pattern already in the codebase — but it is still named and
   typed around adaptation-specific decision kinds (map approval, waiver,
   screenplay admission), not a generic "gate".
3. **M3/M4** (`r2/production/`): `ApprovedMasterMetadata`, latest-only, as
   described in §2's Gate C section above.

A lighter-weight fourth data point, **not** strong enough to be a Gate on its
own: `CreativeApprovalStatus` (`DRAFT/PROPOSED/REVIEW_REQUIRED/APPROVED/REJECTED`)
is a single status field on `ScriptArtifact`/`SceneSpec` with no
authorization/identity binding at all.

## 4. Operator-control surface: does not exist at any layer

`grep -rl "AdaptationAuthorityService\|ProductionApprovalService\|ScreenplayAdmissionCommand\|MapApprovalCommand" server/ frontend/src/` returns
**zero results**. Every call into any of these services exists only in test
code today (e.g. `FakeAuthority`, a test double for
`AdaptationShowrunnerAuthorityPort` — there is no concrete non-test
implementation of that port anywhere outside `r2/adaptation/authority.py`
itself). There is no HTTP route, no CLI command, and no frontend affordance
that lets a real human operator press "approve" for any of the four gates.
This is not a gap specific to Gates A/D — it is true for B and C too, despite
their backend mechanisms already being real and tested.

## 5. Facts / inference / unknowns / candidate reuse targets

**Facts** (all cited above with file:line): Gate B and Gate C both have real,
tested backend mechanisms; Gate A and Gate D have none; three distinct
decision-ledger shapes already exist (M5C, M6, M3/M4); zero operator-facing
surface (UI or API) exists for any gate.

**Inference:** the host version manager likely retains old file versions on
disk even after a newer candidate is promoted (consistent with "promotion"
being a pointer change, not a delete) — not directly confirmed by reading
`lib/version_manager.py` in this pass.

**Unknowns:**
- Whether the existing Jianying/export code path has any structure that maps
  onto Gate D's "deliverable + platform intent + visibility" concept, or
  whether that triple needs to be modeled from scratch.
- Whether M5C's `NarrativeDecisionReceipt`/`AuthorityKernel` could be
  generalized to also carry Gate A/D decisions, versus being left
  narrative-specific and building something new for A/D.
- Exact host DB schema/migration shape needed for a new receipt table (not
  yet designed) and whether "no new governance database" is satisfied by a
  new *table* in the existing host database (near-certainly yes, since P0
  item 1-5 already added multiple new tables like `BackupSetRepository`
  without anyone calling that a new governance database) or something
  stricter.

**Candidate reuse targets for the design phase:**
1. `AdaptationDecision`'s shape (`sequence` + `decision_digest` +
   `ArtifactVersionRef` binding + `authorization` record) is the most
   generic-looking existing pattern — a new, small, gate-scoped table
   following the *same shape* (not literally the same table, since that one
   is typed around adaptation-specific decision kinds) is a plausible
   "smallest new surface" if the answer is "add one new host-owned ledger
   used consistently by all four gates."
2. Alternatively, Gates B and C could keep using their own existing
   mechanisms untouched, with a new, thin, read-only "gate receipt"
   projection/view built only for Gates A and D plus a unifying display
   layer — smaller code diff, but leaves three-going-on-four different
   shapes for future maintainers to reconcile, arguably in tension with
   "smallest" read as "smallest total surface area to reason about" rather
   than "smallest diff."

## 6. Cross-referenced against frozen precedent — conclusion, not an open menu

The two candidates in §5 were re-checked against `R2_04_DECISION_REGISTRY.json`
(30 decisions, all `LOCKED`/`ACTIVE`) rather than left as an unresolved
preference. Relevant precedent:

- **R2-DEC-001** ("Human Showrunner remains final creative/governance
  authority", `LOCKED`): "Human approval/override is explicit, auditable, and
  cannot be replaced by autonomous agent mutation." Explicitly lists
  `ProductionApprovalService` as an affected component.
- **R2-DEC-025** ("ApprovedMaster requires explicit selection", `LOCKED`): "A
  successful generation is not an approved master; selection/approval is
  explicit and failed later generations preserve the existing master."
  Explicitly binds `ProductionApprovalService` + "ArcReel version storage".
  `reopen_conditions: ["contract contradiction discovered"]` — this contract
  is frozen, not a starting point to redesign.
- **R2-DEC-003/010/016** ("Five authority planes", "Factual/fiction truth
  distinct", "Shot readiness distinct from content/runtime status") — three
  independent, all-`LOCKED` decisions that each freeze a *separation*
  between authority domains that could have been merged into one generic
  mechanism, and explicitly chose not to. This is a consistent, repeated
  architectural preference across the whole frozen registry, not a one-off.

**This settles §5's open question:** a single new shared ledger used by all
four gates would run against the registry's own repeated, LOCKED preference
for domain-scoped authority over merged generic mechanisms, and Gate C's
existing contract (`ApprovedMaster` is a "current selection," per R2-DEC-025)
is frozen and not open to being replaced by a new shape. The direction this
research settles on for the design phase: **keep Gate B and Gate C's existing
mechanisms exactly as they are (no contract change); add a small, additive,
append-only audit companion to Gate C specifically** (so it satisfies
R2-DEC-001's "auditable" bar, which its current latest-only shape does not,
without touching the frozen "current master" pointer contract); **and build
two new, small, domain-appropriately-named decision records for Gate A and
Gate D**, each following the same established shape (explicit command +
an exact artifact/project-revision binding + an authorization sub-record +
append-only) as precedent from M5C/M6, but as their own distinct constructs
rather than folded into M6's adaptation-specific `AdaptationDecision` union.

## 7. Operator-control surface — a real, reusable precedent found, and why it doesn't fully apply

`frontend/src/components/canvas/timeline/VersionTimeMachine.tsx` (440 lines,
tested, real feature) already gives a human operator a working "browse
versions, see which is current, click an action, get a toast" interaction —
proof the host has a real, working pattern for exactly this *shape* of
human-facing control surface. Traced its action end to end: `handleRestore`
→ `API.restoreVersion` → `POST /projects/{project}/versions/{type}/{id}/restore/{version}`
(`server/routers/versions.py:344`) → `restore_resource_version`, which calls
straight into the host's own generic `VersionManager` "switch current-version
pointer" mechanism. **This confirms, independently of §4's grep-based
finding, that zero real surface reaches R2's approval layer today**: this
restore endpoint has no `ProductionApprovalService` call, no candidate
lifecycle/fingerprint validation, no `selected_by`/`approval_record` —
it is the pre-R2 host's own file-version-switching feature, not an R2 Gate.

**Conclusion, not left open:** ArcReel is a web-app product end to end
(`frontend/` React SPA is the primary interface per this repo's own
`AGENTS.md` first line, not a CLI tool) — an operator using ArcReel to
produce and review a video would expect to approve a gate in the same web
app, not switch to a separate CLI. The "smallest" reading that stays
consistent with the product's own nature is: real new API endpoints (added
under `server/routers/`, following existing router registration conventions
— required regardless of front-end choice, since something must call into
the approval services) plus a minimal front-end affordance reusing
`VersionTimeMachine`'s established interaction *pattern* (panel-driven
browse → select → confirm → toast) rather than its component (whose
underlying endpoint is the wrong mechanism, per above) — not a CLI-only
surface, and not a new dedicated multi-page UI either.

