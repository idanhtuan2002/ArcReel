# R2 P1 plan — the smallest host-owned A–D receipt and operator-control surface

Implements `docs/superpowers/specs/2026-09-22-r2-p1-gate-receipt-surface-design.md`
(head `8a907b93` at plan time). ADR-0089 P1 backlog item 6 only.

## Global Constraints

- Start only from `feat/r2-m7-host-production-hardening` HEAD `8a907b93`
  (`content-production-os-m7`). No changes to `ProductionApprovalService`'s
  signature, `AdaptationAuthorityService`'s signature, or any `LOCKED`
  decision registry contract (`ApprovedMasterMetadata`,
  `ScreenplayAdmissionDecision`).
- Every new DB table is additive (a new Alembic revision adding exactly
  three tables); no existing table's schema changes.
- Every gate endpoint requires the real, existing session-JWT
  `get_current_user` dependency — no service-account/agent-callable path,
  no caller-supplied `authenticated_principal`.
- User-facing frontend text gets i18n keys in all three supported languages
  (`en`, `vi`, `zh`) per `AGENTS.md`'s existing rule — checked by
  `tests/unit/lib/i18n/test_i18n_consistency.py`.
- This plan touches Alembic (a new migration) and `frontend/` — per
  `CONTRIBUTING.md`'s test-selection rule this means the full backend gate
  (`pytest -n 4 --dist loadfile`, SQLite *and* postgres-compat selections)
  and `(cd frontend && pnpm check)` are both required before the final
  commit, not just the affected-directory subset.
- Stop after Task 6's evidence for review (self-review with human-override
  disclosure per the M7-A..D / M3 precedent, if Codex is unavailable) — no
  push/merge/tag without separate explicit human approval.

---

### Task 1: Gate contracts

**Files:** `r2/contracts/gates.py` (new): `GateAuthorization`,
`GreenlightDecision`, `PublishApprovalDecision`, `FinalCutReceipt` (design
§4). `tests/unit/r2/contracts/test_gates.py` (new).

**Interfaces:** pure Pydantic contracts, no I/O. `GreenlightDecision.action`/
`PublishApprovalDecision.action` are `Literal` unions (`GREENLIGHT`/`REVOKE`,
`APPROVE_PUBLISH`/`REVOKE`) matching the `Claim`/`AdaptationDecision`
convention of an explicit action enum rather than a bare boolean.

- [ ] Write the four contracts exactly as shaped in design §4.1/§4.2, reusing
  `NonEmptyStr`/`R2ContractModel`/the existing tz-aware `datetime` validator
  convention from `r2/contracts/factual.py`/`r2/contracts/adaptation.py`.
- [ ] Unit tests: round-trip validation, `action` literal enforcement,
  rejection of a naive (non-tz-aware) `authorized_at`/`selected_at` if the
  shared `_aware` validator is reused (confirm it is importable from
  `r2.contracts.common` or wherever it actually lives before assuming so).
- [ ] `uv run pytest tests/unit/r2/contracts/test_gates.py -v` green.
- [ ] Commit `feat(r2): add Gate A-D receipt contracts`.

### Task 2: DB models and migration

**Files:** `lib/db/models/gates.py` (new): `GreenlightDecisionModel`,
`PublishApprovalDecisionModel`, `FinalCutReceiptModel`. One new Alembic
revision under `alembic/versions/`.

**Interfaces:** three tables, columns matching Task 1's contracts plus
`sequence: int` (repo-assigned, not client-supplied). Follow
`lib/db/models/host_hardening.py`'s `MasterHeadVersionModel`/
`PromotionReceiptModel` exactly for column typing/index conventions (design
§7's stated precedent) rather than the older `AdaptationDecisionModel` shape.

- [ ] `GreenlightDecisionModel`/`PublishApprovalDecisionModel`: PK
  `(user_id, project_name, decision_id)`; unique constraint
  `(user_id, project_name, sequence)`.
- [ ] `FinalCutReceiptModel`: its own primary key (a receipt has no natural
  caller-supplied `decision_id` the way a command-driven decision does —
  confirm against `PromotionReceiptModel`'s own PK choice and mirror it);
  unique `(user_id, project_name, artifact_key, sequence)`.
- [ ] One new Alembic revision, `down_revision` = the exact current head at
  Task-2 time (`alembic heads` before writing the revision, not assumed).
- [ ] Migration round-trip test mirroring M7-B's own precedent style
  (`upgrade head` → `upgrade head` no-op → `downgrade base` → `upgrade head`)
  against a real disposable PostgreSQL container, per this repo's existing
  Alembic-migration test convention (check `tests/integration/lib/db/migrations/`
  for the nearest analogous existing test file to model, e.g. whichever one
  covers `host_hardening`'s own tables, and follow its exact shape).
- [ ] `uv run alembic upgrade head` clean against SQLite dev DB.
- [ ] Commit `feat(db): add Gate A/D decisions and Gate C receipt tables`.

### Task 3: Repositories

**Files:** `lib/db/repositories/gates.py` (new). `r2/gates/ports.py` (new,
small Protocols: `GreenlightRepositoryPort`, `PublishApprovalRepositoryPort`,
`FinalCutReceiptRepositoryPort`). `tests/integration/lib/db/repositories/test_gates.py`
(new).

**Interfaces:**

```python
class GreenlightRepositoryPort(Protocol):
    async def append(self, decision: GreenlightDecision) -> None: ...
    async def list_for_project(self, *, user_id: str, project_name: str) -> list[GreenlightDecision]: ...

# PublishApprovalRepositoryPort mirrors this shape exactly.

class FinalCutReceiptRepositoryPort(Protocol):
    async def append(self, receipt: FinalCutReceipt) -> None: ...
    async def list_for_artifact(self, *, user_id: str, project_name: str, artifact_key: str) -> list[FinalCutReceipt]: ...
```

- [ ] `append()` assigns `sequence` itself (read current max + 1 inside the
  same transaction, or an equivalent race-safe approach — confirm which
  pattern `lib/db/repositories/adaptation.py`'s own sequence assignment uses
  and match it, since it already solved this exact race).
- [ ] Real integration tests against `session_factory` (dialect-aware,
  matching this repo's existing `uses_db` fixture convention): append +
  read-back round trip, sequence increments correctly under two sequential
  appends, unique-constraint violation surfaces as a typed error not a raw
  DB exception leaking through.
- [ ] `uv run pytest tests/integration/lib/db/repositories/test_gates.py -v`
  green.
- [ ] Commit `feat(r2): add Gate A/C/D repositories`.

### Task 4: Gate B's missing real authority adapter

**Files:** `r2/adaptation/session_authority.py` (new, or an equally
honestly-named module — not `authority.py` itself, which is the service, not
an adapter).

**Interfaces:** `SessionAuthenticatedShowrunnerAuthority` implementing
`AdaptationShowrunnerAuthorityPort.authorize()`.

Research confirmed `AdaptationShowrunnerAuthorityPort` has zero real
(non-test) implementation anywhere — `FakeAuthority` in test code is the
only existing implementor. Gate B's route (Task 5) cannot call the real
`AdaptationAuthorityService` without one. V1 is explicitly single-operator,
self-hosted, no multi-tenant/multi-role promise
(`R2_V1_PRODUCTION_RELEASE_STRATEGY.md` §4) — so the correct-for-V1 real
adapter authorizes any already-session-authenticated principal as
`HUMAN_SHOWRUNNER` unconditionally; it does not implement a separate
per-project grant registry (there is nothing to check that against in V1,
and inventing one would be new authoritative state ADR-0089 says V1 must
not add). State this scoping explicitly in the module's own docstring, not
just here.

- [ ] Implement `SessionAuthenticatedShowrunnerAuthority.authorize()`
  returning a real `AdaptationDecisionAuthorization` for any
  `authenticated_principal`.
- [ ] Unit test proving it never raises `AdaptationAuthorityDeniedError` for
  any principal (documenting the V1 scoping decision in the test's own
  docstring/comment, not just the module's).
- [ ] Commit `feat(r2): add the real single-operator showrunner authority adapter`.

### Task 5: Server routes

**Files:** `server/routers/gates.py` (new). Registration in `server/app.py`
(mirror `server/app.py:634`'s exact `include_router(..., dependencies=[Depends(get_current_user)], tags=[...])`
pattern).

**Interfaces (design §5):**

```text
POST /api/v1/projects/{project_name}/gates/greenlight
POST /api/v1/projects/{project_name}/gates/narrative-lock
POST /api/v1/projects/{project_name}/gates/final-cut
POST /api/v1/projects/{project_name}/gates/publish-approval
GET  /api/v1/projects/{project_name}/gates
```

- [ ] Greenlight/publish-approval handlers: construct the Task 3
  repositories via `lib.db.engine.safe_session_factory` (the exact
  module-level pattern `ExecutionRecoveryScheduler` already uses in the live
  server process — confirmed real, not per-request `Depends()` DI), append
  a decision, return it.
- [ ] Narrative-lock handler: construct `AdaptationAuthorityService` with
  the real `safe_session_factory`-backed `uow_factory` and Task 4's new
  `SessionAuthenticatedShowrunnerAuthority`; call
  `admit_screenplay_for_direction` with `authenticated_principal` from
  `get_current_user`, not a request body field.
- [ ] Final-cut handler: `await asyncio.to_thread(...)`-call the existing,
  unmodified `ProductionApprovalService.promote()` (mirroring
  `server/routers/versions.py`'s established sync-bridge pattern exactly),
  then append a `FinalCutReceipt` via Task 3's repository using the same
  request's fields (design §4.2) — including on the `changed=False`
  no-op-promotion branch.
- [ ] `GET .../gates`: read all four gates' current/history state (Greenlight
  and Publish Approval from Task 3's `list_for_project`; Narrative Lock from
  the existing `AdaptationEvidenceService`; Final Cut from
  `ApprovedMasterMetadata` plus Task 3's `list_for_artifact` receipts) and
  assemble one response shape for the frontend panel.
- [ ] Router tests (real DB, real HTTP test client — check whether this
  repo's convention for DB-backed router tests is `tests/unit/server/routers/`
  with a fixture-backed fake DB or `tests/integration/server/`; follow
  whichever `test_versions_router.py` or a comparable DB-touching router
  test actually uses, don't assume).
- [ ] `uv run pytest tests/{unit,integration}/server/routers/test_gates_router.py -v`
  green (exact path depends on the tier decision above).
- [ ] Commit `feat(server): add the Gate A-D operator-control API`.

### Task 6: Frontend panel, i18n, and end-to-end evidence

**Files:** `frontend/src/components/.../GateApprovalPanel.tsx` (new, exact
directory chosen to match wherever `VersionTimeMachine.tsx`'s sibling
project/episode-level components live).
`frontend/src/api.ts` (add the five client methods).
`frontend/src/i18n/{en,vi,zh}/*.ts` (new keys).
`frontend/src/components/.../GateApprovalPanel.test.tsx` (new, mirroring
`VersionTimeMachine.test.tsx`'s shape).
`docs/r2/evidence/R2_P1_GATE_SURFACE.json` (new).

- [ ] `GateApprovalPanel.tsx`: local `useState` for open/loading/selected
  state, `useAppStore`'s `pushToast` for feedback — no new global store
  (design §5). Renders all four gates' status from `GET .../gates`; a button
  per actionable gate.
- [ ] Add every new user-facing string to all three `i18n` language files in
  the same commit; run `uv run pytest tests/unit/lib/i18n/test_i18n_consistency.py`
  before considering this task done, not just at the final gate.
- [ ] Frontend unit test (Vitest) covering: panel renders four gates,
  clicking an actionable gate's button calls the right endpoint and shows a
  toast on success/failure — mirroring `VersionTimeMachine.test.tsx`'s
  mocking approach.
- [ ] `(cd frontend && pnpm check)` green.
- [ ] End-to-end test: a real test (backend, `tests/integration/server/`)
  driving all four gate endpoints through an actual HTTP test client against
  a real seeded project/screenplay/candidate — not unit-level service calls
  — proving a human operator really can approve all four gates through this
  surface for at least one real project.
- [ ] Run the complete gate suite from `CONTRIBUTING.md` at the exact HEAD:
  ruff/format/basedpyright/lint-imports/deptry, full pytest (SQLite *and*
  postgres-compat selections, since a migration was added), `audit_tests.py --check`,
  `(cd frontend && pnpm check)`.
- [ ] Write `docs/r2/evidence/R2_P1_GATE_SURFACE.json`, mirroring the
  M7-A..D / M3-closure evidence shape: `status: "GATE_SURFACE_CLOSED"` or
  `REJECTED`, the design's verification matrix (§10) results, gate results,
  and `coverage_limitations` explicitly naming: `AtomicPromotionService`
  bridge deferred (design §8), Gate A's thin `source_digest` binding, Gate
  D's `deliverable_digest` reusing the Final Cut candidate's own digest
  (no separate final-export mechanism exists yet), and that a receipt is
  only recorded for approvals made through this route (not for any direct
  service call bypassing it).
- [ ] Commit `docs(r2): record the P1 gate-receipt surface` and stop for
  review — no push/merge/tag without separate explicit human approval.
