# Workspace-wide Showrunner grants and per-project autopilot

Date: 2026-11-10. Branch `impl/autonomous-production`, HEAD `7cb2ed39d`. Read-only research; no database, service,
staging host, key material or `.env` was touched. Labels: **FACT** (path:line, read at this HEAD), **INFER**
(reasoned from facts, not executed), **UNKNOWN** (not established).

Sponsor decisions (2026-11-10) under study: one ceremony signs a workspace-wide Showrunner grant (every current and
future project of the user, with expiry, revocable; existing per-project grants stay valid); a per-project
**autopilot** toggle, switched on by the Showrunner interactively, after which the system starts story-part runs and
film runs on its own; an action "auto-create films for finished stories"; no limits beyond each run's own caps and
the grant's own expiry.

---

## 1. Current authority model

### 1.1 Decisions on record

- ADR-0103 §1: a grant is scoped to the exact `(user_id, project_name, authenticated_principal, HUMAN_SHOWRUNNER)`,
  an issuer key, an issue event, a validity interval and a monotonic head; "No wildcard project, implicit admin
  conversion or route for self-issuance exists." (FACT docs/adr/0103-showrunner-grants-and-spatial-review-custody.md:13).
  Governance alone imports signed events (FACT :14). Activation needs an operator-custodied verification key, a pinned
  image, a retained grant-head checkpoint and a restore drill (FACT :7, :24).
- ADR-0111: a current *project* Showrunner may delegate operations to a distinct run-scoped automation principal;
  delegations are append-only child records bound to the exact Start command, parent event and frozen input/policy;
  "Start must lock the parent and create run plus child grant in one transaction"; lock order "owner heads, signed
  parent, child head, run and decision"; "no historical project starts automatically"
  (FACT docs/adr/0111-autonomous-production-run-authority.md:13, :17, :19).
- ADR-0116 §8: "Starting the next part's run is a Showrunner action like any run start … a run that starts runs on its
  own would need delegated start authority, which is a separate decision." (FACT docs/adr/0116-…book-plan.md:17).
- ADR-0122 §1 / "Not adopted": story-sync needs an interactive user; "automatic re-sync of a film when its story
  changes" was explicitly not adopted because an edited story file can conflict with planned episodes
  (FACT docs/adr/0122-story-projects-film-projects-and-a-control-room.md:9, :16).

The sponsor's 2026-11-10 decisions therefore **amend ADR-0103 §1 (no wildcard), ADR-0116 §8 and ADR-0122's
"not adopted" clause**; new ADRs are needed (INFER).

### 1.2 What is signed, by which key

- Grant event body (FACT r2/contracts/showrunner_grant.py:41-76): `schema = governance.showrunner_grant_event.v1`,
  `event_type ISSUE|REVOKE`, `user_id`, `project_name`, `principal`, `role = HUMAN_SHOWRUNNER`, `sequence`,
  `previous_event_digest`, `issued_at`, `signer_key_id`, and for ISSUE `not_before`/`expires_at`. `"*"` is rejected for
  user/project/principal/key (FACT :57-62). Envelope `{"body","signature"}`, canonical JSON, 64-byte Ed25519 signature;
  the digest is `sha256(canonical body)` (FACT :100-143).
- Signing is offline only: `sign_grant_event` (FACT r2/governance/ceremony.py:178-213) with raw Ed25519 private bytes;
  "the application never holds a signing key" (FACT :4-5). CLI `scripts/r2/governance_ceremony.py sign-event` takes
  `--user-id --project --principal --sequence --previous-event-digest --expires-at` (FACT scripts/r2/governance_ceremony.py:115-125).
- Two distinct keys: a grant-event key and a checkpoint key, registered in a verifier registry that must keep them
  distinct (FACT r2/governance/ceremony.py:91-111); an approved-deployment record binds the pinned image to the
  registry bytes (FACT :114-136).
- Checkpoint body `governance.grant_head_checkpoint.v1`: deployment, `checkpoint_sequence`, predecessor digest,
  signer key, and sorted unique `heads` `(user_id, project_name, principal, head_sequence, head_event_digest)`; wildcard
  rejected (FACT r2/contracts/grant_checkpoint.py:41-84); at most 10 000 heads, 4 MiB (FACT :19-20, :128). A
  high-water record chains each retained checkpoint (FACT r2/governance/ceremony.py:216-248).

### 1.3 Where it is verified, and what a scope match is

- `verify_grant_event`: key id + Ed25519 over the canonical body (FACT r2/governance/grant_signature.py:17-32).
- `GrantScopeV1(user_id, project_name, principal)` and `_matches_scope` = exact equality on the three fields plus
  role (FACT r2/governance/grant_transition.py:12-29). `verify_next_grant_event` enforces scope, `issued_at ≤ DB now`,
  unexpired ISSUE, genesis `sequence 1 ISSUE`, `sequence+1`, predecessor digest, strictly increasing `issued_at`, and
  **alternating type** (ISSUE→REVOKE→ISSUE) (FACT :32-65). Consequence: extending an expiry is REVOKE then ISSUE, so
  the head sequence always moves (INFER from :62).
- Ledger tables `r2_showrunner_grant_heads` (PK user/project/principal, FK to the current event) and
  `r2_showrunner_grant_events` (PK + sequence, raw bytes, digest, type) (FACT lib/db/models/governance_grant.py:22-78);
  `project_name String(255)` with no pattern constraint (FACT :45, :70).
- `GovernanceGrantImporter.import_event` takes the shared import fence, claims/locks the head row (`FOR UPDATE`),
  re-verifies the full chain, replays identical bytes, and appends under DB time (FACT server/services/governance_grants.py:154-235).
- `CurrentShowrunnerGrantReader.require_current_locked` (FACT :238-259): needs a transaction, locks the exact head,
  re-verifies every stored event's bytes and the chain (`_current_locked`, FACT :108-151), and requires the head to be an
  ISSUE with `not_before ≤ now < expires_at` using `clock_timestamp()` on PostgreSQL (FACT :45-51).
- `require_historical_issue_locked` (FACT :261-307): current grant first, then the referenced ISSUE in the same exact
  chain was active and not superseded at the authorization instant. Callers: spatial pair v2
  (FACT server/services/spatial_pair_current_v2.py:131, spatial_pair_decision_v2.py:187).
- `CheckpointedShowrunnerGrantReader` additionally loads the signed checkpoint **on every call**, verifies it, and
  requires `head_for_scope(exact scope)` to equal the DB head (FACT :310-350; exact-key map FACT
  r2/governance/checkpoint_signature.py:26-27, :42). This is the rollback protection for the DB.
- Startup / activation: `verify_governance_activated_startup` validates public custody copies, schema, runs
  `GovernanceGrantRecoveryScanner.verify` (every DB chain equals the checkpoint's head set exactly, FACT
  server/services/governance_grants.py:426-477), and requires a fresh nonce proof from the host attestor over a Unix
  socket (FACT server/services/governance_startup.py:66-108; server/services/governance_attestation.py:222-276). The
  attestor side also scans the ledger with the grant key (FACT server/services/governance_operator_archive.py:119, :152).
- Retained-chain rollback check across checkpoints: a scope present in checkpoint N must exist in N+1 with a
  non-decreasing head (FACT r2/governance/archived_custody_chain.py:53-70).
- Ceremony host steps: `import_grant_event` derives the scope from `body.project_name` (FACT
  server/services/governance_ceremony.py:199-213); `next_checkpoint_body` exports every committed head
  (FACT :216-233, exporter FACT server/services/governance_grants.py:353-404).

Every application authority site builds `GrantScopeV1(user, project, principal)` and calls the reader — 21 call sites
(FACT grep: story_authoring/authority.py:72; automation_grants.py:107,136,239,302,318,374; quality_dispositions.py:152,210;
quality_package_selection.py:328,381; quality_profile_custodian.py:113,174; quality_runs.py:312,393; format_review.py:86;
spatial_review_session.py:71,117,151; spatial_pair_decision_v2.py:158,189; spatial_pair_current_v2.py:129). **INFER:**
resolving the workspace grant inside the reader changes all of them at once without touching callers.

### 1.4 Automation (run-scoped) grants

- `AutomationGrantCustodian.issue_locked` (FACT server/services/automation_grants.py:229-286): requires an interactive
  session whose `(id, sub)` equals `(user_id, issuer_id)` (`_actor`, FACT :214-220, checked twice), the issuer's
  **current parent grant for the exact project** (FACT :238-240), `now < expires_at ≤ parent expiry`, the run's
  `start_command_id`, input and policy digests (FACT :248-259), run `PENDING`; it stores parent sequence + digest
  (FACT :266-285).
- `require_issuer_locked` (FACT :288-306) is what Start/Resume/Mode/Review call; it is the only "is a Showrunner"
  check on the production side.
- `RunAutomationAuthority.require_locked` (every owner's final write, FACT :125-171) and
  `require_queued_task_current` (every queued task, FACT :100-123; caller server/production_run/execution_guard.py:58)
  re-require the **current** parent grant at `(user, project, issuer)` and its `(sequence, digest)` equal to the
  recorded one. Revoking or re-issuing the parent therefore stops every running run at its next owner write/task (INFER).
- `renew_locked` and `revoke` also require an interactive token (FACT :308-353, :355-386).
- `ProductionRunService.start` (FACT server/production_run/service.py:236-292): interactive actor → policy/target/input
  checks → `require_issuer_locked` → `ProductionRunRepository.create` and `issue_locked` in **one transaction**.
  Child grant expiry = `min(now + 24 h, parent expiry)` (FACT :115, :233). A run whose child grant expires is blocked
  `AUTOMATION_GRANT_NOT_CURRENT` by the controller (FACT server/production_run/controller.py:73-74, :184-198) and needs
  an interactive Resume to renew (FACT service.py:341-366).
- Run identity and idempotency: `run_id = uuid5(user, project, command_id)`, `uq_auto_start_command` and
  `start_replay` return the same run for the same command; one active run per project via an advisory project lock
  plus partial unique index `uq_auto_active_project` (FACT lib/db/repositories/production_runs.py:95-97, :130-211;
  lib/db/models/production_run.py:68-69, :84-91). BLOCKED_* and WAITING_REVIEW are non-terminal, so they hold the slot.

### 1.5 Story runs and Gate A

- Manual story path: brief → Human `POST /gates/greenlight` → `POST /projects/{p}/story-runs` (interactive,
  `_require_grant` → `GrantNarrativeShowrunnerAuthority.require_showrunner` exact scope) → approve → send-to-video
  (FACT server/routers/story_runs.py:133-160, :275-289, :322-410; server/story_authoring/service.py:397-403, :746-754;
  server/story_authoring/authority.py:66-80).
- `start_greenlit` requires a Gate A `GREENLIGHT` decision with the brief digest that is not superseded; it does not
  care whether the decision's authorization is Human or automatic; the run id derives from the decision id, so the
  same greenlight never starts two runs (FACT server/story_authoring/service.py:405-453, :173-174).
- Inside a production run, BRIEF greenlights automatically under the run's automation grant
  (`greenlight_automatically`, FACT server/production_run/greenlight_authority.py:23-69, using
  `GateAutomationAuthorizationV1`), STORY calls `start_greenlit` under `require_locked`
  (FACT server/production_run/story_adapter.py:205-224), STORY_COMMIT approves via `AutomaticNarrativeAuthority`,
  HANDOFF writes sources (FACT story_adapter.py:1-12). **So a production run already satisfies Gate A, approval and
  hand-off automatically; a standalone story run cannot without a Human.**
- A production run always continues past HANDOFF into film stages: `first_stage` is BRIEF or ASSET_ANALYSIS
  (FACT lib/db/repositories/production_runs.py:41-43), the next stage is `_STAGES[index+1]` until EXPORT
  (FACT r2/automation/transitions.py:126-143), and SUCCEEDED requires non-empty targets with outputs
  (FACT r2/contracts/automation.py:291-296). There is no story-only run end today.
- `RunCommand` supports `story_source ∈ {idea, project, continue, variant}` and `book_chapters`
  (FACT r2/contracts/automation.py:314-329). A continuation still needs an idea: `brief_idea` raises `IDEA_REQUIRED`
  without idea or variant profile (FACT server/story_authoring/service.py:159-170). Book progress = latest part
  committed and handed off, scanned from all story tasks of the project (FACT :333-359).
- story-sync is an interactive route that adds missing files, skips identical, reports conflicts, never overwrites
  (FACT server/routers/story_runs.py:191-239). A film run's input witness covers handed-off and source files; a change
  blocks an active run `BLOCKED_INPUT_CHANGED` (FACT server/production_run/inputs.py:72-97;
  server/production_run/controller.py:71-72).
- Film targets are `episode:N`; the UI always sends `episode:1..N` (FACT
  frontend/src/features/production-run/ui/ProductionRunPanel.tsx:219), capped by `policy.max_target_episodes`
  (FACT server/production_run/service.py:251-252).
- A DB-scan scheduler with leases already exists for production runs (FACT server/production_run/scheduler.py:21-60).

---

## 2. Workspace-wide grant

### 2.1 Options

| | A1 `project_name:"*"` in v1 | A2 reserved name in v1 (`@workspace`) | **A3 v2 event, explicit workspace scope** | A4 separate grant kind + checkpoint v2 |
|---|---|---|---|---|
| Signed meaning | wildcard in an identity field; v1 parser rejects it (showrunner_grant.py:57-62) | broad meaning lives in code, not in the signed bytes | explicit `scope:"WORKSPACE"` in a new schema id | explicit |
| Event/verify code | change validators, every exact match | none in contract | new body model + parser branch + `_matches_scope` | new contract, tables, verifier |
| Ledger tables | none | none | none (sentinel key, see below) | new tables + migration |
| Checkpoint | v1 validator rejects `*` → v2 needed | unchanged | unchanged (sentinel head is an ordinary v1 head) | new checkpoint schema; archived-chain and high-water code change |
| Image rollback after import | old image rejects → governance unavailable | old image sees a grant for a project that cannot exist (safe) | old image rejects the v2 row at startup scan → governance unavailable (fail-closed) | same as A3 |
| ADR-0103 "no wildcard" | violates literally | evades | amends explicitly | amends explicitly |

Sentinel key: `@workspace` can never be a project name, since `PROJECT_NAME_PATTERN = ^[A-Za-z0-9-]+$` (FACT
lib/project_manager.py:97, :315-320), and the ledger column has no pattern (FACT lib/db/models/governance_grant.py:45).

### 2.2 Recommendation: A3

1. **Contract.** Add `governance.showrunner_grant_event.v2` with the v1 fields minus `project_name`, plus
   `scope: Literal["WORKSPACE"]`. `parse_grant_event` dispatches on `schema`; v1 bytes and digests are untouched.
   The domain-separated schema id means a v2 signature can never be read as a v1 grant and vice versa.
2. **Ledger key.** Store a v2 chain under `project_name = "@workspace"` in the existing tables; `GrantScopeV1` gains
   a `workspace(user, principal)` constructor; `_matches_scope` compares v2 events only against the sentinel key and
   v1 events only against a pattern-valid project. No table migration (INFER). Optional hardening migration: a CHECK
   `project_name ~ '^[A-Za-z0-9-]+$' OR project_name = '@workspace'` on both tables (verify that existing rows pass).
3. **Resolution in the reader (one place).** `require_current_locked(scope)` with a project scope:
   - refuse any caller scope whose project is not pattern-valid (a request for project `@workspace` must never
     select the workspace chain by exact match);
   - lock in fixed order **exact head, then workspace head** (importer locks one head; scanner/exporter hold the
     exclusive fence, FACT server/services/governance_grant_fence.py:16-40), so no new deadlock cycle (INFER);
   - exact chain present and current ISSUE active → use it (existing behaviour byte-for-byte);
   - exact chain head is a **REVOKE → deny** (an explicit per-project revoke wins over the workspace grant; fail-closed);
   - exact chain absent, or its ISSUE expired/not yet valid → use the workspace chain if its current ISSUE is active;
   - return `ResolvedGrant(event, chain_key)` so callers that bind the parent can record which chain they used.
4. **Checkpoint check covers both chains it consulted.** `CheckpointedShowrunnerGrantReader` must require
   `head_for_scope(exact)` to equal the DB exact head **or both be absent**, and `head_for_scope(@workspace)` to equal
   the workspace head. Without the first, deleting an exact-chain REVOKE from the DB would silently fall through to
   the workspace grant (INFER — this is the main new rollback vector).
5. **Historical replay.** `require_historical_issue_locked` looks the digest up in the exact chain, then the
   workspace chain, and checks supersession inside the chain it found; it also applies the explicit-REVOKE rule.
6. **Scanner/exporter/archived chain.** Unchanged logic: the sentinel head is one more ordinary head; they must use
   the new parser so v2 rows verify. The checkpoint shrinks from one head per project to one per user (benefit: the
   10 000-head cap, FACT grant_checkpoint.py:20, and per-call checkpoint load/verify cost, FACT governance_grants.py:332).
7. **Ceremony.** `sign_grant_event(scope="WORKSPACE")` and CLI `sign-event --workspace` (mutually exclusive with
   `--project`); `import_grant_event` derives the scope from the body kind (today from `body.project_name`, FACT
   server/services/governance_ceremony.py:211-212). Issue → import → `next-body` → offline `sign-checkpoint` →
   `publish`, exactly the existing sequence.
8. **Revocation / renewal.** A signed v2 REVOKE appends to the workspace chain; every reader call then denies for
   projects without their own active grant; every running automation child bound to it stops at its next owner
   write/task (FACT automation_grants.py:106-123, :135-161). Renewal = REVOKE+ISSUE (alternation rule), which moves the
   head; see §3 for how autopilot reacts.
9. **Deployment order (fail-closed).** Ship the image with v2 parsing in both app and attestor, re-approve the pinned
   image (ADR-0103 activation), only then import the first v2 event. After import, rolling back to an image without
   v2 makes startup refuse governance for **all** projects (scan fails on the v2 row). The rollback runbook must say so.

Backward compatibility: v1 events, v1 checkpoints, stored digests, existing per-project grants and every replay
reference keep their bytes and behaviour; precedence uses the exact chain first (INFER from the design above).

---

## 3. Standing autopilot delegation

### 3.1 Options

- **B1 project-level long-lived automation grant** (one child grant per project spanning many runs): breaks
  ADR-0111's run-scoped child bound to an exact Start command, input and policy (FACT 0111:17). Rejected.
- **B2 stored interactive token / service JWT for the scheduler**: ADR-0103 and ADR-0111 forbid deriving the
  entitlement from API keys or sessions (FACT 0103:13, 0111:15). Rejected.
- **B3 Autopilot delegation record** — an append-only, versioned, digested record per project created only by an
  interactive Showrunner, consumed by an in-process scheduler that issues each run's automation grant through a new
  custodian entry. Recommended.
- **B4 offline-signed autopilot event per project**: a ceremony per project contradicts the sponsor's "one ceremony".
  A variant — an explicit `standing_start` entitlement inside the signed v2 workspace grant — would make the
  ceremony state that standing starts are allowed, but would also stop per-project v1 grants from enabling autopilot.
  It is an option for the sponsor, not recommended by default.

### 3.2 Recommendation: B3

**Record** `r2_autopilot_delegations` (append-only, PK `(user_id, project_name, version)`, head table like the grant
ledger): `state ENABLED|DISABLED`, `kind story|film`, `issuer_principal` (`actor.sub`), `parent_chain_key` (project or
`@workspace`), `parent_sequence`, `parent_event_digest`, `mode` (AUTO), `policy_digest` (frozen at enable),
story params (`book_chapters` and the part-1 idea for a project without part 1; a fixed continuation direction text,
since a continuation needs an idea — FACT service.py:167-169), film params (episodes per run ≤
`max_target_episodes`), `enable_command_id`, `created_at` (DB time), and `delegation_digest` = canonical digest of the
body. A separate mutable cursor row holds `halted_reason`, `last_run_id`, `due_at`, lease — never part of the digest.

**Enable** `POST /projects/{p}/autopilot` (interactive): `require_issuer_locked` (resolves workspace or project
grant) → lock delegation head → append ENABLED version bound to the resolved parent and the current policy digest.
**Disable** (interactive, any session of the user, like Pause/Cancel, FACT service.py:3-5) → append DISABLED; stops
future starts only; "stop now" can additionally Pause the active autopilot run through the existing control path.

**Custodian entries without a token** (new, narrowly typed, only callable with a locked delegation):
`issue_delegated_locked(session, delegation, request)` and `renew_delegated_locked(...)`. They replace `_actor(token)`
with: delegation head locked, `ENABLED`, its digest equals the one the scheduler read, `issuer_principal ==
request.issuer_id`, `request.command_id` is the deterministic autopilot command, `request.policy_digest ==
delegation.policy_digest`, and the parent chain recorded in the delegation is current with **the same sequence and
digest** (a re-issue or revoke of the parent therefore halts autopilot). Lock order extends ADR-0111: owner heads →
signed parent (exact, then workspace) → delegation head → project lock/run → child grant (INFER; must be written
into the ADR). The child grant records `parent_chain_key` (new optional field, excluded at its default so existing
grant JSON is unchanged); `RunAutomationAuthority` re-requires that exact chain (plus the explicit-REVOKE rule)
instead of re-resolving, so issuing a per-project grant later does not strand runs bound to the workspace parent.
Expiry: delegated child grants expire at the parent's expiry (sponsor: no expiry beyond the grant's own) instead of
the 24 h TTL (FACT service.py:115, :233), which otherwise blocks long autopilot runs and needs interactive Resume.

**Gate A and approvals**: unchanged — autopilot only starts *production runs*; their BRIEF/STORY_COMMIT/HANDOFF
owners already greenlight and approve under the run's child grant (FACT greenlight_authority.py:23-69,
story_adapter.py:1-12). Automatic decisions keep `RUN_AUTOMATION` provenance, never Human (ADR-0111).

**Story-only production run** (needed for story projects): add `RunCommand.end_stage: Literal["EXPORT","HANDOFF"]`
(excluded at default, so stored command digests are unchanged — the same pattern as `story_source`, FACT
automation.py:320-329), carry it into `RunSnapshot`, make `transitions` finish SUCCEEDED after HANDOFF, relax the
SUCCEEDED-needs-targets validator for HANDOFF-ending runs (FACT automation.py:291-296), and restrict the child
grant's operations to BRIEF..HANDOFF. A story project then runs: part 1 = `story_source="idea"`, `book_chapters`;
part k+1 = `story_source="continue"` with the delegation's continuation direction.

**Scheduler** `AutopilotScheduler`, in the app process beside `ProductionScheduler` (same DB-scan + lease pattern,
FACT scheduler.py:21-60): claim due ENABLED cursors (`FOR UPDATE SKIP LOCKED`), compute the next action, start through
`ProductionRunService.start_delegated` (same validation as `start` minus the token), one transaction for run + child
grant. One `custodian.activate()` (attestor exchange + full scan) per scan batch, not per project (INFER: activation
does a socket exchange and full ledger scan, FACT automation_grants.py:190-207, governance_startup.py:66-104).

- **Idempotency**: command id `autopilot:{delegation_digest}:{ordinal}` (story: part number; film: story-part
  ordinal). A crash after commit replays to the same run (`start_replay`, `uq_auto_start_command`); a second
  scheduler instance hits `uq_auto_active_project` / the project advisory lock (FACT production_runs.py:135-153).
- **Ordering**: story part k+1 only when `book_progress.parts_done == k`, the last autopilot run SUCCEEDED, and no
  unfinished manual story task exists in the project (ADR-0116 §9 race, `CANON_BASE_MOVED`). Film: only when the
  linked story's handed-off parts exceed what the film holds **and the film has no active run** (a sync during a
  run would block it `BLOCKED_INPUT_CHANGED`, FACT controller.py:71-72); sync first (extract the route body into
  a service function `sync_linked_story(projects, film, user_id)`; it is already idempotent: add / skip / report),
  any `conflicts` halts with `STORY_SYNC_CONFLICT`, then start a film run (`story_source="project"`) for the new
  episode targets.
- **Stopping**: any non-SUCCEEDED outcome (BLOCKED_*, WAITING_REVIEW, FAILED*, CANCELLED) halts the cursor and puts
  it in `GET /operations` "Needs you"; after the operator resolves and the run succeeds, the next scan continues.
  Parent revoked/expired/re-issued, delegation disabled, policy moved → halt with a reason; bulk "re-enable autopilot"
  (interactive, one command, appends new versions bound to the new parent) handles yearly renewal.
- **Auto-create films for finished stories**: an interactive command recorded as a durable batch row (command id,
  digest, actor, parent). The batch walks story projects whose book is complete (or short story committed and handed
  off) and that no film links (index counts films per story, ADR-0122 §2), in story creation order, creating a film
  named deterministically from the story (`film-<story>`), linking `story_project`, syncing, and enabling film
  autopilot bound to the batch command. Restart resumes from the batch cursor; an existing linked film is skipped.

---

## 4. Phased plan

| Phase | Change (modules/contracts) | Tests |
|---|---|---|
| P0 | ADR-0123 workspace grants (amends 0103 §1); ADR-0124 autopilot standing delegation (amends 0116 §8, 0122 "not adopted", extends 0111 lock order); CONTEXT.md terms | — |
| P1 | `r2/contracts/showrunner_grant.py` v2 body + dispatch; `r2/governance/grant_transition.py` scope kinds; `r2/governance/ceremony.py` + `scripts/r2/governance_ceremony.py --workspace`; `server/services/governance_grants.py` resolution, dual checkpoint check, historical lookup; `server/services/governance_ceremony.py` import scope | canonical v2 vectors; v1 vectors byte-identical; v1/v2 cross-schema signature reuse refused; sentinel never matched by a project scope; precedence table (exact active / exact REVOKE deny / exact expired → workspace / none); checkpoint missing-exact-but-DB-has / DB-deleted-REVOKE refused; scanner/exporter/archived-chain with mixed heads; adversarial PG: concurrent import vs reader, lock order no deadlock |
| P2 | `r2/contracts/automation.py` `AutomationGrant.parent_chain_key` (excluded at default); `server/services/automation_grants.py` chain-bound re-require; `issue_delegated_locked`/`renew_delegated_locked` | old grant JSON parses and digests unchanged; run bound to workspace survives a later per-project ISSUE; parent REVOKE stops owner write and queued task |
| P3 | story-only run: `RunCommand.end_stage`, `RunSnapshot`, `r2/automation/transitions.py`, `lib/db/repositories/production_runs.py`, story-project policy/preflight | old command digests unchanged; HANDOFF → SUCCEEDED; film stages never dispatched; continue part k+1 from book state |
| P4 | `lib/db/models` + alembic migration for delegations/cursors/batches; `server/services/autopilot.py`; routes enable/disable/re-enable/auto-create; operations read; frontend toggle + i18n all languages | enable needs interactive + current grant; disable by any interactive session; digest stable; append-only |
| P5 | `server/production_run/autopilot_scheduler.py`; `ProductionRunService.start_delegated`; story-sync service extraction | crash between commit and ack replays; two schedulers → one run; ordering; halt on each non-success; sync conflict halts; sync never during an active film run |
| P6 | auto-create films batch | deterministic names; resume after crash; skip already-linked; order |

Verify on a **disposable PostgreSQL** (never the staging DB): lock ordering and deadlock under concurrent
import/reader/scheduler; `clock_timestamp()` expiry boundaries; `SKIP LOCKED` claims with two schedulers; partial
unique index behaviour; migration up/down with existing v1 rows; startup scan with mixed v1/v2 chains; the DB-rollback
attack (delete exact REVOKE rows) refused by the checkpoint. Note the asyncpg cross-loop rule for router tests.

Verify in the **ceremony rehearsal** (throwaway keys, throwaway archive): sign v2 ISSUE → import → next-body → sign
checkpoint → publish → activated startup with attestor; v2 REVOKE + re-ISSUE (renewal) and its effect on autopilot;
coexistence with an existing per-project chain; image rollback to a v1-only build refuses governance (expected); restore
drill with the high-water record.

## 5. Risks

1. **Blast radius of one key event**: a single signed v2 ISSUE authorizes every project and every future project;
   a leaked grant key or a mis-signed event is workspace-wide. Mitigation: short expiry, rehearsal, revocation drill.
2. **New rollback vector**: falling through from an exact chain to the workspace chain must be checkpoint-checked
   for both chains (§2.2 item 4).
3. **Image rollback after v2 import** makes governance unavailable for all projects (fail-closed but total).
4. **Unbounded spend**: the sponsor chose no cap beyond each run's caps; thousands of autopilot projects can spend in
   parallel. Only pacing (scan batch size, resource admission) limits it.
5. **Renewal halts everything**: REVOKE+ISSUE moves every parent; all delegations halt until the bulk re-enable.
6. **Story-only run contract change** touches the run state machine and SUCCEEDED invariant.
7. **Film sync vs active run**: syncing during a run blocks it; the scheduler must serialize.
8. **Book progress cost**: `book_progress` scans all story tasks of a project per call (FACT service.py:337-359);
   per-scan use over thousands of projects needs a cursor/cached progress.
9. Checkpoint load + Ed25519 verify on every reader call (FACT governance_grants.py:332) multiplies with autopilot
   volume; measure.

## 6. Unknowns

- UNKNOWN whether the story-project policy/preflight passes without film routes (start_offer/readiness resolve a full
  production policy, FACT service.py:147-164, :209-212).
- UNKNOWN how EPISODE_PLAN/ADAPTATION behave for a second film run whose targets are new episodes (`episode:6..`)
  of a film that already has episodes (FACT text_adapter.py:319-321, :336-367 only shows target→episode mapping);
  and how many episodes a book part yields relative to `max_target_episodes`.
- UNKNOWN whether the attestor runs from the same pinned image as the app in production (governs the deploy order).
- UNKNOWN whether any existing grant ledger row has a project name outside the pattern (affects the optional CHECK).
- UNKNOWN sponsor preference on explicit per-project REVOKE overriding the workspace grant (recommended: yes).
- UNKNOWN whether the continuation direction for autopilot parts should be a fixed text or per-part generated
  (ADR-0116 §8 treats it as the author's direction).
