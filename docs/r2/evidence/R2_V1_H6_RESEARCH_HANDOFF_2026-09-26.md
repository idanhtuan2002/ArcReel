# R2 V1 H6 research handoff — 2026-09-26

## V1-01 task gate and V1-02 staging correction — 2026-09-27

Live clean HEAD before this checkpoint edit was `cda38fcd` on
`feat/r2-m7e-v1-lineage`. Commit `af30ac6e` added presentation/checkpoint
field candidates; `cda38fcd` corrected the staging rule after checking the
actual submitted-job resume reader. A valid checkpoint plus provider job
allows provider polling without reopening staged inputs. The V1-01 draft now
proposes that all `queued`, `running` and `cancelling` tasks block a quiescent
exact capture pending a reviewed fence. A later failed-to-running
artifact-download retry is a separate DB writer that must join that fence.
These are source-backed candidate rules, not H6 acceptance or production code.

The isolated checkpoint-state test passed (1); `git diff --check` and the
M7 real-baseline scope test passed on clean `cda38fcd` (1). The isolated
reference-resume test did not finish under a bounded run; pytest-timeout
marked it failed, and the run was interrupted during teardown. Do not count
that test or the full backend suite as green. No source code, schema, capture
or restore adapter was changed. On resume inspect live Git, complete the
task-writer/fence inventory and resolve the still-open lifecycle, file
authority, custody, sponsor and independent review gates. Preserve unrelated
root-checkout work. No license analysis is in scope.

## V1-02 field-map continuation — 2026-09-27

Live clean HEAD before this checkpoint edit: `d1339025` on
`feat/r2-m7e-v1-lineage`. Commits `dda1a5eb` and `d1339025` refined the
**existing** [file-authority matrix](../../research/2026-09-26-r2-m7-h6-project-inventory-authority.md),
instead of creating a second map. The grid slice records raw unversioned
states, pending/old composite paths, frame paths surviving replacement and
fixture obligations. The version-history slice records absent/present index,
all selected/unselected/rejected snapshots, and a separate identity check
beyond the existing bucket validator. A disposable probe showed that
`is_managed_snapshot_path()` accepts another resource's same-bucket filename;
another showed that `add_version()` can persist a reference without source
bytes. Both are ordinary API behaviors, not production H6 acceptance.

The global-asset follow-up found that `AssetRepository.list()` is paginated,
`list_derivatives_by_asset_ids()` covers only supplied IDs, and
`CandidateObjectRepository.list_all()` covers one user/project scope. Reuse
these readers only after a fenced complete DB-row domain is established;
V1-03 transaction/query design remains open. Fresh targeted grid, census and
version-manager tests passed (`45 passed`); `git diff --check` passed before
each scoped commit. No production classifier, capture adapter, restore code,
schema migration or provider call was added. The H6 design remains draft and
needs V1-01 liveness, V1-02 reference-authority, deployment identity, custody,
sponsor and independent review gates before implementation/acceptance. On
resume, inspect live Git status and continue the remaining field-map cases in
the same matrix; preserve unrelated root-checkout work.

## Continuation checkpoint — 2026-09-27

The live M7-D worktree was clean at `b586b3c3b22cb411682aa8f5f3dd291232f0e83e`
before this handoff edit. Later Git state must be read live rather than inferred
from this paragraph. `b586b3c3` adds the legacy bootstrap/deployment-identity
matrix to the [lifecycle protocol note](../../research/2026-09-27-r2-m7-h6-project-lifecycle-protocol-options.md).
Earlier `6286b9e8` records the isolated PostgreSQL 18.6 two-connection
admission/deletion/rollback probe; `053546b1` records the bounded Task,
attempt and backup writer survey. The probe tested scratch SQL ordering, not
repository integration. The graph generation was `2026-09-18T10:57:40Z` from
the separate M7 worktree; current source was read where coverage was stale or
missing. No production schema, backup, restore or lifecycle adapter was added.

The bootstrap matrix identifies incomplete HTTP creation, older/migrating
metadata, DB-only historical names, conflicting users, hidden swap/import
siblings and retained retired names as distinct review cases. The current
`RecoveryConfigV1` parser accepts `source_deployment_id` but does not itself
prove a runtime binding to the DB and project root. A bounded literal search
did not find such a resolver in the inspected runtime paths. Source identity,
signed pre-bootstrap census, legacy row dispositions and all-writer admission
coverage remain open V1-01 gates.

`git diff --check` passed for the research note before commit. On clean
`b586b3c3`, the real-baseline M7 scope verifier passed (`1 passed, 17
deselected`). The backend full suite remains incomplete from the earlier
interrupted unrelated render. V1-02 still needs a release-pinned classifier
for every declared reference and status-dependent pending/required rule; the
existing `r2/host_hardening/grid_reference_probe.py` only extracts raw grid
fields and grants no capture authority. Next, review V1-01 and V1-02 together
against the exact candidate HEAD, resolve their open contract gates and obtain
sponsor/independent acceptance before production H6 code. Preserve unrelated
root-checkout changes. No license analysis is in scope.

## Current checkpoint after resumed work

This section supersedes the older Git-state and resume instructions below;
they remain as the historical checkpoint from the earlier interruption.

- Worktree: `/home/anhtuan/content-production-os/.worktrees/r2-m7e-v1-lineage`.
- Branch: `feat/r2-m7e-v1-lineage`.
- Exact HEAD before this checkpoint update:
  `eaa5cc4d4ca7890aae4f927f9af97f90885a74ef`; worktree was clean.
- New commits since the older checkpoint: `c4c26ad3` (V1-01/V1-02 research),
  `30b253be` (pure H6 grid reference probe and tests), `b6d245ab`
  (presentation/staging/draft reference research), `117bdf0c` (archive
  overwrite lifecycle and other JSON evidence), `eaa5cc4d` (v5-to-v6
  whole-tree migration swap evidence). This checkpoint edit is intentionally
  separate from those verified commits.

The pure grid probe reads supplied bytes only and does not enter production
capture. Its affected host/grid tests passed (350), with repo-wide Ruff,
format, basedpyright, lint-imports and deptry checks passing at the code
packet. The new archive-overwrite tests selected for evidence passed (3);
project-migration swap-recovery tests passed (13). After the latest clean HEAD,
the real-baseline M7 scope verifier passed (1 selected test); the full scope
test module also passed (18) after `117bdf0c`. The backend full suite remains
incomplete because an earlier run was interrupted in an unrelated real-media
render; do not cite it as green.

V1-01 candidate now covers HTTP intermediate metadata, explicit deletion,
failed Agent creation rollback, archive overwrite and v5-to-v6 whole-tree
swap. V1-02 positive field map includes grid, presentations, execution
checkpoint/staging, quarantine drafts, profile manifest, migration-failure
and storyboard-failure JSON. See the two liveness notes, project inventory
note and other-JSON survey for exact evidence and limits. These are research
and **draft** decisions. No lifecycle schema, fence, capture/restore adapter,
custody profile or recovery verdict was approved or implemented.

Next work: independently review the V1-01 crash/identity matrix and V1-02
release-pinned classifier against all supported schema versions and runtime
writers; resolve the archive-overwrite and migration-swap fence semantics,
then obtain sponsor/design acceptance before production H6 implementation.
Preserve unrelated dirty work in the root checkout; inspect live Git state on
resume. No license analysis is in scope.

## Historical checkpoint from the earlier interruption

Stopped at the user's quota/session request. This is a resume checkpoint,
not H6 design approval, production-backup evidence or an implementation
acceptance receipt.

## Exact Git state

- Worktree: `/home/anhtuan/content-production-os/.worktrees/r2-m7e-v1-lineage`
- Branch: `feat/r2-m7e-v1-lineage`
- HEAD: `06edb3f8bf5ddafcc41cbf430c2660ece4b1451e`
- Committed this turn: `06edb3f8` (bounded `ApiCall.output_path` audit and
  candidate retention of regular lock-named files).
- Dirty, **not committed or accepted**:
  - `docs/research/2026-09-26-r2-m7-h6-project-inventory-authority.md`
  - `docs/superpowers/specs/2026-09-25-r2-v1-m7d-recovery-closure-design.md`
  - this handoff file.

Preserve these dirty files. Do not reset, clean, or fold them into an
unrelated packet. Re-read live `git status` and diff on resume.

## Source-backed progress and open draft

- `docs/research/2026-09-26-r2-m7-h6-api-call-output-path-audit.md` traces
  normal runtime persistence, usage display and cost classification. Within
  its stated source scope, persisted `ApiCall.output_path` is not a current
  media reader. A follow-up found the legacy SQLite-to-ORM migration copies
  that field but does not open the named file. The audit is research, not an
  approved H6 classifier.
- Source inspection found that Vertex credential uploads write JSON under
  `app_data_dir().parent/vertex_keys`, mounted separately from project data
  in production Compose; the DB stores the absolute `credentials_path`.
  Connectivity check opens it. This finding is in the dirty inventory note.
  No live secret was read and no provider call was made.
- The dirty H6 design proposes `ExternalSecretDispositionV1` and two verdict
  references. It would require signed disabled-route/no-provider evidence
  for the V1 no-paid-route profile, and reject unresolved DB credential-file
  dependencies. This is **draft**; review its field schema, trust source,
  failure code, and consistency with the isolated no-credential restore
  before adopting it. No custody product, policy or production approval was
  selected.
- The committed H6 design still says `DRAFT FOR SPONSOR REVIEW`; V1-01
  liveness/tombstone policy, V1-02 complete reference classifier, actual
  custody policy/profile and independent H6 acceptance remain open. Do not
  implement or claim `RECOVERY_VERIFIED` from these notes.

## Checks and exact resume entry

- Ran `git diff --check` on the dirty files: passed. Docs-only changes;
  no backend/frontend/full test suite was run, per scope and user request.
- On resume: inspect live status/diff and this handoff; self-review the
  external-secret research/design delta against source and existing §6
  custody semantics; refine or reject the proposal, run `git diff --check`,
  then commit only this scoped document packet if coherent. Continue V1-02
  reference/lifecycle research or seek the required sponsor design review;
  do not treat a self-review as approval or start production capture code.

## Continuation on 2026-09-26

The source review found a material omission in the initial draft: Vertex file
selection also comes from `provider_config` migration and direct
`resolve_vertex_credentials_path()` calls in the text/video backends (with an
image fallback). The draft now requires a release-pinned census of explicit DB
path references **and** implicit resolver selectors, a signed target-bound
disposition fetched from the independent recovery ledger, and disabled-route/
no-provider evidence for every selector in the proposed V1 profile. It
explicitly rejects missing selectors or a supposedly disabled enabled route.
The research and design edits remain a candidate, not a sponsor or independent
review verdict. No secret contents, live credential or provider was accessed.

Next gate: independently review the revised classifier/disposition contract
alongside V1-01 project liveness and the remaining V1-02 path/reader census.
Do not implement the capture/restore adapter or claim H6 recovery closure from
this documentation packet.
