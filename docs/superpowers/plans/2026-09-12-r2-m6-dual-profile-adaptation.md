# R2-M6 Dual-Profile Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use `superpowers:test-driven-development` for every behavior change.

**Goal:** Implement an auditable dual-profile fiction adaptation path from one
exact Canon parent through independent Western-generic and Chinese short-drama
branches, approved/locked screenplays, TakeDirector, ShotSpecV2, existing
production authority, and two Golden B slices.

**Architecture:** One shared append-only adaptation authority kernel owns branch,
map, waiver and screenplay-admission decisions. Each branch immutably binds one
versioned profile pack. Pure profile evaluators emit typed non-authoritative
sidecars. TakeDirector emits provider-neutral ShotSpecV2 through existing Director
and Production gates; no new Canon or Production authority is introduced.

**Tech Stack:** Python 3.12+, Pydantic v2, SQLAlchemy async ORM, Alembic,
PostgreSQL 18, SQLite migration tests, pytest/pytest-asyncio, ruff,
basedpyright, import-linter, deptry; Node 20+ only for test-time donor parity.

**Spec:**
`docs/superpowers/specs/2026-09-12-r2-m6-dual-profile-adaptation-design.md`

**ADR:**
`docs/adr/0077-dual-profile-adaptation-lineage-and-policy-evidence.md`

**Research:**
`docs/research/2026-09-12-r2-m6-dual-profile-adaptation-research.md`

## Global Constraints

- Work only in a newly prepared M6 implementation worktree rooted at the final
  accepted, clean M5C handoff SHA. Do not implement in the design branch or edit
  the existing dirty M5C worktree.
- Task 0 is a mechanical prerequisite gate. If the M5C handoff is missing,
  rejected, dirty, not an ancestor, not at Alembic head `5c7c4a0e0004`, or has
  different approved-document hashes, print `M6_PREREQUISITE_NOT_ACCEPTED`, exit
  2 and stop without creating implementation code. Do not ask for a design
  choice.
- Task 0 must prove exact Git lineage, clean state, graph project/generation and
  coverage before code work. A historical green run is not current evidence.
- The existing M5A `CanonTransactionService` remains the sole Canon writer. The
  existing M4 approval/promotion services remain the sole Production authority.
- `AdaptationAuthorityService` is the sole adaptation head writer. Evidence
  services, profiles, evaluators, donors, Directors, providers and orchestration
  cannot call repository head-mutation methods.
- `adaptation_policy` remains `STRICT | FAITHFUL | FREE | INSPIRED_BY`.
  `WESTERN_GENERIC` and `CN_SHORT_DRAMA_SHUANGWEN` are profile IDs, never fidelity
  values.
- No runtime `latest` lookup for parent Canon, profile, policy, map, screenplay,
  report, waiver, Director output, candidate or master. Every authority input is
  an exact immutable ref and content/digest binding.
- Accepted ShotSpec v1 bytes and content fingerprints are immutable. New Take
  output writes v2; v2 lineages never downgrade; unknown legacy values are not
  guessed.
- Every Huohuo- or Take-derived behavior passes all four `R2-DEC-031` gates:
  exact source manifest, branch-complete corpus, same-fixture parity, and
  exact-HEAD evidence. Donor code is test-time only unless explicitly ported.
- Use fresh short `READ COMMITTED` transactions. Exact retry precedes stale-head
  rejection. Genesis uses unique insert plus lock/reread, never absent-row
  `FOR UPDATE`. Multi-head lock order is authority family then canonical UTF-8
  key. Automatic retries are forbidden in tests and production service code.
- A currentness guard that grants a capability must fold and verify the complete
  typed authoritative chain through the same transaction-bound repository while
  holding the relevant head lock. A checker that opens another UoW is audit-only;
  FK/check constraints and pointer equality never substitute for the fold.
- Every public repository predicate contains `(user_id, project_name)`. Unknown
  and foreign IDs are indistinguishable. Global collisions disclose no owner.
- Tests use public interfaces and explicit fakes, no sleeps and no private-symbol
  monkeypatching. A zero-test selection must be broadened.
- Each behavior task follows: write failing test; run and observe the intended
  failure; implement the minimum; rerun focused tests; run affected regression;
  run `uv run python scripts/audit_tests.py --check` when tests changed; inspect
  `git status --short`; stage only owned paths; commit.
- Each checkpoint freezes a clean implementation HEAD and stops for independent
  Codex review. Claude Code must not cross a rejected or pending checkpoint.
- No test/review/commit authorizes operating migrations, provider/network calls,
  production discovery or repair, worker start, push, publish or deployment.

---

## Base Modules — Read-Only Authority Dependencies

| Existing module | Permitted use |
|---|---|
| `r2/contracts/narrative.py` | exact Canon refs, knowledge/fact contracts |
| `r2/narrative/canon_transaction.py` | immutable exact-version reads and existing Canon boundary only |
| `r2/contracts/production.py` | ShotSpec v1 compatibility and successor union |
| `r2/contracts/director.py` | normalized Director input/result contracts |
| `r2/production_intelligence/director.py` | existing TAKE routing and semantic validation seam |
| `r2/production_intelligence/admission.py` | existing readiness/currentness admission |
| `r2/production/approval_service.py` | existing candidate-to-ApprovedMaster promotion |
| `r2/contracts/fingerprints.py` | semantic versus execution fingerprint separation |
| `r2/narrative_lifecycle/authority_kernel.py` | transaction/retry/OCC pattern, not a mixed-domain authority API |

## Fixed Implementation Contract

Claude Code must use the following names, shapes, migrations and stop codes. A
different accepted-base seam is `M6_BASE_SEAM_CHANGED`; stop and return evidence
for Codex design review rather than asking the user or inventing a replacement.

### Verified existing seams

The following surfaces were verified at M5C snapshot
`2dbfad701dc11dd3127e8fefd4e6830de3c73b09`; Task 0 re-verifies them at the
accepted M5C SHA:

| Seam | Preserved public surface |
|---|---|
| `DirectorAdapter` | `director_kind: DirectorKind`; `direct(self, artifact: object) -> object` |
| `DirectorRoutingPolicy.decide` | exact profile ref, content basis, advisory values and optional Human override; adaptation routes to `TAKE` |
| `DirectorExecutionService.execute` | `routing`, `adapters`, `artifact`, `transient_retry_budget` -> `DirectorResult` |
| `DirectorSuccess` | normalized `scenes: list[SceneSpec]`, `shots: list[ShotSpec]` |
| `ProductionReadinessEvaluator.evaluate` | shot, bindings, resolved identity and exact freshness anchors |
| `compute_content_fingerprint` | shot plus semantic bindings/identity/source refs; provider data remains in the execution fingerprint |
| `ProductionApprovalService` | the only candidate-to-ApprovedMaster promotion path |

### New vocabulary and exact model shapes

All models use the repository's extra-forbid base. Evidence/decision models add
`ConfigDict(frozen=True)`. Reuse `NonEmptyStr`, `AwareDatetime`, `ContentBasis`,
`CreativeApprovalStatus`, `SceneSpec`, `Provenance` and `ProvenanceActor`.

```python
class AdaptationProfileId(StrEnum):
    WESTERN_GENERIC = "WESTERN_GENERIC"
    CN_SHORT_DRAMA_SHUANGWEN = "CN_SHORT_DRAMA_SHUANGWEN"

class AdaptationPolicy(StrEnum):
    STRICT = "STRICT"
    FAITHFUL = "FAITHFUL"
    FREE = "FREE"
    INSPIRED_BY = "INSPIRED_BY"

class AdaptationOperation(StrEnum):
    PRESERVE = "PRESERVE"
    EXTERNALIZE = "EXTERNALIZE"
    CONDENSE = "CONDENSE"
    COMBINE = "COMBINE"
    SPLIT = "SPLIT"
    OMIT = "OMIT"
    REORDER = "REORDER"
    REFRAME_POV = "REFRAME_POV"
    MODIFY_FOR_MEDIUM = "MODIFY_FOR_MEDIUM"

class FindingDisposition(StrEnum):
    INTEGRITY_BLOCK = "INTEGRITY_BLOCK"
    PROFILE_BLOCK = "PROFILE_BLOCK"
    ADVISORY = "ADVISORY"
    NOT_APPLICABLE = "NOT_APPLICABLE"

class AdaptationAuthorityFamily(StrEnum):
    MAP_APPROVAL = "MAP_APPROVAL"
    PROFILE_WAIVER = "PROFILE_WAIVER"
    SCREENPLAY_ADMISSION = "SCREENPLAY_ADMISSION"

class AdaptationDecisionAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    WAIVE = "WAIVE"
    DENY_WAIVER = "DENY_WAIVER"
    ADMIT = "ADMIT"
    REVOKE = "REVOKE"
```

Exact immutable refs and content models:

```python
class ArtifactVersionRef(R2ContractModel):
    artifact_id: NonEmptyStr
    version: int = Field(ge=1)
    content_hash: NonEmptyStr

class AdaptationProfileRef(R2ContractModel):
    profile_id: AdaptationProfileId
    profile_version: NonEmptyStr
    policy_pack_digest: NonEmptyStr

class DecisionRef(R2ContractModel):
    decision_id: NonEmptyStr
    decision_digest: NonEmptyStr

class AdaptationBranchV2(R2ContractModel):
    branch_id: NonEmptyStr
    schema_version: Literal["r2-adaptation-branch-v2"]
    version: int = Field(ge=1)
    parent_branch_id: NonEmptyStr | None
    parent_canon_version: ArtifactVersionRef
    medium: NonEmptyStr
    adaptation_policy: AdaptationPolicy
    overlay_version: int = Field(ge=1)
    profile_ref: AdaptationProfileRef
    created_at: AwareDatetime
    created_by: NonEmptyStr

class AdaptationMapEntry(R2ContractModel):
    entry_id: NonEmptyStr
    source_refs: list[NonEmptyStr] = Field(min_length=1)
    target_refs: list[NonEmptyStr] = Field(min_length=1)
    operation: AdaptationOperation
    rationale: NonEmptyStr
    fidelity_risk: NonEmptyStr
    approval_status: CreativeApprovalStatus

class AdaptationMapV2(R2ContractModel):
    adaptation_map_id: NonEmptyStr
    schema_version: Literal["r2-adaptation-map-v2"]
    version: int = Field(ge=1)
    adaptation_branch_ref: ArtifactVersionRef
    entries: list[AdaptationMapEntry] = Field(min_length=1)
    profile_analysis_refs: list[ArtifactVersionRef] = Field(default_factory=list)
    content_hash: NonEmptyStr

class ScreenplayScene(R2ContractModel):
    scene_id: NonEmptyStr
    purpose: NonEmptyStr
    duration_target: float = Field(gt=0)
    location_ref: NonEmptyStr | None
    character_refs: list[NonEmptyStr]
    source_mapping_refs: list[NonEmptyStr] = Field(min_length=1)
    dramatic_text: NonEmptyStr

class ScreenplayArtifactV2(R2ContractModel):
    screenplay_id: NonEmptyStr
    schema_version: Literal["r2-screenplay-artifact-v2"]
    version: int = Field(ge=1)
    adaptation_branch_ref: ArtifactVersionRef
    content_basis: ContentBasis
    scenes: list[ScreenplayScene] = Field(min_length=1)
    characters: list[NonEmptyStr] = Field(min_length=1)
    source_mapping_refs: list[NonEmptyStr] = Field(min_length=1)
    approval_status: CreativeApprovalStatus
    locked_for_direction: bool
    content_hash: NonEmptyStr
    adaptation_map_ref: ArtifactVersionRef
    profile_analysis_refs: list[ArtifactVersionRef] = Field(default_factory=list)
```

`approval_status` and `locked_for_direction` are content-state claims, not
capabilities. Evidence service appends proposal version N with
`locked_for_direction=false`. Admission receives that exact proposal plus a deep
snapshot of version N+1 of the same screenplay ID. N+1 must be
`approval_status=APPROVED` and `locked_for_direction=true`; other semantic edits
must already be present in the proposal or validation fails. One transaction
rehashes and appends immutable N+1, appends its admission decision, and advances
the head. The exact reader returns N+1 only while the complete admission chain
is current. No row is mutated and no approval-without-lock state is usable.

Selectors are exactly `r2-adaptation-branch-v2`, `r2-adaptation-map-v2`,
`r2-screenplay-artifact-v2`, `r2-western-drama-analysis-v1`,
`r2-shuangwen-analysis-v1`, and `r2-profile-evaluation-report-v1`. Content hashes
use `sha256:<64 lowercase hex>` and cover every semantic field except
`created_at`, storage IDs and rendered messages.

`ProfileFinding` fields are `finding_id`, `rule_id`, `rule_version`,
`disposition`, `applicability`, `severity`, `target_path`, `source_span`,
`evidence_refs`, and `message_params`. `WesternDramaAnalysis` contains format
findings, rubric observations and evidence locations. `ShuangwenAnalysis`
contains chapter/index scope, `hen/shuang/ji/pan` evidence, optional
`shuang_type`, and findings. `ProfileEvaluationReport` binds the exact artifact
hash, profile ref, evaluator version, sidecar ref/digest, ordered findings,
report digest and creation time.

The six Shuangwen values are exactly `硬撕 | 拒签 | 揭穿假账 | 示弱钓鱼 |
当众对赌 | 借力第三方`. Chapters 1–8 require all four `恨/爽/急/盼` fields,
a recognized type and the pinned stakes check; chapter 9+ records those rules as
`NOT_APPLICABLE`.

ShotSpecV2 preserves all v1 semantic fields and adds seven `shot_size`, eight
`camera_angle`, and fourteen `camera_movement` values from pinned
`XucroYuri/take@47c17216b5ad74ee7dd376e8508266e29aefae2c`. Task 4's
source runner is the executable enum oracle; lifecycle/provider/rendered-asset
enums are excluded.

### Commands, decisions, heads and public authority

```python
class MapApprovalCommand(R2ContractModel):
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    decision_id: NonEmptyStr
    branch_id: NonEmptyStr
    map_ref: ArtifactVersionRef
    profile_ref: AdaptationProfileRef
    relied_report_refs: list[DecisionRef]
    expected_predecessor_id: NonEmptyStr | None
    action: Literal[AdaptationDecisionAction.APPROVE, AdaptationDecisionAction.REJECT]

class ProfileWaiverCommand(R2ContractModel):
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    decision_id: NonEmptyStr
    branch_id: NonEmptyStr
    artifact_ref: ArtifactVersionRef
    profile_ref: AdaptationProfileRef
    report_ref: DecisionRef
    finding_ids: list[NonEmptyStr] = Field(min_length=1)
    rule_versions: list[NonEmptyStr] = Field(min_length=1)
    rationale: NonEmptyStr
    expected_predecessor_id: NonEmptyStr | None
    action: Literal[AdaptationDecisionAction.WAIVE, AdaptationDecisionAction.DENY_WAIVER]

class ScreenplayAdmissionCommand(R2ContractModel):
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    decision_id: NonEmptyStr
    branch_id: NonEmptyStr
    proposal_ref: ArtifactVersionRef
    admitted_screenplay: ScreenplayArtifactV2
    profile_ref: AdaptationProfileRef
    effective_map_approval_ref: DecisionRef
    report_refs: list[DecisionRef] = Field(min_length=1)
    waiver_refs: list[DecisionRef] = Field(default_factory=list)
    expected_predecessor_id: NonEmptyStr | None
    action: Literal[AdaptationDecisionAction.ADMIT, AdaptationDecisionAction.REVOKE]
```

Authorization and stored decisions have these exact shapes:

```python
class AdaptationDecisionAuthorization(R2ContractModel):
    authenticated_principal: NonEmptyStr
    authority_role: Literal["HUMAN_SHOWRUNNER"]
    action: AdaptationDecisionAction
    command_identity_hash: NonEmptyStr
    approval_receipt: NonEmptyStr
    authorized_at: AwareDatetime

class MapApprovalDecision(R2ContractModel):
    decision_kind: Literal["MAP_APPROVAL"] = "MAP_APPROVAL"
    command: MapApprovalCommand
    authorization: AdaptationDecisionAuthorization
    sequence: int = Field(ge=1)
    decision_digest: NonEmptyStr
    created_at: AwareDatetime

class ProfileWaiverDecision(R2ContractModel):
    decision_kind: Literal["PROFILE_WAIVER"] = "PROFILE_WAIVER"
    command: ProfileWaiverCommand
    authorization: AdaptationDecisionAuthorization
    sequence: int = Field(ge=1)
    decision_digest: NonEmptyStr
    created_at: AwareDatetime

class ScreenplayAdmissionDecision(R2ContractModel):
    decision_kind: Literal["SCREENPLAY_ADMISSION"] = "SCREENPLAY_ADMISSION"
    command: ScreenplayAdmissionCommand
    authorization: AdaptationDecisionAuthorization
    sequence: int = Field(ge=1)
    decision_digest: NonEmptyStr
    created_at: AwareDatetime

AdaptationDecision = Annotated[
    MapApprovalDecision | ProfileWaiverDecision | ScreenplayAdmissionDecision,
    Field(discriminator="decision_kind"),
]
```

```python
class AdaptationHead(R2ContractModel):
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    family: AdaptationAuthorityFamily
    head_key: NonEmptyStr
    latest_decision_id: NonEmptyStr
    effective_decision_id: NonEmptyStr | None
    selected_artifact_ref: ArtifactVersionRef | None
    generation: int = Field(ge=1)

class AdaptationDecisionReceipt(R2ContractModel):
    decision_ref: DecisionRef
    family: AdaptationAuthorityFamily
    head_key: NonEmptyStr
    outcome: Literal["RECORDED", "EXACT_RETRY"]
    current_at_return: bool

class AdmittedScreenplayRef(R2ContractModel):
    screenplay_ref: ArtifactVersionRef
    admission_ref: DecisionRef
    profile_ref: AdaptationProfileRef

class AdaptationShowrunnerAuthorityPort(Protocol):
    async def authorize(self, *, authenticated_principal: str,
                        action: AdaptationDecisionAction,
                        command_identity_hash: str) -> AdaptationDecisionAuthorization: ...

class AdaptationAuthorityRepositoryPort(Protocol):
    async def get_decision_by_id(self, *, user_id: str, project_name: str,
                                 decision_id: str) -> AdaptationDecision | None: ...
    async def prepare_or_lock_head(self, *, user_id: str, project_name: str,
                                   family: AdaptationAuthorityFamily,
                                   head_key: str) -> AdaptationHead | None: ...
    async def list_decisions_for_locked_head(self, *, user_id: str,
                                             project_name: str,
                                             family: AdaptationAuthorityFamily,
                                             head_key: str) -> Sequence[AdaptationDecision]: ...
    async def append_decision_and_advance_head(
        self, decision: AdaptationDecision, expected_generation: int
    ) -> None: ...

def fold_adaptation_head(decisions: Sequence[AdaptationDecision]) -> AdaptationHead: ...

async def verify_locked_adaptation_selection(
    repository: AdaptationAuthorityRepositoryPort, *, locked_head: AdaptationHead,
    expected_decision_id: str, expected_artifact_ref: ArtifactVersionRef,
) -> None: ...

class AdaptationAuthorityService:
    async def decide_map(self, command: MapApprovalCommand, *,
                         authenticated_principal: str) -> AdaptationDecisionReceipt: ...
    async def decide_waiver(self, command: ProfileWaiverCommand, *,
                            authenticated_principal: str) -> AdaptationDecisionReceipt: ...
    async def admit_screenplay_for_direction(
        self, command: ScreenplayAdmissionCommand, *, authenticated_principal: str
    ) -> AdaptationDecisionReceipt: ...
```

Task-local support records are not public domain contracts, but their shapes are
also fixed: `VerificationResult(checks: tuple[VerificationCheck, ...], ok: bool,
error_code: str | None)`; `ProfilePack(ref, evaluator_version, rules,
canonical_bytes)`; `ShuangwenSourceScope(chapter_start, chapter_end,
source_refs)`; `ShuangwenFields(book_fields, chapter_fields)`;
`CanonFixture(canon_ref, characters, locations, state_changes,
knowledge_constraints)`; and `GoldenBSliceEvidence(profile_ref, branch_ref,
map_decision_ref, report_refs, waiver_refs, admission_ref, shot_refs,
master_refs, assembly_ref, duration_seconds)`.

Stable public errors are `M6_PREREQUISITE_NOT_ACCEPTED`,
`M6_BASE_SEAM_CHANGED`, `ADAPTATION_NOT_FOUND`,
`ADAPTATION_IDENTITY_CONFLICT`, `ADAPTATION_STALE_HEAD`,
`ADAPTATION_STALE_DEPENDENCY`, `ADAPTATION_AUTHORITY_DENIED`,
`ADAPTATION_AUTHORITY_INTEGRITY`, `ADAPTATION_PROFILE_MISMATCH`,
`ADAPTATION_POLICY_DIGEST_MISMATCH`, `ADAPTATION_BLOCKING_FINDING`,
`ADAPTATION_WAIVER_NOT_APPLICABLE`, `SCREENPLAY_NOT_APPROVED`,
`SCREENPLAY_NOT_LOCKED`, and `SHOT_SPEC_MANUAL_MAPPING_REQUIRED`.

### Linear migration chain

```text
5c7c4a0e0004
  -> 6a7c4a0e0001  proposal evidence
  -> 6b7c4a0e0001  decisions, identity registry and heads
  -> 6c7c4a0e0001  evaluation attempts, sidecars, reports and waivers
  -> 6c7c4a0e0002  screenplay admission
```

No later task edits a migration frozen by an earlier checkpoint.

## Per-Task Execution Matrix

This matrix is normative and supplements each task below. “RED” is run before
implementation and must fail for the named missing behavior. “GREEN” reruns the
same selection after the minimal implementation and must pass with a non-zero
test count. Every row is followed by audit, status inspection, exact-path stage,
and the commit already named in the task.

| Task | Exact interface/output | RED expected | GREEN selection/result |
|---|---|---|---|
| 0 | `verify(checkpoint: str, repo_root: Path) -> VerificationResult`; CLI exit 2 on invalid base | missing module; prerequisite mutations rejected | `pytest tests/unit/scripts/r2/test_verify_m6_scope.py -q`; all cases pass and CLI reports all PASS |
| 1 | all fixed enums/models/union above | `r2.contracts.adaptation` import fails | `pytest tests/unit/r2/contracts/test_adaptation.py -q`; strict/frozen/round-trip cases pass |
| 2 | `canonical_adaptation_bytes`, `compute_adaptation_hash`, `compute_decision_identity_hash`, `validate_adaptation_transition` | hashing/upgrader imports fail | both Task 2 test files plus Task 1 pass; golden hashes stable |
| 3 | `ShotSpecV1`, `ShotSpecV2`, discriminated `ShotSpec`, `upgrade_shot_spec_v1` | V2 import fails while v1 vectors pass | Task 3 tests pass; v1 constants unchanged; unknown legacy is typed |
| 4 | Take runner JSON `{shot_sizes,camera_angles,camera_movements,cases}` | source/runner or enum parity fails | donor parity plus ShotSpecV2 tests pass exactly |
| 5 | scoped exact append/read repositories and `AdaptationUoW`; migration `6a...` | ORM/migration imports fail | model/repository/migration tests and isolated PostgreSQL round trip pass |
| 6 | `create_branch`, `append_map`, `append_screenplay` exact-retry evidence API | service import fails | evidence and architecture tests pass; no authority import |
| 7 | fixed authority ports, fold, locked guard and `decide_map`; migration `6b...` | authority absent/corrupt head not caught | map/concurrency/migration tests pass; corruption is integrity error |
| 8 | `ProfilePackRegistry.resolve(ref) -> ProfilePack` | registry/packs absent | exact lookup/tamper/runtime-import tests pass |
| 9 | `evaluate_western(screenplay, *, profile_pack) -> WesternDramaAnalysis` | evaluator absent | Western fixture suite passes; craft counterexamples remain advisory |
| 10 | `parse_shuangwen_fields`; `evaluate_shuangwen`; donor JSON oracle | Python port absent after donor expected JSON exists | branch-complete same-fixture parity and runtime boundary pass |
| 11 | `ProfileEvaluationService.evaluate`; `decide_waiver`; migration `6c...0001` | services/tables absent | evaluation/waiver/migration tests pass; failed attempt grants no capability |
| 12 | `admit_screenplay_for_direction`; `ApprovedScreenplayReader.get_exact_admitted`; migration `6c...0002` | admission API/table absent | race/corruption/dependency tests pass before-write |
| 13 | `TakeDirectorAdapter.direct(AdmittedScreenplayRef) -> DirectorSuccess` | adapter absent | Take and existing Director tests pass; old routes unchanged |
| 14 | dual-read consumers; selector fingerprint; unchanged readiness signature | new v2 tests fail, pre-existing v1 tests pass | all named M4/contract/Director/readiness/Production selections pass |
| 15 | `build_golden_b_canon`; `run_profile_slice` | fixture/public flow absent | two isolated 60–120s slices pass from one Canon parent |
| 16 | typed `M6MutationCase`; barrier-driven PostgreSQL race hooks | each mutation first fails intended assertion | stable owning-boundary error, no partial/sibling write, all races pass |
| 17 | final verification Markdown and machine-readable accepted handoff | handoff remains `PENDING_REVIEW` | every full gate exits 0, clean HEAD, both independent reviews approve |

Run commands shown as `pytest ...` in the matrix with
`uv run python -m pytest ...`. If a selection collects zero tests, expand to the
owning directory; zero is not GREEN.

## Checkpoint M6-A — Contracts, compatibility, and source pins

### Task 0: Freeze the accepted starting boundary

**Interfaces:** Task 0 row in the execution matrix; output and failure code are
fixed by the prerequisite contract above.

**Files:**

- Create: `docs/r2/evidence/R2_M6_STARTING_STATE.json`
- Create: `scripts/r2/verify_m6_scope.py`
- Test: `tests/unit/scripts/r2/test_verify_m6_scope.py`

- [ ] Record the accepted M5C handoff SHA, merge-base, branch, clean status,
  migration head `5c7c4a0e0004`, Python/Node/PostgreSQL tool versions,
  spec/ADR/research hashes,
  and graph project/generation in the starting-state manifest.
- [ ] Index the exact implementation worktree, query structural candidates with
  Codebase Memory Tier 2, run `check_index_coverage` for every relied-on code path,
  and direct-read all reported missed/stale ranges.
- [ ] Write failing scope-verifier tests for an unexpected implementation path,
  dirty checkpoint, mismatched document hash, wrong base SHA and missing graph
  evidence.
- [ ] Implement `verify_m6_scope.py` with per-checkpoint allowlists and no
  mutation/repair behavior.
- [ ] Run:

```bash
uv run python -m pytest tests/unit/scripts/r2/test_verify_m6_scope.py -q
uv run python scripts/audit_tests.py --check
uv run python scripts/r2/verify_m6_scope.py --checkpoint M6-A
git diff --check
```

Expected RED before implementation: import failure for
`scripts.r2.verify_m6_scope`. Expected GREEN after implementation: tests select
non-zero cases and pass; verifier prints every check as `PASS`. An unaccepted M5C
base must instead exit 2 with `M6_PREREQUISITE_NOT_ACCEPTED` and end execution.

- [ ] Commit only the three Task 0 files:

```bash
git add docs/r2/evidence/R2_M6_STARTING_STATE.json scripts/r2/verify_m6_scope.py tests/unit/scripts/r2/test_verify_m6_scope.py
git commit -m "chore(r2): pin M6 implementation boundary"
```

### Task 1: Add adaptation and profile contracts

**Interfaces:** Task 1 row and the complete model catalog above; no additional
contract name or optional extension field is permitted.

**Files:**

- Create: `r2/contracts/adaptation.py`
- Create: `r2/adaptation/__init__.py`
- Test: `tests/unit/r2/contracts/test_adaptation.py`

- [ ] Start with contract tests for strict enums, immutable models, ordered refs,
  complete `AdaptationProfileRef`, schema selectors, exact round trips, forbidden
  `latest`, profile/fidelity separation and foreign sidecar rejection.
- [ ] Add `AdaptationBranchV2`, frozen nine-operation `AdaptationMapEntry`,
  `AdaptationMapV2`, `ScreenplayArtifactV2`, profile refs, typed Western/Shuangwen
  sidecars, stable findings, evaluation reports and authority decision receipts.
- [ ] Keep `AdaptationBrief` absent. Do not add optional placeholder fields.
- [ ] Run:

```bash
uv run python -m pytest tests/unit/r2/contracts/test_adaptation.py -q
uv run ruff check r2/contracts/adaptation.py r2/adaptation tests/unit/r2/contracts/test_adaptation.py
uv run basedpyright r2/contracts/adaptation.py r2/adaptation tests/unit/r2/contracts/test_adaptation.py
uv run python scripts/audit_tests.py --check
```

Expected RED before implementation: import failure for
`r2.contracts.adaptation`. Expected GREEN: every strict enum, frozen-model,
selector, exact-ref, cross-profile and round-trip case passes with no lint, type
or audit finding.

- [ ] Commit:

```bash
git add r2/contracts/adaptation.py r2/adaptation/__init__.py tests/unit/r2/contracts/test_adaptation.py
git commit -m "feat(r2): define M6 adaptation contracts"
```

### Task 2: Add canonical serialization, hashing, and schema ratchets

**Interfaces:** Task 2 row in the execution matrix. Hash selectors and transition
rules are exact and exhaustive.

**Files:**

- Create: `r2/adaptation/hashing.py`
- Create: `r2/adaptation/schema_upgrade.py`
- Test: `tests/unit/r2/adaptation/test_hashing.py`
- Test: `tests/unit/r2/adaptation/test_schema_upgrade.py`

- [ ] Write failing golden-vector tests proving map/screenplay/profile/report hashes
  change for every semantic binding, ignore only declared audit metadata, and are
  stable under dictionary insertion order.
- [ ] Test legal genesis/v1/v2 transitions, profile change requiring a new branch,
  no v2-to-v1 downgrade and no same-ID genesis tuple substitution.
- [ ] Implement selector-dispatched canonical serializers and distinct versioned
  hash domains; reuse established canonical JSON helpers without sharing hash
  domain labels.
- [ ] RED command:

```bash
uv run python -m pytest tests/unit/r2/adaptation/test_hashing.py tests/unit/r2/adaptation/test_schema_upgrade.py -q
```

Expected RED: both new modules fail import. Implement the selector-dispatched
hashes/ratchets, then run the same command plus
`tests/unit/r2/contracts/test_adaptation.py` and the audit check. Expected GREEN:
all selected tests pass with stable golden vectors. Commit exactly the four files
with `feat(r2): add adaptation identity hashing`.

### Task 3: Introduce ShotSpecV2 without changing v1 bytes

**Interfaces:** Task 3 row in the execution matrix. The existing class becomes
the v1 arm without changing its accepted serialization or content hash.

**Files:**

- Modify: `r2/contracts/production.py`
- Modify: `r2/contracts/fingerprints.py`
- Create: `r2/production/shot_schema_upgrade.py`
- Test: `tests/unit/r2/contracts/test_shot_spec_v2.py`
- Test: `tests/unit/r2/contracts/test_fingerprints.py`
- Test: `tests/unit/r2/production/test_shot_schema_upgrade.py`

- [ ] Capture accepted v1 serialized bytes and content fingerprints as failing
  compatibility vectors before adding v2.
- [ ] Add the exact pinned Take `shot_size`, `camera_angle`, and
  `camera_movement` enums plus a discriminated `ShotSpecV1 | ShotSpecV2` union.
- [ ] Add selector-dispatched fingerprinting. Prove v1 vectors are unchanged and
  every v2 semantic field changes the content fingerprint while provider/runtime
  fields remain excluded.
- [ ] Implement exact-only legacy mapping and typed
  `SHOT_SPEC_MANUAL_MAPPING_REQUIRED`; test unknown and compound strings.
- [ ] Run all `r2/contracts`, fingerprint, registry/neutrality and existing
  Director tests; audit tests; commit exact owned paths.

Expected RED: the new V2/upgrader imports fail while the pre-existing v1 suite
passes. Expected GREEN: all named suites pass, every stored v1 byte/hash constant
is unchanged, and unknown legacy text yields
`SHOT_SPEC_MANUAL_MAPPING_REQUIRED`.

### Task 4: Pin and parity-test Take vocabulary

**Interfaces:** Task 4 row in the execution matrix; the Node runner's canonical
JSON is the only enum oracle.

**Files:**

- Modify: `docs/r2/evidence/reuse-map-2026-09-07/source-manifest.json`
- Create: `tests/donor_parity/take_shot_vocabulary_runner.mjs`
- Create: `tests/donor_parity/test_take_shot_vocabulary.py`
- Create: `tests/donor_parity/fixtures/take_shot_vocabulary/cases.json`

- [ ] Record exact Take revision, paths and SHA-256 values before copying behavior.
- [ ] Make the test-time runner load the unmodified pinned source and emit its
  exact enum/validation behavior for the shared fixture corpus.
- [ ] Compare Python v2 vocabulary against the source runner for every enum member,
  valid case, invalid case and serialization spelling.
- [ ] Run donor parity, manifest-integrity tests and audit check; commit.

Expected RED: missing source runner/fixture or exact enum mismatch. Expected
GREEN: all ordered members, valid/invalid cases and spellings match the pinned
source and the manifest SHA check passes.

### M6-A gate

- [ ] Run the full affected backend static/tooling gate and all M4 contract,
  fingerprint, Director and donor-parity tests.
- [ ] Run `uv run python scripts/r2/verify_m6_scope.py --checkpoint M6-A` and
  `git diff --check`; require a clean status.
- [ ] Record `docs/r2/evidence/R2_M6_A_REVIEW.md` only after independent Codex
  review approves the exact HEAD. Stop on any compatibility, parity or scope gap.

## Checkpoint M6-B — Branch/map evidence and Human authority

### Task 5: Add append-only persistence and migrations

**Interfaces:** Task 5 row in the execution matrix; this checkpoint contains
proposal evidence only and exposes no head writer.

**Files:**

- Create: `lib/db/models/adaptation.py`
- Create: `lib/db/repositories/adaptation.py`
- Create: `lib/db/adaptation_uow.py`
- Create: `alembic/versions/6a7c4a0e0001_add_adaptation_evidence.py`
- Modify: `lib/db/models/__init__.py`
- Test: `tests/unit/lib/db/models/test_adaptation.py`
- Test: `tests/integration/lib/db/migrations/test_alembic_adaptation.py`
- Test: `tests/integration/lib/db/repositories/test_adaptation.py`

- [ ] Test immutable version rows, scoped uniqueness, exact branch genesis tuple,
  global opaque-ID collision, FK/check constraints, append-only behavior,
  upgrade/downgrade and rollback before implementing tables.
- [ ] Store canonical payload bytes/digests alongside query columns. Heads are
  rebuildable projections; rule bodies never enter authority rows.
- [ ] Verify SQLite migration mechanics and real PostgreSQL constraint behavior.
- [ ] Migration is exactly `revision = "6a7c4a0e0001"` and
  `down_revision = "5c7c4a0e0004"`. RED is missing ORM/migration imports. GREEN
  is the three named tests plus isolated `$POSTGRES_TEST_URL` upgrade -> downgrade
  to `5c7c4a0e0004` -> upgrade, all exit 0. Run audit and commit exact paths.

### Task 6: Implement proposal evidence service

**Interfaces:** Task 6 row in the execution matrix. Exact retry returns the
original immutable evidence; no method can mutate an authority head.

**Files:**

- Create: `r2/adaptation/ports.py`
- Create: `r2/adaptation/evidence.py`
- Create: `r2/adaptation/errors.py`
- Test: `tests/integration/r2/adaptation/test_evidence_service.py`

- [ ] Write failing tests for branch genesis, map/screenplay append, exact retry,
  identity mismatch, stale parent, cross-scope IDs and failure-before-commit.
- [ ] Implement `AdaptationEvidenceService` with immutable appends only. Its ports
  expose no authority-head mutation method.
- [ ] Add import-fitness tests proving it cannot import Canon writer, Production
  approval, provider or adaptation authority internals.
- [ ] Run `uv run python -m pytest
  tests/integration/r2/adaptation/test_evidence_service.py
  tests/unit/r2/test_m6_architecture_boundaries.py -q`, then the audit check;
  require non-zero passing tests and commit the listed files only.

Expected RED: evidence service/ports fail import. Expected GREEN: named evidence
and architecture tests pass, failure-before-commit leaves no row, and dependency
scan finds no authority/provider import.

### Task 7: Implement adaptation authority kernel and map approval

**Files:**

- Create: `r2/adaptation/authority_kernel.py`
- Create: `r2/adaptation/authority.py`
- Modify: `lib/db/repositories/adaptation.py`
- Modify: `lib/db/models/adaptation.py`
- Modify: `lib/db/adaptation_uow.py`
- Create: `alembic/versions/6b7c4a0e0001_add_adaptation_authority.py`
- Test: `tests/integration/r2/adaptation/test_map_approval.py`
- Test: `tests/integration/r2/adaptation/test_concurrency.py`
- Test: `tests/unit/r2/test_m6_architecture_boundaries.py`
- Test: `tests/integration/lib/db/migrations/test_alembic_adaptation_authority.py`

**Interfaces:**

- Consumes the fixed `MapApprovalCommand` and internally obtained authorization.
  Produces the fixed fold, locked guard, receipt, repository port and
  `decide_map` surface above. Migration is exactly `revision =
  "6b7c4a0e0001"`, `down_revision = "6a7c4a0e0001"`.

- [ ] Test Human Showrunner denial, whole-map hash binding, incomplete entry
  evidence, exact retry before stale head, retry after supersession, stale policy,
  cross-profile refs, same/different-ID concurrent genesis and rollback. Add
  FK-valid corrupted-head cases for effective `REJECT`, wrong selected artifact,
  broken predecessor/generation fold and stored/rebuilt projection mismatch.
- [ ] Reuse the M5C transaction protocol as a pattern while keeping a separate
  adaptation authority type and repository surface.
- [ ] Implement one pure chain-fold/validation helper used by both the standalone
  integrity checker and repository-bound online guard. The online guard accepts
  the active repository and locked head; it must not open a nested UoW, return an
  authority token, or repair disagreement.
- [ ] Start the correction with failing public-behavior tests equivalent to:

```python
async def test_locked_guard_rejects_fk_valid_effective_reject(authority_service, corrupt_head) -> None:
    await corrupt_head(latest="d-reject", effective="d-reject", generation=2)
    with pytest.raises(AdaptationAuthorityIntegrityError):
        await authority_service.approve_map(map_approval_command(expected_effective="d-reject"))


async def test_locked_guard_rejects_decision_for_another_artifact(authority_service, corrupt_head) -> None:
    await corrupt_head(effective="d-accept-other-map")
    with pytest.raises(AdaptationAuthorityIntegrityError):
        await authority_service.approve_map(map_approval_command(map_id="map-requested"))
```
- [ ] In PostgreSQL barrier tests, prove one winner for same-head genesis, no
  cross-profile blocking for distinct branches, deterministic multi-head order,
  no partial rows and rebuild equality.
- [ ] Run `uv run python -m pytest
  tests/integration/r2/adaptation/test_map_approval.py
  tests/integration/r2/adaptation/test_concurrency.py
  tests/integration/lib/db/migrations/test_alembic_adaptation_authority.py
  tests/unit/r2/test_m6_architecture_boundaries.py -q` against the isolated
  PostgreSQL fixture, then audit; commit exact paths.

Expected RED: authority/migration imports fail and the corrupted-head tests have
no trustworthy guard. Expected GREEN: all named tests pass; each corruption is
`ADAPTATION_AUTHORITY_INTEGRITY`; races have one winner, no partial row, and
rebuild equality.

### M6-B gate

- [ ] Run all adaptation contract/persistence/authority tests plus cumulative
  M5A/M5B/M5C authority and isolation regression selected by `CONTRIBUTING.md`.
- [ ] Freeze a clean HEAD, verify scope, and add
  `docs/r2/evidence/R2_M6_B_REVIEW.md` only after independent approval.

## Checkpoint M6-C — Profile evaluation and screenplay admission

### Task 8: Add immutable profile-pack registry

**Interfaces:** `ProfilePackRegistry.resolve(ref: AdaptationProfileRef) ->
ProfilePack` and `verify_manifest_bytes(value: bytes, expected_digest: str) ->
ProfilePack`; there is no latest lookup, hot reload or executable rule DSL.

**Files:**

- Create: `r2/adaptation/profiles.py`
- Create: `r2/adaptation/policy_packs/__init__.py`
- Create: `r2/adaptation/policy_packs/western_generic_v1.json`
- Create: `r2/adaptation/policy_packs/cn_short_drama_shuangwen_v1.json`
- Test: `tests/unit/r2/adaptation/test_profiles.py`

- [ ] Test exact profile/version/digest lookup, manifest tamper, duplicate rule ID,
  invalid disposition/applicability, cross-profile rule and forbidden runtime
  latest/hot reload.
- [ ] Encode named source identities and stable rule metadata, not mutable prompts
  or Human approval data. Keep these domain policy packs separate from
  `agent_runtime_profile/`, which configures the embedded creative Agent runtime.
- [ ] Run `uv run python -m pytest
  tests/unit/r2/adaptation/test_profiles.py -q`, then audit; require non-zero
  passing tests and commit exact paths.

Expected RED: registry/packs fail import. Expected GREEN: exact lookup, unknown
version, digest tamper, duplicate/cross-profile rule and runtime-import cases all
pass.

### Task 9: Implement Western evaluator

**Interfaces:** `evaluate_western(screenplay: ScreenplayArtifactV2, *,
profile_pack: ProfilePack) -> WesternDramaAnalysis`; pure and deterministic.

**Files:**

- Create: `r2/adaptation/western_profile.py`
- Create: `tests/fixtures/r2/m6_western_profile.py`
- Test: `tests/unit/r2/adaptation/test_western_profile.py`

- [ ] Test screenplay surface failures, evidence locations, deterministic finding
  order, slow-burn/tragic/unresolved counterexamples and absence of numeric craft
  gating.
- [ ] Implement a pure evaluator: shared/surface rules may block; dramatic rubric
  concepts emit advisory observations only.
- [ ] Run `uv run python -m pytest
  tests/unit/r2/adaptation/test_western_profile.py
  tests/unit/r2/adaptation/test_profiles.py -q`, then audit and commit exact
  paths.

Expected RED: evaluator import fails. Expected GREEN: named fixtures pass,
finding order is stable, and slow-burn/tragic/unresolved craft counterexamples
remain advisory rather than numerical hard gates.

### Task 10: Port bounded Huohuo surface and prove parity

**Interfaces:** `parse_shuangwen_fields(text: str) -> ShuangwenFields` and
`evaluate_shuangwen(screenplay: ScreenplayArtifactV2, *, source_scope:
ShuangwenSourceScope, profile_pack: ProfilePack) -> ShuangwenAnalysis`; donor
runner emits canonical expected JSON for the identical corpus.

**Files:**

- Create: `r2/adaptation/shuangwen_profile.py`
- Modify: `docs/r2/evidence/reuse-map-2026-09-07/source-manifest.json`
- Create: `tests/donor_parity/huohuo_drama_fields_runner.mjs`
- Create: `tests/donor_parity/test_huohuo_drama_fields.py`
- Create: `tests/donor_parity/fixtures/huohuo_drama_fields/cases.jsonl`
- Test: `tests/unit/r2/adaptation/test_shuangwen_profile.py`

- [ ] First make the unmodified pinned TypeScript runner and branch-complete
  corpus pass independently; then write failing Python parity tests.
- [ ] Port only pure parsing, validation, six-type vocabulary and deterministic
  prompt-block behavior. Preserve exact chapter 1–8 applicability.
- [ ] Include chapter 9+, cross-episode, ambiguous type, empty semantic content,
  translated text and non-keyword fixtures. Do not invent a seconds/chapter rule.
- [ ] Prove runtime imports no donor, Node, completion/repair or persistence code.
- [ ] Run source verifier, parity, unit, architecture and audit tests; commit.

Expected RED: donor runner establishes expected JSON but Python port is absent.
Expected GREEN: branch-complete same-fixture parity passes, including chapter 9+
non-applicability, and runtime imports no donor/Node/completion code.

### Task 11: Persist reports and governed waivers

**Interfaces:** `ProfileEvaluationService.evaluate(...) ->
ProfileEvaluationReport` and fixed `AdaptationAuthorityService.decide_waiver`;
migration `revision = "6c7c4a0e0001"`, `down_revision =
"6b7c4a0e0001"`.

**Files:**

- Create: `r2/adaptation/evaluation.py`
- Modify: `r2/adaptation/authority.py`
- Modify: `lib/db/models/adaptation.py`
- Modify: `lib/db/repositories/adaptation.py`
- Modify: `lib/db/adaptation_uow.py`
- Create: `alembic/versions/6c7c4a0e0001_add_profile_reports_and_waivers.py`
- Test: `tests/integration/r2/adaptation/test_evaluation.py`
- Test: `tests/integration/r2/adaptation/test_waivers.py`
- Test: `tests/integration/lib/db/migrations/test_alembic_adaptation_profiles.py`

- [ ] Test attempt-before-work, atomic successful report bundle, deterministic
  report digest, evaluator failure, stale artifact/policy, cross-profile sidecar,
  non-waivable integrity finding and waiver laundering after semantic change.
- [ ] Implement pure evaluator ports wrapped by append-only report evidence.
- [ ] Implement Human-only waiver decisions bound to exact artifact/profile/rule/
  finding tuple and rationale; v1 applicability expires only by semantic/profile
  change or explicit supersession, not wall-clock time.
- [ ] Run `uv run python -m pytest
  tests/integration/r2/adaptation/test_evaluation.py
  tests/integration/r2/adaptation/test_waivers.py
  tests/integration/lib/db/migrations/test_alembic_adaptation_profiles.py -q`,
  then isolated PostgreSQL upgrade, audit and exact-path commit.

Expected RED: report/waiver APIs and tables are absent. Expected GREEN: all named
tests pass, evaluator failure grants no success capability, integrity findings
cannot be waived, and semantic/profile changes invalidate applicability.

### Task 12: Atomically approve and lock screenplay for direction

**Files:**

- Modify: `r2/adaptation/authority.py`
- Modify: `lib/db/repositories/adaptation.py`
- Modify: `lib/db/models/adaptation.py`
- Modify: `lib/db/adaptation_uow.py`
- Create: `alembic/versions/6c7c4a0e0002_add_screenplay_admission.py`
- Test: `tests/integration/r2/adaptation/test_screenplay_admission.py`
- Test: `tests/integration/lib/db/migrations/test_alembic_screenplay_admission.py`

**Interfaces:**

- Consumes fixed `ScreenplayAdmissionCommand`, locked guard and exact dependency
  refs. Produces the fixed service receipt plus
  `ApprovedScreenplayReader.get_exact_admitted(user_id, project_name,
  screenplay_ref, admission_ref) -> ScreenplayArtifactV2`. Migration is exactly
  `revision = "6c7c4a0e0002"`, `down_revision = "6c7c4a0e0001"`.

- [ ] Test missing/stale map approval, blocking report, invalid waiver, edit between
  approval and lock, retry after supersession, cross-profile refs and concurrent
  admissions. Corrupt an otherwise FK-valid head to an effective rejection and to
  an accepting decision for a different screenplay; both must fail before write.
- [ ] Implement one command that appends the exact screenplay admission decision
  and advances the admission head in one transaction after folding and comparing its
  authoritative chain and revalidating every dependency through that same UoW.
- [ ] In that transaction verify proposal N, deep-snapshot and rehash exact N+1,
  require the same screenplay ID and exact permitted lifecycle transition,
  append N+1 plus its decision, and never update N in place.
- [ ] Expose an exact approved/locked screenplay reader for Director; expose no
  mutation through that port.
- [ ] Run `uv run python -m pytest
  tests/integration/r2/adaptation/test_screenplay_admission.py
  tests/integration/lib/db/migrations/test_alembic_screenplay_admission.py
  tests/unit/r2/test_m6_architecture_boundaries.py -q` against the isolated
  PostgreSQL fixture, then audit and exact-path commit.

Expected RED: admission API/migration are absent. Expected GREEN: exact admitted
read succeeds, every stale/cross-profile/corrupt/race case fails before write,
proposal N is unchanged, and only the atomic N+1 admission decision grants use
of its `APPROVED` plus `locked_for_direction=true` state.

### M6-C gate

- [ ] Run all profile, donor-parity, report, waiver and screenplay-admission tests
  plus cumulative adaptation and Narrative authority regressions.
- [ ] Freeze clean HEAD; verify exact source manifest/scope; independently review;
  add `docs/r2/evidence/R2_M6_C_REVIEW.md` only on approval.

## Checkpoint M6-D — TakeDirector and M4 compatibility retrofit

### Task 13: Implement TakeDirector adapter

**Interfaces:** `TakeDirectorAdapter` implements the verified `DirectorAdapter`;
`director_kind = DirectorKind.TAKE`; `direct(artifact: AdmittedScreenplayRef) ->
DirectorSuccess`, loading the exact admitted screenplay through the read-only
port from Task 12.

**Files:**

- Create: `r2/production_intelligence/take_director.py`
- Modify: `r2/production_intelligence/director.py`
- Test: `tests/unit/r2/production_intelligence/test_take_director.py`
- Test: `tests/unit/r2/production_intelligence/test_director.py`

- [ ] Test exact approved/locked screenplay input, deterministic normalized
  SceneSpec/ShotSpecV2 output, empty/orphan/duplicate shots, invalid vocabulary,
  stale profile/map ref, provider-field leakage and no route fallback.
- [ ] Implement a pure/provider-neutral `TakeDirectorAdapter`; keep provider jobs,
  candidates, retries, budgets and master approval outside it.
- [ ] Preserve existing factual/OpenMontage routing and Human override semantics.
- [ ] Run full Director tests, static checks and audit check; commit.

Expected RED: adapter import fails. Expected GREEN: Take and existing Director
tests pass; malformed output maps to existing failure classes; old routes and
Human override behavior remain unchanged.

### Task 14: Retrofit readiness, fingerprints and Production consumers

**Interfaces:** dual-read consumers accept `ShotSpecV1 | ShotSpecV2`; content
fingerprinting dispatches by schema selector; execution fingerprint and
`ProductionReadinessEvaluator.evaluate` public signatures stay unchanged.

**Files:**

- Modify: `r2/contracts/__init__.py`
- Modify: `r2/contracts/director.py`
- Modify: `r2/contracts/fingerprints.py`
- Modify: `r2/m3/director.py`
- Modify: `r2/m3/host_integration.py`
- Modify: `r2/m3/preparation.py`
- Modify: `r2/production_intelligence/capability_registry.py`
- Modify: `r2/production_intelligence/fixture_loader.py`
- Modify: `r2/production_intelligence/prompting.py`
- Modify: `r2/production_intelligence/readiness.py`
- Test: `tests/unit/r2/contracts/test_architecture_boundaries.py`
- Test: `tests/unit/r2/contracts/test_production.py`
- Test: `tests/unit/r2/contracts/test_roundtrip.py`
- Test: `tests/unit/r2/production_intelligence/test_architecture_boundaries.py`
- Test: `tests/unit/r2/production_intelligence/test_contracts.py`
- Test: `tests/unit/r2/production_intelligence/test_prompting.py`
- Test: `tests/unit/r2/production_intelligence/test_readiness.py`
- Test: `tests/integration/r2/m4/test_approved_master_semantics.py`
- Test: `tests/integration/r2/production/test_manifest_bridge_integration.py`
- Test: `tests/integration/r2/production/test_manifest_recovery_integration.py`
- Test: `tests/integration/r2/production/test_master_promotion_integration.py`

- [ ] Refresh graph traces inbound/outbound from ShotSpec, fingerprints, Director
  execution, readiness and promotion; coverage-check every candidate before edits.
  Persist the exact candidate-path/signature hashes in the scope manifest. If
  the accepted M5C head changes a public seam relative to the fixed catalog,
  exit with `M6_BASE_SEAM_CHANGED`; do not edit and do not ask a design question.
  Newly discovered consumers with unchanged public seams are added mechanically
  to the Task 14 owned-path/test manifest and verified before edits.
- [ ] Add failing v1/v2 dual-read tests and prove approved v1 masters remain valid
  historical evidence while new v2 content invalidates stale readiness/candidates.
- [ ] Keep execution fingerprint separation and “explicit approved master wins”
  semantics unchanged.
- [ ] Run every affected M4 test, Golden A host integration, contract/fingerprint/
  Director/readiness/promotion tests and audit check; commit exact discovered paths.

Expected RED: new v2 cases fail at typed consumers while all pre-existing v1
cases pass. Expected GREEN: every graph-proven consumer and named regression
passes, Golden A/v1 hashes remain unchanged, and v2 semantic changes invalidate
stale readiness/candidates.

### M6-D gate

- [ ] Run the complete M4 gate selected by `CONTRIBUTING.md`, all Take parity and
  M6-A–D tests, full static/import/dependency checks, scope verifier and diff check.
- [ ] Freeze clean HEAD; independently review both M6 spec conformance and M4
  non-regression; add `docs/r2/evidence/R2_M6_D_REVIEW.md` only on approval.

## Checkpoint M6-E — Golden B end-to-end evidence

### Task 15: Build the shared-Canon dual-profile corpus

**Interfaces:** `build_golden_b_canon() -> CanonFixture` and
`run_profile_slice(profile_ref: AdaptationProfileRef) -> GoldenBSliceEvidence`;
the acceptance test uses public services/readers only.

**Files:**

- Create: `tests/fixtures/r2/m6_dual_profile_corpus.py`
- Create: `tests/integration/r2/test_m6_dual_profile_acceptance.py`

- [ ] Construct one pinned Canon fixture with 2+ characters, location change,
  prop/state change and secret/knowledge constraint.
- [ ] Drive public interfaces to two sibling branches, separately approved maps,
  reports/waivers, approved/locked screenplays, TAKE output, 5–10 ShotSpecV2
  shots, readiness, at least one multi-candidate shot, explicit master selection
  and final 60–120-second assembly per profile.
- [ ] Assert independent branch heads, evidence and masters plus exact common
  parent identity. Do not assert cultural representativeness.
- [ ] Run the acceptance test and audit check; commit.

Expected RED: fixture/public flow is absent. Expected GREEN: exactly two
separately reviewable 60–120 second slices pass from the same Canon ref with
isolated heads, reports, candidates and masters.

### Task 16: Add adversarial mutation and real-PostgreSQL acceptance tests

**Interfaces:** each `M6MutationCase` contains `case_id`, mutation,
`expected_error | expected_outcome | expected_finding`, `owning_boundary`, and
`expected_no_write`; concurrency uses injected hooks plus `asyncio.Barrier(2)`,
never sleeps.

**Files:**

- Modify: `tests/integration/r2/test_m6_dual_profile_acceptance.py`
- Create: `tests/integration/r2/adaptation/test_m6_postgres_concurrency.py`

- [ ] Add mutations for cross-profile sidecars, stale policy/report/waiver, changed
  Canon parent, silent rebase, overlay masking, secret leakage, continuity override,
  approval-lock split, ambiguous v1 mapping, failed/rejected latest candidate and
  retry tuple substitution.
- [ ] Assert each fails at its owning boundary, writes no partial authority state,
  leaves the sibling branch/master unchanged and yields stable public error codes.
- [ ] Run real PostgreSQL barriers for same-ID, same-head and different-profile
  genesis, rollback and deterministic lock order; record server/database identity.
- [ ] Commit tests only after observing the intended red failures against the
  pre-fix code and green results after the corresponding implementation.

Expected RED: each mutation first fails its intended assertion; already-green
cases must be recorded as proof of an existing boundary. Expected GREEN: stable
owning-boundary result, no partial write, unchanged sibling branch/master, and
all real-PostgreSQL races pass.

### Task 17: Run final gates and create the M6 handoff

**Interfaces:** handoff JSON remains `status = "PENDING_REVIEW"` until exact-HEAD
standards and spec reviews both approve; only then may it contain `status =
"ACCEPTED"` with exact SHA/parent, clean state, migration head, command exits/test
counts, PostgreSQL identity, graph generation/coverage, hashes, parity and Golden
A/B evidence.

Expected RED: before independent review, the verifier rejects any handoff marked
`ACCEPTED` and requires `PENDING_REVIEW`. Review rejection or any gate failure
keeps the handoff non-accepted.

**Files:**

- Create: `docs/r2/evidence/R2_M6_FINAL_VERIFICATION.md`
- Create: `docs/r2/evidence/R2_M6_IMPLEMENTATION_HANDOFF.json`

- [ ] From one clean exact HEAD, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run basedpyright --warnings
uv run lint-imports
uv run deptry lib server alembic scripts tests r2
uv run python -m pytest -n 4 --dist loadfile
uv run python scripts/audit_tests.py --check
(cd frontend && pnpm check)
(cd website && pnpm check)
git diff --check
git status --short
```

Expected GREEN: every command exits 0, pytest selects a non-zero set with no
required skip, `git status --short` is empty, donor/M4/M6 gates pass, and both
independent reviews approve the same exact HEAD.

- [ ] Also run both donor source verifiers/parity suites, M4 Golden A regression,
  M6 real-PostgreSQL concurrency suite, dual-profile Golden B acceptance and the
  M6 scope verifier. A skip in required evidence is a failed gate unless an
  explicit approved waiver is recorded outside this plan.
- [ ] Record exact HEAD, clean status, command/exit/count evidence, database
  identity, graph generation/coverage, document/source hashes, donor parity,
  fixture/artifact/decision fingerprints and checkpoint-review lineage.
- [ ] Run independent Codex standards/spec review on the exact final HEAD. Fixes
  require a new exact HEAD and complete affected rerun.
- [ ] Commit only final evidence after review approval:

```bash
git add docs/r2/evidence/R2_M6_FINAL_VERIFICATION.md docs/r2/evidence/R2_M6_IMPLEMENTATION_HANDOFF.json
git commit -m "docs(r2): record verified M6 handoff"
```

- [ ] Stop. Report the accepted implementation SHA and evidence paths. Do not
  push, merge, run an operating migration, call a provider, start a worker or
  deploy without separate explicit authorization.

## Plan Self-Review

- **Spec coverage:** Tasks 1–4 cover versioned contracts, exact profiles and
  ShotSpec compatibility; 5–7 cover evidence, retry/OCC and map authority; 8–12
  cover both evaluators, reports, governed waivers and admission; 13–14 cover
  TakeDirector and M4 consumers; 15–17 cover dual Golden B, adversarial evidence
  and final acceptance.
- **Type consistency:** commands, authorization, decisions, receipt, head,
  repository/authority ports, selectors, task-local records and public errors
  are defined once above. Public authority takes `authenticated_principal`; no
  caller-supplied authorization remains.
- **Migration consistency:** `5c7c4a0e0004 -> 6a7c4a0e0001 ->
  6b7c4a0e0001 -> 6c7c4a0e0001 -> 6c7c4a0e0002`; a later checkpoint never edits
  an earlier migration.
- **Authority consistency:** retry precedes writes; online currentness folds the
  complete chain under the same locked UoW; proposal/profile code cannot write
  heads; exact admission, not a field alone, grants Director capability.
- **Compatibility consistency:** accepted v1 bytes/hashes and Golden A remain
  immutable; Take writes v2; provider/runtime fields remain outside semantic
  content identity.
- **No-question execution:** every open base condition maps to a stable stop
  code. Every implementation choice within an accepted base is fixed here.
- **Placeholder scan:** `...` appears only in Python Protocol/method-body
  signatures whose behavior, inputs, outputs and tests are specified. There is
  no `TBD`, `TODO`, option selection or unresolved Human decision.
