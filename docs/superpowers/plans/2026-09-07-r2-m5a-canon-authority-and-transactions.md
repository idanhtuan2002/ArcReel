# R2-M5A Canon Authority and Transactions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the durable, append-only Canon authority that creates pinned branches, commits approved deltas atomically, resolves immutable versions deterministically, and proves recovery and concurrency on PostgreSQL.

**Architecture:** Pure R2 contracts, hashing, state application, and validation live under `r2/`; persistence-neutral protocols keep them independent of SQLAlchemy. Host-side ORM, repository, and unit-of-work modules bind those protocols to the existing async database. `CanonTransactionService` is the only authority that calls write-port methods and completes a unit-of-work; `CanonResolver` can rebuild only disposable projections.

**Tech Stack:** Python 3.12+, Pydantic v2, SQLAlchemy async ORM, Alembic, PostgreSQL 16, SQLite focused tests, pytest/pytest-asyncio, ruff, basedpyright, import-linter, deptry.

**Spec:** `docs/superpowers/specs/2026-09-07-r2-m5a-canon-authority-and-transactions-design.md`

## Global Constraints

- Start execution only after the M4 Gate D result is accepted and integrated; rebase this worktree onto that accepted revision before Task 1 without changing the approved M5A design.
- Preserve ADR-0075: accepted `CanonDelta`, immutable `CanonVersion`, and `CanonBranch` are authority; `canon_resolved_projections` is disposable.
- `CanonTransactionService` is the sole Canon commit authority and the sole caller of authoritative write-port methods.
- One service call owns one fresh `AsyncSession` transaction through `CanonUnitOfWork`; repositories and resolvers never commit, roll back, or open sessions.
- Use `(user_id, project_name)` on every read, replay, branch creation, commit, projection rebuild, and integrity check. Cross-scope identifiers return the same result as unknown identifiers.
- `base_canon_version_id` is the semantic base: null for main genesis, the pinned parent version for narrative version 1, and the preceding local version afterward.
- Persist `sha256`, `r2-canon-delta-v1`, `r2-canon-content-v1`, and `r2-canon-schema-v1`; unsupported stored versions fail closed.
- Fact validity is `[effective_from, effective_until)` with null infinities. `RETIRE_FACT` supplies its non-null end time in the delta.
- `canon_delta_id` is the idempotency identity. An exact retry is resolved before base comparison. One `approval_ref` authorizes one accepted delta identity.
- Same-branch writes serialize with PostgreSQL `SELECT ... FOR UPDATE`; SQLite uses the existing `BEGIN IMMEDIATE` focused-test convention. PostgreSQL 16 is the concurrency acceptance authority.
- Do not add KnowledgeState, NarrativeChangeSet compilation, M5B/M5C behavior, Canvas, providers, production activation, or user interface code.
- Do not modify frozen R2 registries to make tests pass. They already name `CanonTransactionService`; implementation must conform to them.
- Follow `CONTRIBUTING.md` test selection. Every task that changes tests runs `uv run python scripts/audit_tests.py --check`; the final task runs the full affected backend gates.
- Use explicit seams instead of patching private production symbols. Do not add sleeps, automatic retries, implicit rebases, or generic approval infrastructure.
- Graph evidence was verified at project generation `2026-09-07T13:08:31Z`, source head `9d5e6a3971cc88909e49b834974d763c06984491`; all relied-on paths had no recorded coverage gap. The graph is best-effort, and executors must re-check source after the M4 rebase.

## File and responsibility map

| File | Responsibility |
|---|---|
| `r2/contracts/narrative.py` | Provider-neutral Canon atoms, typed operations, delta/approval/branch/version/result contracts |
| `r2/contracts/__init__.py` | Public exports for the new contracts |
| `r2/narrative/errors.py` | Stable Canon error taxonomy |
| `r2/narrative/hashing.py` | Versioned delta/content hash creation and verification |
| `r2/narrative/canon_state.py` | Pure ordered delta application and resolved-view construction |
| `r2/narrative/validation.py` | Structural, interval, reference, and exact-fact contradiction validation |
| `r2/narrative/ports.py` | Read, projection, write, and unit-of-work protocols |
| `r2/narrative/canon_resolver.py` | Version-DAG replay, projection verification, and projection rebuild |
| `r2/narrative/canon_transaction.py` | Branch creation and the only approved Canon commit orchestration |
| `r2/narrative/integrity.py` | Executable logical-FK, lineage, linkage, and hash integrity checker |
| `r2/narrative/__init__.py` | Deliberate public narrative API; excludes persistence primitives |
| `lib/db/models/canon.py` | Four SQLAlchemy tables and physical constraints |
| `lib/db/models/__init__.py` | Register/export Canon ORM models |
| `lib/db/repositories/canon_repo.py` | Scoped SQLAlchemy reads and transaction-bound persistence primitives; no commit/rollback |
| `lib/db/canon_uow.py` | AsyncSession lifecycle and SQLite/PostgreSQL transaction startup |
| `alembic/versions/5a7c4a0e0001_add_canon_authority.py` | Additive schema from parent `c04b7d93e5a1` |
| `tests/unit/r2/contracts/test_narrative.py` | Strict contracts, discriminated operations, timestamps, normalization |
| `tests/unit/r2/narrative/test_hashing.py` | Hash domains, version pinning, deterministic bytes |
| `tests/unit/r2/narrative/test_canon_state.py` | Pure operation application and semantic no-op behavior |
| `tests/unit/r2/narrative/test_validation.py` | Reference, interval, retirement, and contradiction rules |
| `tests/unit/lib/db/models/test_canon.py` | ORM registration and authority-table metadata shape |
| `tests/integration/lib/db/migrations/test_alembic_canon_authority.py` | SQLite Alembic upgrade/downgrade schema proof |
| `tests/integration/lib/db/repositories/test_canon_repo.py` | Scoped repository, UoW, uniqueness, and no-commit behavior |
| `tests/integration/r2/narrative/test_canon_resolver.py` | Replay, pinned ancestry, projection loss/corruption/race |
| `tests/integration/r2/narrative/test_canon_transaction.py` | Approval, idempotency, base conflict, atomic commit |
| `tests/integration/r2/narrative/test_canon_concurrency.py` | PostgreSQL same-branch/different-branch concurrency and restart |
| `tests/integration/r2/narrative/test_canon_integrity.py` | Executable checker over valid and intentionally corrupted fixtures |
| `tests/unit/r2/narrative/test_canon_architecture_boundaries.py` | Commit authority and import/session ownership fitness rules |
| `pyproject.toml` | Import-linter contract keeping R2 narrative core independent of Host persistence |
| `docs/r2/evidence/R2_M5A_FINAL_VERIFICATION.md` | Exact revision, migration head, commands, exit codes, and disposable PostgreSQL identity |

---

### Task 1: Canon contracts and error vocabulary

**Files:**
- Create: `r2/contracts/narrative.py`
- Create: `r2/narrative/errors.py`
- Modify: `r2/contracts/__init__.py`
- Test: `tests/unit/r2/contracts/test_narrative.py`

**Interfaces:**
- Consumes: `R2ContractModel`, `NonEmptyStr`, and `JSONValue` from `r2.contracts.common`.
- Produces: `CanonBranchType`, `EntityType`, `Entity`, `Fact`, `Event`, five typed operation models, `CanonOperation`, `CanonContent`, `CanonDeltaPayload`, `CanonDelta`, `CanonCommitApproval`, `CreateCanonBranch`, `CanonBranchSnapshot`, `CanonVersionSnapshot`, `AcceptedCanonDeltaSnapshot`, `CanonCommitResult`, `CanonValidationFinding`, and `CanonValidationReport`.
- Produces errors: `CanonError`, `CanonNotFoundError`, `CanonIdentityConflictError`, `CanonBaseVersionConflict`, `CanonApprovalError`, `CanonValidationError`, `CanonIntegrityError`, and `CanonOperationError`.

- [ ] **Step 1: Write failing strict-contract and operation-discriminator tests**

```python
def test_delta_preserves_operation_order_and_normalizes_reference_sets() -> None:
    payload = CanonDeltaPayload(
        canon_delta_id="delta-1",
        target_branch_id="main",
        base_canon_version_id=None,
        operations=[add_entity("e-1"), add_event("ev-1", participants=["e-1"])],
        source_change_set_refs=["s-2", "s-1", "s-2"],
        author_decision_refs=["a-1"],
        validation_report_refs=[],
        payload_hash_algorithm="sha256",
        payload_hash_version="r2-canon-delta-v1",
        content_schema_version="r2-canon-schema-v1",
        created_at=NOW,
        created_by="showrunner",
    )
    assert [item.operation_id for item in payload.operations] == ["op-e-1", "op-ev-1"]
    assert payload.source_change_set_refs == ["s-1", "s-2"]


def test_operation_payload_is_discriminated_and_extra_fields_fail() -> None:
    with pytest.raises(ValidationError):
        CanonDeltaPayload.model_validate({**valid_delta_json(), "operations": [{"kind": "ADD_FACT", "entity": {}}]})
    with pytest.raises(ValidationError):
        Entity(entity_id="e-1", entity_type="CHARACTER", canonical_name="Ada", aliases=[], extra="forbidden")
```

- [ ] **Step 2: Run the contract test to verify RED**

Run: `uv run python -m pytest tests/unit/r2/contracts/test_narrative.py -q`

Expected: collection fails because `r2.contracts.narrative` does not exist.

- [ ] **Step 3: Implement the exact contract shapes and validators**

```python
class Entity(R2ContractModel):
    entity_id: NonEmptyStr
    entity_type: EntityType
    canonical_name: NonEmptyStr
    aliases: list[NonEmptyStr]


class Fact(R2ContractModel):
    fact_id: NonEmptyStr
    subject_ref: NonEmptyStr
    predicate: NonEmptyStr
    value: JSONValue
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    source_event_refs: list[NonEmptyStr] = []


class Event(R2ContractModel):
    event_id: NonEmptyStr
    event_type: NonEmptyStr
    participant_refs: list[NonEmptyStr]
    location_ref: NonEmptyStr | None = None
    temporal_anchor: datetime | None = None
    causal_refs: list[NonEmptyStr] = []
    state_effect_refs: list[NonEmptyStr] = []


class AddEntityOperation(R2ContractModel):
    operation_id: NonEmptyStr
    kind: Literal["ADD_ENTITY"] = "ADD_ENTITY"
    target_id: NonEmptyStr
    entity: Entity


class UpdateEntityOperation(R2ContractModel):
    operation_id: NonEmptyStr
    kind: Literal["UPDATE_ENTITY"] = "UPDATE_ENTITY"
    target_id: NonEmptyStr
    entity: Entity


class AddFactOperation(R2ContractModel):
    operation_id: NonEmptyStr
    kind: Literal["ADD_FACT"] = "ADD_FACT"
    target_id: NonEmptyStr
    fact: Fact


class RetireFactOperation(R2ContractModel):
    operation_id: NonEmptyStr
    kind: Literal["RETIRE_FACT"] = "RETIRE_FACT"
    target_id: NonEmptyStr
    effective_until: datetime


class AddEventOperation(R2ContractModel):
    operation_id: NonEmptyStr
    kind: Literal["ADD_EVENT"] = "ADD_EVENT"
    target_id: NonEmptyStr
    event: Event


CanonOperation = Annotated[
    AddEntityOperation | UpdateEntityOperation | AddFactOperation | RetireFactOperation | AddEventOperation,
    Field(discriminator="kind"),
]


class CanonDeltaPayload(R2ContractModel):
    canon_delta_id: NonEmptyStr
    target_branch_id: NonEmptyStr
    base_canon_version_id: NonEmptyStr | None
    operations: list[CanonOperation]
    source_change_set_refs: list[NonEmptyStr]
    author_decision_refs: list[NonEmptyStr]
    validation_report_refs: list[NonEmptyStr]
    payload_hash_algorithm: Literal["sha256"] = "sha256"
    payload_hash_version: Literal["r2-canon-delta-v1"] = "r2-canon-delta-v1"
    content_schema_version: Literal["r2-canon-schema-v1"] = "r2-canon-schema-v1"
    created_at: datetime
    created_by: NonEmptyStr


class CanonDelta(CanonDeltaPayload):
    payload_hash: NonEmptyStr


class CanonContent(R2ContractModel):
    entities_by_id: dict[NonEmptyStr, Entity]
    facts_by_id: dict[NonEmptyStr, Fact]
    events_by_id: dict[NonEmptyStr, Event]
```

`CanonBranchType` has exactly `MAIN` and `NARRATIVE_BRANCH`; `EntityType` has exactly `CHARACTER`, `LOCATION`, `OBJECT`, and `ORGANIZATION`. Use one shared timezone-aware validator. Normalize aliases, fact source-event refs, and delta source/author/validation refs to sorted unique lists. For event participant and causal refs, reject duplicate input in a `mode="before"` validator, then sort; do not silently erase the structural error. Reject duplicate operation IDs and empty operation lists while preserving operation order. Validate every `CanonContent` map key against the contained atom ID. Set `ConfigDict(frozen=True, extra="forbid")` on `Entity`, `Fact`, `Event`, and `CanonContent`; state changes use `model_copy` and never mutate an atom. Never use a mutable object as a field default; implement the displayed empty lists with `Field(default_factory=list)`.

- [ ] **Step 4: Add immutable receipt/snapshot contracts and error payloads**

```python
class CanonVersionSnapshot(R2ContractModel):
    canon_version_id: NonEmptyStr
    branch_id: NonEmptyStr
    version_number: Annotated[int, Field(ge=1)]
    parent_version_id: NonEmptyStr | None
    committed_delta_id: NonEmptyStr
    committed_at: datetime
    committed_by: NonEmptyStr
    content_hash: NonEmptyStr
    content_hash_algorithm: NonEmptyStr
    content_hash_version: NonEmptyStr
    content_schema_version: NonEmptyStr


class CanonBranchSnapshot(R2ContractModel):
    branch_id: NonEmptyStr
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    branch_type: CanonBranchType
    parent_branch_id: NonEmptyStr | None
    parent_version_id: NonEmptyStr | None
    head_version_id: NonEmptyStr | None
    created_at: datetime
    created_by: NonEmptyStr


class CreateCanonBranch(R2ContractModel):
    branch_id: NonEmptyStr
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    branch_type: CanonBranchType
    parent_branch_id: NonEmptyStr | None = None
    parent_version_id: NonEmptyStr | None = None
    created_at: datetime
    created_by: NonEmptyStr


class CanonCommitApproval(R2ContractModel):
    approval_ref: NonEmptyStr
    canon_delta_id: NonEmptyStr
    payload_hash: NonEmptyStr
    payload_hash_algorithm: Literal["sha256"]
    payload_hash_version: Literal["r2-canon-delta-v1"]
    content_schema_version: Literal["r2-canon-schema-v1"]
    project_name: NonEmptyStr
    user_id: NonEmptyStr
    approved_by: NonEmptyStr
    approved_at: datetime
    status: Literal["APPROVED"]


class AcceptedCanonDeltaSnapshot(R2ContractModel):
    delta: CanonDelta
    approval: CanonCommitApproval
    committed_version_id: NonEmptyStr


class CanonValidationFinding(R2ContractModel):
    rule_id: NonEmptyStr
    affected_refs: tuple[NonEmptyStr, ...]
    message: NonEmptyStr


class CanonValidationReport(R2ContractModel):
    findings: tuple[CanonValidationFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings


class CanonCommitResult(R2ContractModel):
    accepted_delta: AcceptedCanonDeltaSnapshot
    version: CanonVersionSnapshot
    validation_report: CanonValidationReport


class CanonBaseVersionConflict(CanonError):
    def __init__(self, *, expected: str | None, current: str | None) -> None:
        self.expected = expected
        self.current = current
        super().__init__(f"expected Canon base {expected!r}; current base is {current!r}")
```

Proposal and approval selectors are v1 literals, so unsupported new writes fail during contract validation. Persisted `CanonVersionSnapshot` selector fields remain `NonEmptyStr` so historical rows stay parseable and the versioned hash layer or integrity checker can report an unsupported selector explicitly. Corrupt stored delta/approval JSON that cannot satisfy the strict accepted contract becomes `CanonIntegrityError`. Successful validation reports contain no findings, so the persisted accepted delta plus immutable version reconstruct a byte-identical retry result without replay. Keep the mutable branch head out of `CanonCommitResult`; later branch advancement must not change the original result. Set `model_config = ConfigDict(frozen=True, extra="forbid")` on snapshots and receipts. Keep mutable proposal models consistent with the existing `R2ContractModel` convention.

- [ ] **Step 5: Run contract tests and the existing R2 contract suite**

Run: `uv run python -m pytest tests/unit/r2/contracts/test_narrative.py tests/unit/r2/contracts -q`

Expected: all selected tests pass and at least one test is collected from the new file.

- [ ] **Step 6: Run the test-structure audit**

Run: `uv run python scripts/audit_tests.py --check`

Expected: exit 0 with no test-structure violations.

- [ ] **Step 7: Commit the contract slice**

```bash
git add r2/contracts/narrative.py r2/contracts/__init__.py r2/narrative/errors.py tests/unit/r2/contracts/test_narrative.py
git commit -m "feat(r2): define M5A canon contracts"
```

---

### Task 2: Versioned Canon hashing

**Files:**
- Create: `r2/narrative/hashing.py`
- Test: `tests/unit/r2/narrative/test_hashing.py`

**Interfaces:**
- Consumes: `CanonContent`, `CanonDeltaPayload`, `CanonDelta`, and `canonical_json_bytes`.
- Produces: `seal_canon_delta(payload: CanonDeltaPayload) -> CanonDelta`, `compute_canon_delta_hash(payload: CanonDeltaPayload) -> str`, `verify_canon_delta_hash(delta: CanonDelta) -> None`, `compute_canon_content_hash(content: CanonContent, *, algorithm: str = "sha256", hash_version: str = "r2-canon-content-v1", schema_version: str = "r2-canon-schema-v1") -> str`, and `verify_canon_content_hash(content: CanonContent, *, expected_hash: str, algorithm: str, hash_version: str, schema_version: str) -> None`.

- [ ] **Step 1: Write failing hash-domain tests**

```python
def test_delta_hash_is_order_sensitive_for_operations_and_stable_for_reference_sets() -> None:
    first = payload(operations=[op_a(), op_b()], source_refs=["s-2", "s-1"])
    reordered_refs = payload(operations=[op_a(), op_b()], source_refs=["s-1", "s-2"])
    reordered_ops = payload(operations=[op_b(), op_a()], source_refs=["s-1", "s-2"])
    assert compute_canon_delta_hash(first) == compute_canon_delta_hash(reordered_refs)
    assert compute_canon_delta_hash(first) != compute_canon_delta_hash(reordered_ops)


def test_unsupported_historical_hash_version_fails_closed() -> None:
    with pytest.raises(CanonIntegrityError, match="unsupported Canon content hash version"):
        compute_canon_content_hash(empty_content(), hash_version="r2-canon-content-v2")
```

- [ ] **Step 2: Run the hash tests to verify RED**

Run: `uv run python -m pytest tests/unit/r2/narrative/test_hashing.py -q`

Expected: collection fails because `r2.narrative.hashing` does not exist.

- [ ] **Step 3: Implement explicit hash payloads**

```python
def compute_canon_delta_hash(payload: CanonDeltaPayload) -> str:
    _require_versions(
        algorithm=payload.payload_hash_algorithm,
        hash_version=payload.payload_hash_version,
        schema_version=payload.content_schema_version,
        expected_hash_version="r2-canon-delta-v1",
    )
    value = {
        "canon_delta_id": payload.canon_delta_id,
        "target_branch_id": payload.target_branch_id,
        "base_canon_version_id": payload.base_canon_version_id,
        "operations": [item.model_dump(mode="json") for item in payload.operations],
        "source_change_set_refs": sorted(set(payload.source_change_set_refs)),
        "author_decision_refs": sorted(set(payload.author_decision_refs)),
        "validation_report_refs": sorted(set(payload.validation_report_refs)),
        "payload_hash_version": payload.payload_hash_version,
        "content_schema_version": payload.content_schema_version,
    }
    return hashlib.sha256(canonical_json_bytes(ensure_json_value(value))).hexdigest()
```

Do not include `payload_hash`, creation metadata, approval identity, or database metadata. Content hashing serializes only `CanonContent.model_dump(mode="json")`; algorithm/hash/schema versions are persisted selectors and unsupported selectors raise `CanonIntegrityError`.

- [ ] **Step 4: Run the new and existing fingerprint tests**

Run: `uv run python -m pytest tests/unit/r2/narrative/test_hashing.py tests/unit/r2/contracts/test_fingerprints.py -q`

Expected: all tests pass; existing fingerprint bytes remain unchanged.

- [ ] **Step 5: Run the test-structure audit**

Run: `uv run python scripts/audit_tests.py --check`

Expected: exit 0.

- [ ] **Step 6: Commit versioned hashing**

```bash
git add r2/narrative/hashing.py tests/unit/r2/narrative/test_hashing.py
git commit -m "feat(r2): add versioned canon hashing"
```

---

### Task 3: Pure Canon state application

**Files:**
- Create: `r2/narrative/canon_state.py`
- Create: `r2/narrative/__init__.py`
- Test: `tests/unit/r2/narrative/test_canon_state.py`

**Interfaces:**
- Consumes: Canon contracts, versioned content hashing, and `CanonOperationError`.
- Produces: `ResolvedCanonView`, `ResolvedCanonView.for_empty_branch(branch: CanonBranchSnapshot) -> ResolvedCanonView`, `empty_canon_content() -> CanonContent`, and `apply_canon_delta(base: CanonContent, delta: CanonDelta) -> CanonContent`.

- [ ] **Step 1: Write failing ordered-application tests**

```python
def test_ordered_delta_can_add_entity_then_reference_it_from_event() -> None:
    result = apply_canon_delta(empty_canon_content(), sealed_delta(add_entity("hero"), add_event("arrival", "hero")))
    assert result.entities_by_id["hero"].canonical_name == "Ada"
    assert result.events_by_id["arrival"].participant_refs == ["hero"]


def test_retirement_uses_payload_time_and_does_not_delete_history() -> None:
    retired = apply_canon_delta(content_with_open_fact(), sealed_delta(retire_fact("fact-1", UNTIL)))
    assert retired.facts_by_id["fact-1"].effective_until == UNTIL


def test_reference_must_exist_before_the_referencing_operation() -> None:
    with pytest.raises(CanonOperationError, match="missing participant entity hero"):
        apply_canon_delta(empty_canon_content(), sealed_delta(add_event("arrival", "hero"), add_entity("hero")))
```

- [ ] **Step 2: Run the state tests to verify RED**

Run: `uv run python -m pytest tests/unit/r2/narrative/test_canon_state.py -q`

Expected: collection fails because `apply_canon_delta` is unavailable.

- [ ] **Step 3: Implement copy-on-write operation application**

```python
class ResolvedCanonView(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    canon_version_id: NonEmptyStr | None
    branch_id: NonEmptyStr
    content_hash: NonEmptyStr
    content_hash_algorithm: NonEmptyStr = "sha256"
    content_hash_version: NonEmptyStr = "r2-canon-content-v1"
    content_schema_version: NonEmptyStr = "r2-canon-schema-v1"
    content: CanonContent

    @classmethod
    def for_empty_branch(cls, branch: CanonBranchSnapshot) -> ResolvedCanonView:
        content = empty_canon_content()
        return cls(
            canon_version_id=None,
            branch_id=branch.branch_id,
            content_hash=compute_canon_content_hash(content),
            content=content,
        )


def apply_canon_delta(base: CanonContent, delta: CanonDelta) -> CanonContent:
    entities = dict(base.entities_by_id)
    facts = dict(base.facts_by_id)
    events = dict(base.events_by_id)
    for operation in delta.operations:
        match operation:
            case AddEntityOperation():
                _require_target(operation.target_id, operation.entity.entity_id)
                _require_absent(entities, operation.target_id)
                entities[operation.target_id] = operation.entity
            case UpdateEntityOperation():
                current = _require_present(entities, operation.target_id)
                if current.entity_type is not operation.entity.entity_type:
                    raise CanonOperationError("entity type is immutable")
                entities[operation.target_id] = operation.entity
            case AddFactOperation():
                _require_absent(facts, operation.target_id)
                _require_present(entities, operation.fact.subject_ref, label="subject entity")
                for event_ref in operation.fact.source_event_refs:
                    _require_present(events, event_ref, label="source event")
                facts[operation.target_id] = operation.fact
            case RetireFactOperation():
                current = _require_present(facts, operation.target_id)
                if current.effective_until is not None:
                    raise CanonOperationError("fact is already retired")
                facts[operation.target_id] = current.model_copy(update={"effective_until": operation.effective_until})
            case AddEventOperation():
                _require_absent(events, operation.target_id)
                for entity_ref in operation.event.participant_refs:
                    _require_present(entities, entity_ref, label="participant entity")
                if operation.event.location_ref is not None:
                    _require_present(entities, operation.event.location_ref, label="location entity")
                for event_ref in operation.event.causal_refs:
                    _require_present(events, event_ref, label="causal event")
                events[operation.target_id] = operation.event
            case unreachable:
                assert_never(unreachable)
    return CanonContent(entities_by_id=entities, facts_by_id=facts, events_by_id=events)
```

Never mutate `base` or values stored inside it. Operation/target mismatch, add-existing, update-missing, retire-missing, retire-closed, and a reference not established by the base or an earlier operation raise `CanonOperationError`. `CanonTransactionService` translates operation errors into `CanonValidationError` with zero writes.

- [ ] **Step 4: Add semantic no-op comparison tests**

```python
def test_equivalent_update_produces_equal_content_for_transaction_noop_rejection() -> None:
    base = content_with_entity()
    candidate = apply_canon_delta(base, sealed_delta(update_entity(base.entities_by_id["hero"])))
    assert candidate == base
```

- [ ] **Step 5: Run state tests and audit**

Run: `uv run python -m pytest tests/unit/r2/narrative/test_canon_state.py -q`

Expected: all tests pass.

Run: `uv run python scripts/audit_tests.py --check`

Expected: exit 0.

- [ ] **Step 6: Commit the state engine**

```bash
git add r2/narrative/__init__.py r2/narrative/canon_state.py tests/unit/r2/narrative/test_canon_state.py
git commit -m "feat(r2): apply canon deltas deterministically"
```

---

### Task 4: M5A validation boundary

**Files:**
- Create: `r2/narrative/validation.py`
- Test: `tests/unit/r2/narrative/test_validation.py`

**Interfaces:**
- Consumes: `CanonContent`, `CanonDelta`, `CanonValidationFinding`, and `CanonValidationReport`.
- Produces: `intervals_overlap(left_from, left_until, right_from, right_until) -> bool` and `validate_canon_candidate(*, base: CanonContent, delta: CanonDelta, candidate: CanonContent) -> CanonValidationReport`.

- [ ] **Step 1: Write failing interval and contradiction tests**

```python
@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ((None, T2), (T2, None), False),
        ((None, None), (T1, T2), True),
        ((T1, T3), (T2, None), True),
    ],
)
def test_half_open_interval_overlap(left, right, expected) -> None:
    assert intervals_overlap(*left, *right) is expected


def test_overlapping_different_fact_values_are_rejected() -> None:
    report = validate_canon_candidate(base=base_fact("red"), delta=delta_fact("blue"), candidate=two_facts())
    assert [(item.rule_id, item.affected_refs) for item in report.findings] == [
        ("M5A_FACT_ACTIVE_COLLISION", ("fact-red", "fact-blue"))
    ]
```

- [ ] **Step 2: Run validation tests to verify RED**

Run: `uv run python -m pytest tests/unit/r2/narrative/test_validation.py -q`

Expected: collection fails because `r2.narrative.validation` does not exist.

- [ ] **Step 3: Implement deterministic structural validation**

Validate, in stable rule-ID then affected-ref order:

```python
RULES = (
    "M5A_REFERENCE_MISSING",
    "M5A_EVENT_CAUSAL_SELF_REFERENCE",
    "M5A_FACT_INTERVAL_INVALID",
    "M5A_FACT_RETIREMENT_INVALID",
    "M5A_FACT_ACTIVE_COLLISION",
)
```

Entity, participant, location, causal-event, and source-event references must exist in the post-operation candidate. A finite `effective_until` must be greater than a finite `effective_from`. Compare facts sharing `(subject_ref, predicate)` pairwise; equal values may overlap, different values may not. Adjacent boundaries do not overlap.

- [ ] **Step 4: Run validation tests and the pure M5A suite**

Run: `uv run python -m pytest tests/unit/r2/contracts/test_narrative.py tests/unit/r2/narrative -q`

Expected: all tests pass.

- [ ] **Step 5: Run the test-structure audit**

Run: `uv run python scripts/audit_tests.py --check`

Expected: exit 0.

- [ ] **Step 6: Commit the validation boundary**

```bash
git add r2/narrative/validation.py tests/unit/r2/narrative/test_validation.py
git commit -m "feat(r2): validate M5A canon candidates"
```

---

### Task 5: Canon ORM and additive migration

**Files:**
- Create: `lib/db/models/canon.py`
- Modify: `lib/db/models/__init__.py`
- Create: `alembic/versions/5a7c4a0e0001_add_canon_authority.py`
- Test: `tests/unit/lib/db/models/test_canon.py`
- Test: `tests/integration/lib/db/migrations/test_alembic_canon_authority.py`

**Interfaces:**
- Consumes: `Base`, `UserOwnedMixin`, `utc_now`, SQLAlchemy mapped columns, and Alembic parent `c04b7d93e5a1`.
- Produces: `CanonBranchModel`, `CanonDeltaModel`, `CanonVersionModel`, and `CanonResolvedProjectionModel` registered in `Base.metadata`.

- [ ] **Step 1: Write the failing migration upgrade/downgrade test**

```python
EXPECTED_TABLES = {
    "canon_branches",
    "canon_deltas",
    "canon_versions",
    "canon_resolved_projections",
}


def test_upgrade_creates_canon_authority_schema(alembic_cfg, migration_revisions) -> None:
    revision, parent = migration_revisions("*_add_canon_authority.py")
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, parent)
    command.upgrade(cfg, revision)
    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    assert EXPECTED_TABLES <= set(inspector.get_table_names())
    assert {"approval_ref"} == _unique_columns(inspector, "canon_deltas", "uq_canon_deltas_approval_ref")
```

Also assert all columns, nullable flags, self/branch/delta/projection foreign keys, indexes, checks, one-main partial index, downgrade removal, and preservation of every pre-existing table.

In `tests/unit/lib/db/models/test_canon.py`, call `register_models()` and assert the four Canon table names are in `Base.metadata.tables`, `canon_branches.head_version_id` and `parent_version_id` have no physical foreign keys, and every Canon-to-Canon physical FK uses `RESTRICT`.

- [ ] **Step 2: Run the migration test to verify RED**

Run: `uv run python -m pytest tests/integration/lib/db/migrations/test_alembic_canon_authority.py -q`

Expected: fail because the migration glob matches zero files.

- [ ] **Step 3: Implement the four ORM models**

```python
class CanonBranchModel(UserOwnedMixin, Base):
    __tablename__ = "canon_branches"
    branch_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    branch_type: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_branch_id: Mapped[str | None] = mapped_column(
        ForeignKey("canon_branches.branch_id", ondelete="RESTRICT")
    )
    parent_version_id: Mapped[str | None] = mapped_column(String(255), index=True)
    head_version_id: Mapped[str | None] = mapped_column(String(255), index=True)
```

Use `JSON` for ordered operations/reference arrays and resolved projections, `DateTime(timezone=True)` for all timestamps, `ondelete="RESTRICT"` on every Canon-to-Canon authority foreign key, and no ORM cascades. Retain `UserOwnedMixin`'s existing Host user-lifecycle FK behavior; the restrictive rule applies to branch/delta/version/projection history relationships. Add the partial unique main index with both `postgresql_where` and `sqlite_where`.

- [ ] **Step 4: Implement the exact Alembic revision**

```python
revision: str = "5a7c4a0e0001"
down_revision: str | None = "c04b7d93e5a1"
```

Create tables in branch → delta → version → projection order. Declare the version self-FK and version-to-delta FK inline in the `op.create_table` call for `canon_versions`; by then both referenced tables exist, and SQLite needs no post-create `ALTER TABLE`. Downgrade in reverse order. Do not backfill or alter existing tables.

- [ ] **Step 5: Run migration and model-registration tests**

Run: `uv run python -m pytest tests/integration/lib/db/migrations/test_alembic_canon_authority.py tests/unit/lib/db/models -q`

Expected: all selected tests pass; collection count is non-zero.

- [ ] **Step 6: Run audit and Alembic head checks**

Run: `uv run python scripts/audit_tests.py --check`

Expected: exit 0.

Run: `uv run alembic heads`

Expected: exactly `5a7c4a0e0001 (head)`.

- [ ] **Step 7: Commit the schema slice**

```bash
git add lib/db/models/canon.py lib/db/models/__init__.py alembic/versions/5a7c4a0e0001_add_canon_authority.py tests/unit/lib/db/models/test_canon.py tests/integration/lib/db/migrations/test_alembic_canon_authority.py
git commit -m "feat(db): add canon authority schema"
```

---

### Task 6: Persistence ports, repository, and unit-of-work

**Files:**
- Create: `r2/narrative/ports.py`
- Create: `lib/db/repositories/canon_repo.py`
- Create: `lib/db/canon_uow.py`
- Test: `tests/integration/lib/db/repositories/test_canon_repo.py`

**Interfaces:**
- Consumes: Canon snapshots/contracts and four ORM models.
- Produces: `CanonReadRepositoryPort`, `CanonProjectionRepositoryPort`, `CanonWriteRepositoryPort`, `CanonUnitOfWork`, `CanonUnitOfWorkFactory`, `CanonRepository`, `SqlAlchemyCanonUnitOfWork`, and `SqlAlchemyCanonUnitOfWorkFactory`.

- [ ] **Step 1: Write failing scoped-read and transaction-ownership tests**

```python
async def test_repository_never_commits_its_bound_session(db_factory) -> None:
    async with db_factory() as session:
        repo = CanonRepository(session)
        await repo.insert_branch(branch_snapshot())
        assert session.in_transaction()
        await session.rollback()
    async with db_factory() as session:
        assert await CanonRepository(session).get_branch(branch_id="main", project_name="p", user_id=USER) is None


async def test_cross_scope_ids_are_indistinguishable_from_unknown(db_factory) -> None:
    await create_branch_in_scope(db_factory, user_id=USER_A, project_name="p-a")
    async with db_factory() as session:
        repo = CanonRepository(session)
        assert await repo.get_branch(branch_id="main", project_name="p-b", user_id=USER_B) is None
        assert await repo.get_branch(branch_id="missing", project_name="p-b", user_id=USER_B) is None
```

- [ ] **Step 2: Run repository tests to verify RED**

Run: `uv run python -m pytest tests/integration/lib/db/repositories/test_canon_repo.py -q`

Expected: collection fails because the repository and ports do not exist.

- [ ] **Step 3: Define capability-separated protocols**

```python
class CanonReadRepositoryPort(Protocol):
    async def get_branch(self, *, branch_id: str, project_name: str, user_id: str) -> CanonBranchSnapshot | None: ...
    async def get_version(self, *, canon_version_id: str, project_name: str, user_id: str) -> CanonVersionSnapshot | None: ...
    async def get_accepted_delta(self, *, canon_delta_id: str, project_name: str, user_id: str) -> AcceptedCanonDeltaSnapshot | None: ...
    async def get_accepted_delta_by_approval_ref(self, *, approval_ref: str, project_name: str, user_id: str) -> AcceptedCanonDeltaSnapshot | None: ...
    async def list_scope_branches(self, *, project_name: str, user_id: str) -> tuple[CanonBranchSnapshot, ...]: ...
    async def list_branch_versions(self, *, branch_id: str, project_name: str, user_id: str) -> tuple[CanonVersionSnapshot, ...]: ...


class CanonProjectionRepositoryPort(CanonReadRepositoryPort, Protocol):
    async def load_projection(self, *, canon_version_id: str, project_name: str, user_id: str) -> ResolvedCanonView | None: ...
    async def upsert_projection(self, *, view: ResolvedCanonView, built_at: datetime, project_name: str, user_id: str) -> None: ...


class CanonWriteRepositoryPort(CanonProjectionRepositoryPort, Protocol):
    async def lock_branch(self, *, branch_id: str, project_name: str, user_id: str) -> CanonBranchSnapshot: ...
    async def insert_branch(self, branch: CanonBranchSnapshot) -> None: ...
    async def insert_delta(self, accepted: AcceptedCanonDeltaSnapshot) -> None: ...
    async def insert_version(self, version: CanonVersionSnapshot) -> None: ...
    async def advance_head(self, *, branch_id: str, expected_head_id: str | None, version_id: str, project_name: str, user_id: str) -> None: ...
    async def flush(self) -> None: ...


class CanonUnitOfWork(Protocol):
    repository: CanonWriteRepositoryPort
    async def __aenter__(self) -> CanonUnitOfWork: ...
    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None: ...
    async def commit(self) -> None: ...


class CanonUnitOfWorkFactory(Protocol):
    def __call__(self, *, serialized_authority_write: bool) -> CanonUnitOfWork: ...
```

Only `CanonUnitOfWork.repository` and `CanonTransactionService` may type against `CanonWriteRepositoryPort`. Do not export `CanonRepository` from `lib.db.repositories.__init__`; Host assembly imports the concrete adapter by its full module path.

- [ ] **Step 4: Implement scoped SQLAlchemy repository methods**

Every SELECT starts with all three available scope predicates, joining through branch ownership when the selected table does not carry user/project columns. `lock_branch` adds `.with_for_update()`. Before projection upsert, load the referenced version through that scoped join and raise `CanonNotFoundError` if unavailable. Snapshot conversion validates stored JSON through Pydantic. Corrupt branch/version/delta rows become `CanonIntegrityError`; corrupt projection JSON or metadata makes `load_projection` return `None` so the resolver can rebuild and replace that disposable row. Repository methods call `session.add`, `session.execute`, or `session.flush`; they contain no `commit`, `rollback`, session factory, or engine construction.

```python
async def advance_head(self, *, branch_id: str, expected_head_id: str | None, version_id: str, project_name: str, user_id: str) -> None:
    result = await self.session.execute(
        update(CanonBranchModel)
        .where(
            CanonBranchModel.branch_id == branch_id,
            CanonBranchModel.project_name == project_name,
            CanonBranchModel.user_id == user_id,
            CanonBranchModel.head_version_id.is_(None) if expected_head_id is None else CanonBranchModel.head_version_id == expected_head_id,
        )
        .values(head_version_id=version_id)
    )
    if rowcount(result) != 1:
        raise CanonIntegrityError("locked Canon branch head changed unexpectedly")
```

Implement `upsert_projection` with `sqlalchemy.dialects.postgresql.insert` or `sqlalchemy.dialects.sqlite.insert`, selected from the bound dialect, followed by `on_conflict_do_update(index_elements=["canon_version_id"], set_={"resolved_view_json": statement.excluded.resolved_view_json, "content_hash": statement.excluded.content_hash, "content_hash_algorithm": statement.excluded.content_hash_algorithm, "content_hash_version": statement.excluded.content_hash_version, "content_schema_version": statement.excluded.content_schema_version, "built_at": statement.excluded.built_at})`. Never copy branch head, approval, or version-number authority into the projection. Reject any dialect other than PostgreSQL or SQLite.

- [ ] **Step 5: Implement the Host unit-of-work adapter**

```python
class SqlAlchemyCanonUnitOfWork:
    async def __aenter__(self) -> SqlAlchemyCanonUnitOfWork:
        self.session = self._session_factory()
        if self.session.get_bind().dialect.name == "sqlite" and self._serialized_authority_write:
            await self.session.execute(text("BEGIN IMMEDIATE"))
        else:
            await self.session.begin()
        self.repository = CanonRepository(self.session)
        return self

    async def commit(self) -> None:
        await self.session.commit()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
        await self.session.close()
```

`SqlAlchemyCanonUnitOfWorkFactory.__call__(*, serialized_authority_write: bool)` returns a new UoW each time. The transaction service requests `serialized_authority_write=True`; read/projection facades request `False`. The flag selects SQLite `BEGIN IMMEDIATE`; it does not grant authority, and a projection-only UoW may still upsert its disposable cache row.

- [ ] **Step 6: Run repository/UoW tests on the dialect-aware fixture**

Run: `uv run python -m pytest tests/integration/lib/db/repositories/test_canon_repo.py -q`

Expected: all tests pass, including approval uniqueness and one-main-branch database constraints.

- [ ] **Step 7: Run audit and static checks for the new modules**

Run: `uv run python scripts/audit_tests.py --check`

Expected: exit 0.

Run: `uv run ruff check r2/narrative/ports.py lib/db/repositories/canon_repo.py lib/db/canon_uow.py tests/integration/lib/db/repositories/test_canon_repo.py`

Expected: all checks pass.

- [ ] **Step 8: Commit persistence boundaries**

```bash
git add r2/narrative/ports.py lib/db/repositories/canon_repo.py lib/db/canon_uow.py tests/integration/lib/db/repositories/test_canon_repo.py
git commit -m "feat(db): bind canon persistence unit of work"
```

---

### Task 7: Deterministic resolver and projection recovery

**Files:**
- Create: `r2/narrative/canon_resolver.py`
- Test: `tests/integration/r2/narrative/test_canon_resolver.py`

**Interfaces:**
- Consumes: `CanonProjectionRepositoryPort`, state application, validation, and versioned hashing.
- Produces: `CanonResolver(repository: CanonProjectionRepositoryPort, *, clock: Callable[[], datetime] = utc_now)` with `resolve(*, branch_id: str, version_id: str | None, project_name: str, user_id: str) -> ResolvedCanonView`.

- [ ] **Step 1: Write failing replay and pinned-parent tests**

```python
async def test_narrative_version_one_replays_from_pinned_parent(session_factory) -> None:
    fixture = await committed_parent_and_child(session_factory)
    view = await resolve_with_new_read_uow(session_factory, branch_id=fixture.child_id)
    assert set(view.content.entities_by_id) == {"parent-entity", "child-entity"}
    assert view.canon_version_id == fixture.child_version_id
    assert view.content_hash == fixture.child_content_hash


async def test_parent_advance_does_not_change_pinned_child(session_factory) -> None:
    before = await resolve_child(session_factory)
    await advance_parent_only(session_factory)
    after = await resolve_child(session_factory)
    assert after.model_dump(mode="json") == before.model_dump(mode="json")
```

- [ ] **Step 2: Run resolver tests to verify RED**

Run: `uv run python -m pytest tests/integration/r2/narrative/test_canon_resolver.py -q`

Expected: collection fails because `CanonResolver` does not exist.

- [ ] **Step 3: Implement version-DAG replay**

```python
class CanonResolver:
    def __init__(self, repository: CanonProjectionRepositoryPort, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._repository = repository
        self._clock = clock

    async def resolve(self, *, branch_id: str, version_id: str | None, project_name: str, user_id: str) -> ResolvedCanonView:
        branch = await self._require_branch(branch_id=branch_id, project_name=project_name, user_id=user_id)
        selected = version_id or branch.head_version_id
        if selected is None:
            if branch.parent_version_id is None:
                return ResolvedCanonView.for_empty_branch(branch)
            parent = await self._resolve_version(branch.parent_version_id, project_name=project_name, user_id=user_id)
            return parent.model_copy(update={"branch_id": branch.branch_id})
        await self._require_version_reachable_from_branch(branch=branch, version_id=selected, project_name=project_name, user_id=user_id)
        return await self._resolve_version(selected, project_name=project_name, user_id=user_id)
```

`_resolve_version` first accepts a projection only after stored metadata equals the immutable version receipt and recomputed content hash. Otherwise recursively resolve `version.parent_version_id`, require the accepted delta's semantic base to equal that parent, apply and validate it, recompute the recorded hash, and upsert only an exact match. Track visited version IDs and raise `CanonIntegrityError` on a cycle.

- [ ] **Step 4: Add missing/corrupt/concurrent projection tests**

```python
async def test_two_missing_projection_rebuilders_converge(concurrent_session_factory) -> None:
    await delete_projection(concurrent_session_factory, VERSION_ID)
    start = asyncio.Event()
    results = await run_two_resolvers(concurrent_session_factory, start=start)
    assert results[0].model_dump(mode="json") == results[1].model_dump(mode="json")
    assert await projection_row_count(concurrent_session_factory, VERSION_ID) == 1
```

Also prove corrupt projection replacement, corrupt authoritative delta failure, broken parent failure, unsupported historical hash version failure, and no use of current parent head.

- [ ] **Step 5: Run resolver tests and audit**

Run: `uv run python -m pytest tests/integration/r2/narrative/test_canon_resolver.py -q`

Expected: all tests pass.

Run: `uv run python scripts/audit_tests.py --check`

Expected: exit 0.

- [ ] **Step 6: Commit replay and recovery**

```bash
git add r2/narrative/canon_resolver.py tests/integration/r2/narrative/test_canon_resolver.py
git commit -m "feat(r2): resolve canon lineage and projections"
```

---

### Task 8: Canon transaction authority

**Files:**
- Create: `r2/narrative/canon_transaction.py`
- Modify: `r2/narrative/__init__.py`
- Test: `tests/integration/r2/narrative/test_canon_transaction.py`

**Interfaces:**
- Consumes: `CanonUnitOfWorkFactory`, `CanonResolver`, hashing, state, validation, contracts, and error taxonomy.
- Produces: `CanonCommitStage`; `CanonTransactionService(uow_factory: CanonUnitOfWorkFactory, *, version_id_factory: Callable[[], str] = new_version_id, fault_hook: Callable[[CanonCommitStage], None] = ignore_commit_stage)`; `create_branch(command: CreateCanonBranch) -> CanonBranchSnapshot`; and `commit(*, delta: CanonDelta, approval: CanonCommitApproval, project_name: str, user_id: str, now: datetime) -> CanonCommitResult`.

- [ ] **Step 1: Write failing branch-creation and approved-commit tests**

```python
async def test_approved_main_genesis_advances_head_atomically(session_factory) -> None:
    service = service_for(session_factory, version_ids=iter(["version-1"]).__next__)
    await service.create_branch(main_branch_command())
    result = await service.commit(delta=genesis_delta(), approval=approval_for(genesis_delta()), project_name="p", user_id=USER, now=NOW)
    assert result.version.canon_version_id == "version-1"
    assert result.version.parent_version_id is None
    assert await authority_counts(session_factory) == {"deltas": 1, "versions": 1, "projections": 1}
    assert await branch_head(session_factory) == "version-1"
```

- [ ] **Step 2: Run transaction tests to verify RED**

Run: `uv run python -m pytest tests/integration/r2/narrative/test_canon_transaction.py -q`

Expected: collection fails because `CanonTransactionService` does not exist.

- [ ] **Step 3: Implement idempotent branch creation**

For MAIN require both parent fields null. For NARRATIVE_BRANCH require both, load them in the same scope, and require the version belongs to the parent branch. Identical `branch_id` retry returns the existing snapshot; any field mismatch raises `CanonIdentityConflictError`. Translate the partial-main uniqueness violation to `CanonIdentityConflictError` without leaking another scope.

- [ ] **Step 4: Implement the exact commit ordering**

Before opening the UoW, call `verify_canon_delta_hash(delta)` and validate the approval's status, aware timestamp, delta ID, payload hash/selectors, scope, and non-empty `approved_by`. The authenticated application facade is responsible for deriving `approved_by` from the request principal; M5A exposes no unauthenticated router or Agent-tool entry point. Repeat the exact receipt binding check after the branch is locked and the semantic base is known; pre-lock validation is an early rejection, while the locked check is authoritative.

```python
async with self._uow_factory(serialized_authority_write=True) as uow:
    repository = uow.repository
    branch = await repository.lock_branch(
        branch_id=delta.target_branch_id,
        project_name=project_name,
        user_id=user_id,
    )
    existing = await repository.get_accepted_delta(
        canon_delta_id=delta.canon_delta_id,
        project_name=project_name,
        user_id=user_id,
    )
    if existing is not None:
        return self._resolve_exact_retry(existing=existing, delta=delta, approval=approval)
    current_base = branch.head_version_id if branch.head_version_id is not None else branch.parent_version_id
    if delta.base_canon_version_id != current_base:
        raise CanonBaseVersionConflict(expected=delta.base_canon_version_id, current=current_base)
    base_view = await CanonResolver(repository, clock=lambda: now).resolve(
        branch_id=branch.branch_id,
        version_id=current_base,
        project_name=project_name,
        user_id=user_id,
    )
    candidate = apply_canon_delta(base_view.content, delta)
    report = validate_canon_candidate(base=base_view.content, delta=delta, candidate=candidate)
    if not report.ok:
        raise CanonValidationError(report)
    if candidate == base_view.content:
        raise CanonValidationError("Canon delta is a semantic no-op")
    self._require_exact_approval(delta=delta, approval=approval, project_name=project_name, user_id=user_id)
    result = await self._append_version_and_projection(
        repository=repository,
        branch=branch,
        delta=delta,
        approval=approval,
        candidate=candidate,
        validation_report=report,
        now=now,
    )
    await uow.commit()
    return result
```

Define `_append_version_and_projection(*, repository: CanonWriteRepositoryPort, branch: CanonBranchSnapshot, delta: CanonDelta, approval: CanonCommitApproval, candidate: CanonContent, validation_report: CanonValidationReport, now: datetime) -> CanonCommitResult`. It allocates one version ID, sets version number to `1` or previous local number plus one, sets `parent_version_id = current_base`, persists delta then version then head then projection with an explicit flush/fault stage at each approved boundary, and returns snapshots constructed from those exact persisted values.

The retry comparison includes canonical payload bytes, all hash/schema selectors, semantic base, scope, every approval field, and the linked committed version. It reconstructs `CanonCommitResult(accepted_delta=existing, version=stored_version, validation_report=CanonValidationReport(findings=()))`, runs before current-base comparison, and performs no writes or projection replay. For a new delta, query `get_accepted_delta_by_approval_ref` before applying operations and raise `CanonApprovalError` if that receipt already belongs to another identity. Keep the database unique constraint as the concurrent-race arbiter and translate its violation to the same domain error.

- [ ] **Step 5: Add rejection and idempotency tests**

Prove zero authority writes for missing/wrong/rejected approval, wrong payload hash, wrong scope, stale base, invalid candidate, semantic no-op, conflicting delta ID, and reused approval reference. On retry, changing `approved_by` or `approved_at` under the same approval reference is an identity conflict. Prove an exact retry after head advancement returns byte-identical `CanonCommitResult` and does not call `version_id_factory`.

```python
async def test_exact_retry_precedes_base_conflict(session_factory) -> None:
    service = service_for(session_factory)
    first = await approved_commit(service)
    retried = await service.commit(delta=ORIGINAL_DELTA, approval=ORIGINAL_APPROVAL, project_name="p", user_id=USER, now=LATER)
    assert retried == first
    assert await authority_counts(session_factory) == {"deltas": 1, "versions": 1, "projections": 1}
```

- [ ] **Step 6: Run transaction tests and audit**

Run: `uv run python -m pytest tests/integration/r2/narrative/test_canon_transaction.py -q`

Expected: all tests pass.

Run: `uv run python scripts/audit_tests.py --check`

Expected: exit 0.

- [ ] **Step 7: Commit the authority service**

```bash
git add r2/narrative/canon_transaction.py r2/narrative/__init__.py tests/integration/r2/narrative/test_canon_transaction.py
git commit -m "feat(r2): commit approved canon deltas atomically"
```

---

### Task 9: Fault injection, concurrency, and restart proof

**Files:**
- Modify: `r2/narrative/canon_transaction.py`
- Test: `tests/integration/r2/narrative/test_canon_concurrency.py`

**Interfaces:**
- Consumes: `CanonCommitStage` and the `fault_hook` seam.
- Produces: all-or-nothing evidence at `BEFORE_DELTA_INSERT`, `AFTER_DELTA_FLUSH`, `AFTER_VERSION_FLUSH`, `AFTER_HEAD_FLUSH`, and `BEFORE_PROJECTION_FLUSH`.

- [ ] **Step 1: Write failing parameterized rollback tests**

```python
@pytest.mark.parametrize("stage", list(CanonCommitStage))
async def test_fault_at_each_flush_boundary_preserves_old_authority(session_factory, stage) -> None:
    def fail_at(observed: CanonCommitStage) -> None:
        if observed is stage:
            raise InjectedCommitFailure(stage.value)

    service = service_for(session_factory, fault_hook=fail_at)
    before = await complete_authority_snapshot(session_factory)
    with pytest.raises(InjectedCommitFailure):
        await commit_next(service)
    assert await complete_authority_snapshot(session_factory) == before
```

- [ ] **Step 2: Run the rollback test to verify RED**

Run: `uv run python -m pytest tests/integration/r2/narrative/test_canon_concurrency.py -k fault -q`

Expected: fail because commit stages are not emitted at every boundary.

- [ ] **Step 3: Emit deterministic fault stages after explicit flushes**

Call the injected synchronous hook only at the five public enum stages. Do not catch hook exceptions inside the transaction; UoW exit rolls back. The production default is a module-level no-op function passed as a constructor default, and tests inject the hook without patching private names.

- [ ] **Step 4: Write same-branch and different-branch concurrency tests**

```python
async def test_same_base_concurrent_commits_have_one_winner(concurrent_session_factory) -> None:
    start = asyncio.Event()
    outcomes = await run_two_commits(concurrent_session_factory, same_branch=True, start=start)
    assert sorted(type(item).__name__ for item in outcomes) == ["CanonBaseVersionConflict", "CanonCommitResult"]
    assert await local_version_count(concurrent_session_factory, MAIN_BRANCH) == 2


async def test_different_branches_commit_independently(concurrent_session_factory) -> None:
    outcomes = await run_two_commits(concurrent_session_factory, same_branch=False, start=asyncio.Event())
    assert all(isinstance(item, CanonCommitResult) for item in outcomes)
```

Also race two MAIN branch creations in one scope and require one success plus one `CanonIdentityConflictError`. Race the same `approval_ref` on different branches and require one committed delta plus one `CanonApprovalError`, with the losing transaction leaving no delta/version/projection. Use `asyncio.Event` as the start barrier and no sleeps. On SQLite this proves the serialized fallback; the final PostgreSQL run proves row-lock and uniqueness semantics.

- [ ] **Step 5: Add new-engine restart proof**

Commit through one engine/session factory, dispose it, construct a new engine/factory against the same temporary database, then resolve the head and compare version ID, canonical bytes, and content hash. Mark a permanently file-SQLite-only helper test `sqlite_only`; keep the dialect-aware `session_factory` restart test eligible for PostgreSQL.

- [ ] **Step 6: Run concurrency/restart tests and audit**

Run: `uv run python -m pytest tests/integration/r2/narrative/test_canon_concurrency.py -q`

Expected: all tests pass on the local SQLite fallback.

Run: `uv run python scripts/audit_tests.py --check`

Expected: exit 0.

- [ ] **Step 7: Commit hardening tests and seams**

```bash
git add r2/narrative/canon_transaction.py tests/integration/r2/narrative/test_canon_concurrency.py
git commit -m "test(r2): prove canon atomicity and concurrency"
```

---

### Task 10: Executable Canon integrity checker

**Files:**
- Create: `r2/narrative/integrity.py`
- Modify: `r2/narrative/__init__.py`
- Test: `tests/integration/r2/narrative/test_canon_integrity.py`

**Interfaces:**
- Consumes: `CanonReadRepositoryPort`, hashing, branch/version/delta snapshots.
- Produces: `CanonIntegrityFinding`, `CanonIntegrityReport`, and `CanonIntegrityChecker(repository).check_scope(*, project_name: str, user_id: str) -> CanonIntegrityReport`.

- [ ] **Step 1: Write failing valid-fixture and corrupt-pointer tests**

```python
async def test_valid_scope_passes_every_integrity_rule(session_factory) -> None:
    await seed_main_and_pinned_child(session_factory)
    report = await run_checker(session_factory)
    assert report.ok is True
    assert report.findings == ()


async def test_cross_branch_head_pointer_fails_closed(session_factory) -> None:
    await seed_two_branches(session_factory)
    await corrupt_head_to_other_branch(session_factory)
    report = await run_checker(session_factory)
    assert [item.rule_id for item in report.findings] == ["M5A_HEAD_BRANCH_MISMATCH"]
```

- [ ] **Step 2: Run integrity tests to verify RED**

Run: `uv run python -m pytest tests/integration/r2/narrative/test_canon_integrity.py -q`

Expected: collection fails because the checker does not exist.

- [ ] **Step 3: Implement deterministic integrity rules**

```python
INTEGRITY_RULE_ORDER = (
    "M5A_HEAD_MISSING",
    "M5A_HEAD_SCOPE_MISMATCH",
    "M5A_HEAD_BRANCH_MISMATCH",
    "M5A_HEAD_NOT_LATEST",
    "M5A_VERSION_GAP",
    "M5A_PARENT_MISSING",
    "M5A_PARENT_SCOPE_MISMATCH",
    "M5A_PARENT_BRANCH_MISMATCH",
    "M5A_VERSION_PARENT_MISMATCH",
    "M5A_DELTA_LINK_MISMATCH",
    "M5A_HASH_VERSION_UNSUPPORTED",
    "M5A_AUTHORITATIVE_HASH_MISMATCH",
)
```

Check each branch independently, collect rather than repair, sort by rule order then affected IDs, and never consult a projection as authority. A null head requires zero local versions; a non-null head must be the highest contiguous version. Narrative version 1 points to the pinned parent, later versions point locally, and every version's delta base equals its parent.

- [ ] **Step 4: Add corruption coverage for every logical pointer and hash**

Corrupt rows only through explicit SQL in the test transaction. Cover missing/wrong-scope/wrong-branch head, parent mismatch, version gap, delta/version linkage, unsupported selectors, and authoritative hash mismatch. Assert the checker leaves bytes unchanged.

- [ ] **Step 5: Run integrity tests and audit**

Run: `uv run python -m pytest tests/integration/r2/narrative/test_canon_integrity.py -q`

Expected: all tests pass.

Run: `uv run python scripts/audit_tests.py --check`

Expected: exit 0.

- [ ] **Step 6: Commit the checker**

```bash
git add r2/narrative/integrity.py r2/narrative/__init__.py tests/integration/r2/narrative/test_canon_integrity.py
git commit -m "feat(r2): verify canon authority integrity"
```

---

### Task 11: Architecture fitness, PostgreSQL acceptance, and evidence

**Files:**
- Create: `tests/unit/r2/narrative/test_canon_architecture_boundaries.py`
- Modify: `pyproject.toml`
- Create: `docs/r2/evidence/R2_M5A_FINAL_VERIFICATION.md`

**Interfaces:**
- Consumes: frozen contract registry, completed M5A implementation, existing AST/import-linter patterns, and PostgreSQL-compatible fixtures.
- Produces: executable one-authority/session-boundary rules and a revision-bound acceptance record.

- [ ] **Step 1: Write failing architecture tests**

```python
def test_only_transaction_service_calls_canon_authority_writes() -> None:
    allowed = {"r2/narrative/canon_transaction.py"}
    offenders = files_calling_any(
        ("insert_delta", "insert_version", "advance_head"),
        roots=(REPO / "r2", REPO / "server", REPO / "lib"),
    ) - allowed - {"lib/db/repositories/canon_repo.py"}
    assert offenders == set()


def test_repository_and_resolver_do_not_own_transactions() -> None:
    for rel_path in ("lib/db/repositories/canon_repo.py", "r2/narrative/canon_resolver.py"):
        code = code_without_docstrings(rel_path)
        for forbidden in ("async_sessionmaker(", ".commit(", ".rollback("):
            assert forbidden not in code
```

Also assert no router, worker, Agent tool, Canvas, production, or donor module imports `CanonWriteRepositoryPort`, `CanonRepository`, or `SqlAlchemyCanonUnitOfWork`; Canon modules do not import or instantiate `ProductionApprovalService`; projection code cannot touch branch heads/deltas/versions; `r2.contracts.narrative` remains provider/ORM/endpoint neutral; the frozen registry still names `CanonTransactionService` for authoritative Canon contracts.

- [ ] **Step 2: Run architecture tests to verify RED**

Run: `uv run python -m pytest tests/unit/r2/narrative/test_canon_architecture_boundaries.py -q`

Expected: the import-linter contract assertion fails before `pyproject.toml` is updated.

- [ ] **Step 3: Add the R2 narrative-core import contract**

```toml
[[tool.importlinter.contracts]]
name = "R2 narrative core does not depend on Host persistence"
type = "forbidden"
source_modules = ["r2.narrative"]
forbidden_modules = [
    "lib.db",
    "lib.db.models",
    "lib.db.repositories",
]
```

Do not add `ignore_imports`. Keep SQLAlchemy and session types out of `r2/narrative`; the Host adapter implements the protocols. `server` is not an import-linter root package, so the architecture test enforces that boundary with AST import inspection instead of weakening or expanding the existing root-package configuration.

- [ ] **Step 4: Run focused M5A and architecture gates**

Run: `uv run python -m pytest tests/unit/r2/contracts/test_narrative.py tests/unit/r2/narrative tests/integration/r2/narrative tests/integration/lib/db/repositories/test_canon_repo.py tests/integration/lib/db/migrations/test_alembic_canon_authority.py -q`

Expected: all selected tests pass.

Run: `uv run lint-imports`

Expected: all contracts kept.

Run: `uv run python scripts/audit_tests.py --check`

Expected: exit 0.

- [ ] **Step 5: Commit architecture gates before acceptance runs**

```bash
git add tests/unit/r2/narrative/test_canon_architecture_boundaries.py pyproject.toml
git commit -m "test(r2): enforce M5A canon boundaries"
```

- [ ] **Step 6: Run the complete backend quality gate**

Run each command separately and record its exit code:

```bash
uv run ruff check .
uv run ruff format --check .
uv run basedpyright --warnings
uv run lint-imports
uv run deptry lib server alembic scripts tests r2
uv run python scripts/audit_tests.py --check
uv run python -m pytest -n 4 --dist loadfile
```

Expected: every command exits 0. If formatting fails, run `uv run ruff format .`, inspect the diff, rerun affected focused tests, and repeat this gate.

- [ ] **Step 7: Start a disposable PostgreSQL 16 acceptance database**

Use container `r2-m5a-postgres`, label `com.content-production-os.r2-m5a=1`, host port `55435`, database `arcreel_r2_m5a`, user `arcreel`, and a local-only password. Refuse to remove or reuse a container unless that exact ownership label is present.

```bash
docker run -d --rm --name r2-m5a-postgres --label com.content-production-os.r2-m5a=1 -e POSTGRES_USER=arcreel -e POSTGRES_PASSWORD=r2-m5a-local-only -e POSTGRES_DB=arcreel_r2_m5a -p 127.0.0.1:55435:5432 postgres:16-alpine
docker exec r2-m5a-postgres pg_isready -U arcreel -d arcreel_r2_m5a
```

Expected: `pg_isready` reports accepting connections. This is disposable test infrastructure; do not point `DATABASE_URL` at an operating database.

- [ ] **Step 8: Run PostgreSQL migration and M5A acceptance**

With `DATABASE_URL=postgresql+asyncpg://arcreel:r2-m5a-local-only@127.0.0.1:55435/arcreel_r2_m5a`, run separately:

```bash
uv run alembic upgrade head
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
uv run python -m pytest -v -m "uses_db and not sqlite_only" -n 4 --dist loadfile
uv run python -m pytest -q tests/integration/r2/narrative/test_canon_concurrency.py tests/integration/r2/narrative/test_canon_integrity.py tests/integration/r2/narrative/test_canon_resolver.py
uv run alembic current
uv run alembic heads
```

Expected: all commands exit 0; current and heads both report `5a7c4a0e0001`; same-branch concurrency has one winner; different branches both win; projection race converges; restart and integrity tests pass.

- [ ] **Step 9: Capture the revision-bound evidence document**

Populate `docs/r2/evidence/R2_M5A_FINAL_VERIFICATION.md` with observed values only:

```markdown
# R2 M5A Final Verification

- Implementation revision: output of `git rev-parse HEAD` before this evidence-only commit
- Migration current/head: exact `uv run alembic current` and `uv run alembic heads` output
- PostgreSQL: exact `SELECT version()` output, image ID from `docker inspect`, container name, ownership label, port, and database name
- Focused M5A tests: command, collected/passed count, exit code
- Full backend tests: command, passed/skipped/deselected count, exit code
- Static gates: every command and exit code
- Recovery: projection deletion/rebuild, authoritative corruption failure, new-engine restart results
- Concurrency: same-branch and different-branch test names and results
- Scope exclusions: no M5B/M5C, Canvas, provider, production activation, operating migration, push, or publish action
```

Redact the database password. Include failures and their resolution if any gate required a code change; after any code change, rerun the affected focused tests and the complete backend gate before recording PASS.

- [ ] **Step 10: Stop the disposable database and verify ownership before removal**

Run: `docker inspect -f '{{ index .Config.Labels "com.content-production-os.r2-m5a" }}' r2-m5a-postgres`

Expected: exactly `1`.

Run: `docker rm -f r2-m5a-postgres`

Expected: container name is printed and no operating database is touched.

- [ ] **Step 11: Commit final evidence**

```bash
git add docs/r2/evidence/R2_M5A_FINAL_VERIFICATION.md
git commit -m "docs(r2): record M5A canon verification"
```

- [ ] **Step 12: Verify the final branch state**

Run: `git status --short`

Expected: no output.

Run: `git log --oneline --decorate -12`

Expected: the M5A commits are present after the accepted M4 integration point, ending with the evidence-only commit.
