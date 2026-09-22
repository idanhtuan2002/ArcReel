# R2 P1 design — the smallest host-owned A–D receipt and operator-control surface

Date: 2026-09-22. Builds on
`docs/research/2026-09-22-r2-p1-gate-receipt-surface-research.md` (facts,
gate-by-gate mapping, the two settled research questions in its sections 6-7).
Implements ADR-0089 / `R2_V1_PRODUCTION_RELEASE_STRATEGY.md` §5 P1 backlog
item 6 only. Items 7-10 (run both products through the release candidate,
run the gates, write the runbook, tag) are named in §9 as follow-on work that
consumes this item's output; they are not designed here.

## 1. Goal and boundary

**Goal:** give a real human operator a way to actually press "approve" for
each of the four ADR-0089 Human Gates, with every approval bound to an exact
project/artifact revision and durably, auditably recorded — without building
a new governance database, and without contradicting any `LOCKED` decision in
`R2_04_DECISION_REGISTRY.json`.

**Non-goals (explicit, matching the "smallest" mandate):**
- No unification of the three existing decision-ledger shapes (M5C
  `NarrativeDecisionReceipt`, M6 `AdaptationDecision`, M3/M4
  `ApprovedMasterMetadata`) into one generic table. Research §6 found this
  would contradict R2-DEC-003/010/016's repeated, LOCKED preference for
  domain-scoped authority.
- No routing of M3's render output through M7-B's candidate-store pipeline
  (`CandidateObjectPort.prepare_candidate` → `VerifiedCandidateObject`) to
  make `AtomicPromotionService` directly callable from M3. That bridge is
  real, valuable, and explicitly named as deferred work in
  `docs/r2/evidence/R2_M7_B_ATOMIC_PROMOTION.json`'s own
  `master_reader_boundary_and_legacy_projection.deferred_work` — but pulling
  it in now would turn "the smallest surface" into a full M7-B/M3 pipeline
  merger. Named as a separate deferred item in §8, not silently dropped.
- No new frontend page. The UI addition is a small affordance reusing an
  existing interaction pattern (research §7), not a new route/screen.
- No change to Gate B's (`ScreenplayAdmissionDecision`) or Gate C's
  (`ApprovedMasterMetadata`/`ProductionApprovalService`) existing contracts.
  Gate C gets one additive, append-only companion (§4); nothing about its
  current-selection semantics changes, per R2-DEC-025's `LOCKED` status.

## 2. Existing seams and measured gaps (from research)

| Gate | Backend mechanism | Durable audit trail? | Operator surface |
|---|---|---|---|
| A — Greenlight | none | n/a | none |
| B — Narrative Lock | `AdaptationAuthorityService.admit_screenplay_for_direction` → `ScreenplayAdmissionDecision`, append-only | yes | none |
| C — Final Cut | `ProductionApprovalService.promote` → `ApprovedMasterMetadata` | **no — replace, not append** (research §2) | none |
| D — Publish Approval | none | n/a | none |

Zero HTTP route, CLI command, or frontend affordance reaches any of these
four mechanisms today (research §4, independently reconfirmed in §7 by
tracing `VersionTimeMachine.tsx`'s restore action to a completely unrelated,
pre-R2 `VersionManager` pointer-switch with no R2 approval semantics at all).

A fifth mechanism, `AtomicPromotionService` (`r2/host_hardening/promotion.py`,
M7-B), already provides exactly the append-only, idempotent, CAS-protected
shape Gate C's audit trail needs (`MasterHeadVersionModel`: append-only,
carries `approval_record`/`candidate_id`/`content_digest`/`promoted_at`,
one row per promotion, never overwritten) — but it operates on
`VerifiedCandidateObject` (M7-B's own hardened candidate-store output), not
on `GenerationCandidate` (the model `ProductionApprovalService` and every
M3/M4 caller actually uses). It has zero real callers today; its own
evidence file names this exact gap as deferred work. It is the *template*
this design reuses (§4), not a dependency this design takes on directly —
see §1's non-goals and §8's deferred-item note.

## 3. Canonical vocabulary

- **Gate receipt**: a durable, append-only record that one specific Human
  Gate decision was made, by whom, when, and against exactly which
  project/artifact revision. Distinct from an *operational selection*
  (e.g., "which candidate is currently the master") — a gate receipt is
  never overwritten or deleted once written; an operational selection can
  change without invalidating the historical receipts that led to it.
- **Gate binding**: the exact revision identity a receipt is anchored to.
  For Gates B/C this is already `ArtifactVersionRef`/`content_fingerprint`-shaped
  (reused as-is). For the two new gates:
  - Gate A binds `(project_name, source_digest)` — `source_digest` is a
    caller-supplied content hash of whatever idea/source material is being
    greenlit. The current project model (`lib/project_manager.py`) has no
    richer "idea" object to bind to (`source_kind` is a coarse
    `novel`/`screenplay` category fixed at creation, not a content
    reference) — this is the honest, minimal binding available today, not
    an invented richer concept.
  - Gate D binds `(project_name, deliverable_digest, platform, visibility)`.
    `deliverable_digest` reuses whatever content digest the approved final
    export already carries (`ApprovedMasterMetadata`'s candidate content, or
    the new Gate-C companion's `content_digest` — see §4). `platform`/
    `visibility` are new, caller-supplied free-text fields (e.g.
    `"youtube"`/`"unlisted"`) — research §4 confirmed no existing "platform
    intent" or "visibility" concept exists anywhere to reuse.

## 4. Fixed contracts

### 4.1 A new, small, shared receipt shape — reused as a *pattern*, not a shared table

Modeled directly on `AdaptationDecisionAuthorization`
(`r2/contracts/adaptation.py:276-283`) and `AtomicPromotionService`'s
`PromotionReceipt` idempotency shape, but as a standalone contract module
(`r2/contracts/gates.py`, new) — not imported from `r2.contracts.adaptation`,
since Gate A/D decisions are not adaptation-domain decisions (research §6):

```python
class GateAuthorization(R2ContractModel):
    authenticated_principal: NonEmptyStr
    authority_role: Literal["HUMAN_OPERATOR"]
    authorized_at: datetime  # tz-aware, matches existing _aware validator convention

class GreenlightDecision(R2ContractModel):
    decision_id: NonEmptyStr          # global identity, per (user_id, project_name), mirrors M6's decision_id registry
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    source_digest: NonEmptyStr
    action: Literal["GREENLIGHT", "REVOKE"]
    authorization: GateAuthorization
    sequence: Annotated[int, Field(ge=1)]
    created_at: datetime

class PublishApprovalDecision(R2ContractModel):
    decision_id: NonEmptyStr
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    deliverable_digest: NonEmptyStr
    platform: NonEmptyStr
    visibility: NonEmptyStr
    action: Literal["APPROVE_PUBLISH", "REVOKE"]
    authorization: GateAuthorization
    sequence: Annotated[int, Field(ge=1)]
    created_at: datetime
```

Each gets its own append-only repository table
(`gate_greenlight_decisions`, `gate_publish_approval_decisions`), following
`AdaptationDecisionModel`'s exact persistence pattern
(`lib/db/models/adaptation.py:313-352`): PK `(user_id, project_name,
decision_id)`, unique `(user_id, project_name, sequence)` per project,
`sequence` assigned by the repository (not the caller) to make ordering
gap-free and race-safe. No head/pointer table is needed for these two (unlike
M6's `AdaptationHeadModel`) — Gates A and D do not need a "current effective
decision" concept the way a screenplay branch head does; the full history
*is* the state (an operator can see every past greenlight/publish decision
directly).

### 4.2 Gate C's audit companion

A new, small, append-only table (`gate_final_cut_receipts`). **Deliberately
not written from inside `ProductionApprovalService.promote()`** — a real
constraint found while planning implementation: `ProductionApprovalService`
is synchronous and operates purely over the file-based
`ArtifactManifestPort`/`ProjectArtifactManifestAdapter` (no async DB
session in scope at all), and is constructed directly at 10+ call sites
across M3, M4, and M6 (`r2/m3/host_integration.py`,
`tests/integration/r2/m4/test_approved_master_semantics.py`,
`tests/integration/r2/production/test_master_promotion_integration.py`,
`tests/integration/r2/test_m6_dual_profile_acceptance.py`, and more).
Changing its constructor to require a new async-DB-backed repository
dependency would ripple into every one of those call sites for no reason
connected to their own tests' purpose — the opposite of "smallest surface."

Instead, `FinalCutReceipt` is written by the **new async route handler**
(§5's `POST .../gates/final-cut`), immediately after it `await
asyncio.to_thread(...)`-calls the existing, completely unmodified
`ProductionApprovalService.promote()` — mirroring the exact
sync-host-call-bridged-into-an-async-route pattern already established in
`server/routers/versions.py:349-355`'s `restore_version` handler. The
handler already holds every field a receipt needs (`artifact_key`,
`candidate`, `approval_record`, `selected_at`) because it is the same
request that was just passed to `promote()`; no new coupling between the
two is needed.

```python
class FinalCutReceipt(R2ContractModel):
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    artifact_key: NonEmptyStr
    selected_candidate_id: NonEmptyStr
    content_fingerprint: NonEmptyStr
    approval_record: NonEmptyStr
    selected_by: NonEmptyStr
    selected_at: datetime
    sequence: Annotated[int, Field(ge=1)]  # per (user_id, project_name, artifact_key)
```

`ProductionApprovalService`'s own code, signature, and every existing
caller (including `GoldenAHostIntegration.approve`, and every M3/M4/M6 test
constructing it directly) are **completely untouched** by this design. A
receipt is written whenever the new route is used, including for a *no-op*
re-approval (the `changed=False` branch at `approval_service.py:56-61`
today returns early but still represents a real, explicit gate decision the
operator made through the route) — but any caller that reaches
`ProductionApprovalService.promote()` directly, bypassing the new route
(every current test, and any future non-HTTP caller), gets no receipt. This
is an accepted, disclosed limitation (§8): the audit trail covers
approvals made *through the new operator surface*, not every possible
programmatic call to the underlying service — consistent with "smallest
surface" and with ADR-0089's own framing (Gate receipts exist to prove a
*human* made a decision through a controlled surface, not to audit every
internal service call).

## 5. Operator-control surface

**Backend:** one new router, `server/routers/gates.py`, registered exactly
like every existing router (`server/app.py:634`'s pattern —
`dependencies=[Depends(get_current_user)]`, so gate approval requires the
same session-JWT authentication as every other authenticated host action;
no new auth concept). Four endpoints, one per gate, each taking the gate's
command shape from §4 and returning the resulting decision record:

```text
POST /api/v1/projects/{project_name}/gates/greenlight
POST /api/v1/projects/{project_name}/gates/narrative-lock      (thin wrapper over the existing AdaptationAuthorityService call)
POST /api/v1/projects/{project_name}/gates/final-cut           (calls the existing, unmodified ProductionApprovalService.promote via asyncio.to_thread, then the handler itself appends a FinalCutReceipt row -- see §4.2)
POST /api/v1/projects/{project_name}/gates/publish-approval
GET  /api/v1/projects/{project_name}/gates                     (read all four gates' current/history state for display)
```

`authenticated_principal` for every endpoint is derived from the existing
session JWT (`get_current_user`), not a caller-supplied field — an operator
cannot approve a gate as someone else.

**Frontend:** one small new component (e.g. `GateApprovalPanel.tsx`),
modeled on `VersionTimeMachine.tsx`'s established interaction pattern
(research §7): a collapsible panel, local `useState` for
open/loading/selected state, `useAppStore`'s `pushToast` for
success/failure feedback — no new global store. It calls the `GET
.../gates` endpoint to render each gate's current status and history, and a
button per actionable gate that POSTs the approval. Placed in the existing
project/episode view (exact placement is an implementation-plan-level
decision, not a design-level one) rather than as a new dedicated route.

## 6. Why not delegate to `AtomicPromotionService` now

Considered directly (research surfaced it as the closest existing
precedent) and rejected for *this* item, not forgotten:

`AtomicPromotionService.promote()` is async, idempotent via `command_id`,
and its `MasterHeadVersionModel` is a strictly better-shaped audit trail
than the new `gate_final_cut_receipts` table proposed in §4.2. The new route
handler in §5 is itself already async (every FastAPI route is), so the
sync/async mismatch that would have blocked calling it from inside
`ProductionApprovalService` (§4.2) does not block calling it from the
*route* — but a real, unchanged blocker remains: `AtomicPromotionService`
promotes a `VerifiedCandidateObject` (M7-B's own hardened candidate-store
output, keyed by a `candidate_id` that only exists once something has gone
through `CandidateObjectPort.prepare_candidate`), while every real M3/M4
candidate the route would actually receive is a `GenerationCandidate` — a
different shape produced by a completely different pipeline that has never
run through M7-B's candidate store at all. Routing M3's
`GoldenALocalProducer` output through `prepare_candidate` first so a
`VerifiedCandidateObject` exists for `AtomicPromotionService` to promote is
a genuine, valuable pipeline unification, but it is its own project, not a
"smallest surface" addition — `docs/r2/evidence/R2_M7_B_ATOMIC_PROMOTION.json`
already names this exact bridge as deferred, deliberately, for the same
reason ("building this now against a target with no live caller would be
speculative, not reuse" — now there *is* a live caller, M3, but the
`GenerationCandidate`/`VerifiedCandidateObject` compatibility gap is
unchanged). §4.2's small additive table, written directly by the route
rather than by either service, is the smaller, correct-for-now answer; the
`AtomicPromotionService` bridge remains named and deferred (§8), a
candidate for a future milestone once M3/M4's candidate pipeline is itself
being revisited for other reasons.

## 7. Migration

One new Alembic revision, downstream of the current head, adding exactly
three tables (`gate_greenlight_decisions`, `gate_publish_approval_decisions`,
`gate_final_cut_receipts`) — no changes to any existing table. Follows
`lib/db/models/host_hardening.py`'s `MasterHeadVersionModel`/
`PromotionReceiptModel` as the most recent, same-branch precedent for
column types, indexes, and unique constraints (research §2), since that
precedent is more current than M6's `AdaptationDecisionModel` while
expressing the same append-only pattern.

## 8. Deferred work (named, not silently dropped)

- **`AtomicPromotionService` ⟷ M3/M4 candidate-pipeline bridge** (§6): real,
  valuable, requires routing M3/M4 output through M7-B's candidate store
  (`CandidateObjectPort.prepare_candidate`) first so a `VerifiedCandidateObject`
  exists for it to promote. Not this item's scope.
- **Gate D's `deliverable_digest` source**: this design reuses whatever
  digest the approved Final Cut candidate already carries. If a *later*,
  distinct export/packaging step (Jianying draft or a real final-deliverable
  export — research §4 found no such single mechanism exists today) needs
  its own separate digest, Gate D's binding will need revisiting then; not
  designed here since no such mechanism currently exists to bind against.
- **Gate A's binding richness**: `source_digest` alone is honest but thin —
  it does not durably capture the actual idea/source *content*, only its
  hash. A V2-era richer "Idea" object (if the product ever wants operators
  to browse past greenlit ideas with full content, not just a hash) is out
  of scope for V1's bounded release.

## 9. Relationship to P1 items 7-10

Item 7 ("run both products end to end... including... all four gates")
becomes possible only once this item's endpoints exist — running it is
verification work for a later plan task, not part of this design. Items
8-10 (gate re-run, runbook, release tag) are unaffected by this design's
internal shape and are scoped entirely in the implementation plan.

## 10. Verification matrix

| Requirement (ADR-0089 §3 / strategy doc §3) | How this design proves it |
|---|---|
| all four gates require an explicit human decision | four new/reused backend mechanisms, each requiring `authenticated_principal` derived from a real session JWT, never caller-supplied |
| a gate receipt binds the exact project + revision | `ArtifactVersionRef`/`content_fingerprint` reuse for B/C; `source_digest` / `deliverable_digest`+platform+visibility for A/D |
| agents may prepare evidence, not approve | every endpoint requires the human's own session JWT; no service-account or agent-callable path is added |
| no new governance database | three new tables inside the existing host database, following the exact precedent already set by M7-B's own tables in this same database |
| Gate C's decision is auditable (R2-DEC-001) | new additive `gate_final_cut_receipts`, append-only, one row per promotion including no-op re-approvals |

## 11. Exit states

- **CLOSED**: all four endpoints exist, are reachable only via authenticated
  session JWT, write durable append-only receipts, the new frontend panel
  can drive all four from a real browser session, migration round-trips
  cleanly, full gate suite green at the exact HEAD.
- **REJECTED**: any gate can be approved without a real authenticated
  principal, any receipt is mutable/overwritable after the fact, or Gate B/C's
  existing `LOCKED` contracts are changed rather than additively extended.
