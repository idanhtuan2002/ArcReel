# R2-M0 Host Fork Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a reproducible R2 Host fork from the verified ArcReel v0.29.0 baseline, running PostgreSQL-first and carrying frozen R2 architecture/decision gates without yet adding R2 domain features.

**Architecture:** Keep ArcReel's runtime architecture intact. Add only repository/bootstrap metadata, frozen R2 design inputs, reproducibility checks, architecture-policy tests, PostgreSQL baseline verification, and a machine-readable known-blocker gate for `R2-HOST-001`. M0 must end with a clean green baseline and no Canon, OpenMontage, take, Method Router, or new Artifact Manifest implementation.

**Tech Stack:** Git, ArcReel v0.29.0, Python 3.12+, `uv`, pytest, SQLAlchemy/Alembic, PostgreSQL 16, Docker Compose, Node 20+, pnpm, FFmpeg.

**Spec:** `docs/r2/R2_01_FROZEN_ARCHITECTURE.md` through `docs/r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md`

## Global Constraints

- ArcReel baseline tag: `v0.29.0`.
- ArcReel verified baseline SHA: `6ddedc775e7fe5f398b10081ab741985f7dceda7`.
- Development database baseline: PostgreSQL.
- Do not rewrite the ArcReel generation queue, task state machine, provider backend abstraction, Artifact Manifest core, currency engine, recovery machinery, or cost accounting in M0.
- Do not add Canon, OpenMontage, take, Jellyfish, DramaClaw, Butterfly, or new UI behavior in M0.
- Do not create a second artifact registry or second general media queue.
- `R2-HOST-001` remains a production blocker; M0 registers and tests that the blocker is visible, but does not implement the H1 runtime fix.
- Backend tests use ArcReel's existing pytest conventions. External-service E2E is not required.
- Before modifying existing ArcReel code, use codebase-memory-MCP for symbol/dependency/blast-radius discovery, then targeted reads.
- All commits must keep the working tree reviewable and milestone-scoped.

---

## Target files for M0

Create:

```text
docs/r2/
  00_R2_FREEZE_INDEX.md
  R2_01_FROZEN_ARCHITECTURE.md
  R2_02_FROZEN_RESPONSIBILITY_MATRIX.md
  R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md
  R2_03_CONTRACT_REGISTRY.json
  R2_04_CONSOLIDATED_DECISION_LOG.md
  R2_04_DECISION_REGISTRY.json
  R2_04_SUPERSESSION_MAP.json
  R2_04_OPEN_DECISIONS.md
  R2_05_FROZEN_HOST_HARDENING_REQUIREMENTS.md
  R2_05_HOST_HARDENING_REGISTRY.json
  R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md
  R2_06_ROADMAP_REGISTRY.json

scripts/r2/
  verify_baseline.py
  verify_frozen_registries.py
  verify_postgres_baseline.sh

tests/architecture/
  test_r2_frozen_registries.py
  test_r2_known_blockers.py

r2/
  __init__.py
  bootstrap.py
```

Modify only if repository layout requires it:

```text
pyproject.toml
.gitignore
CONTRIBUTING.md
.github/workflows/<existing-tests-workflow>.yml
```

Do not create the full future `r2/contracts`, `r2/authority`, or `r2/adapters` trees in M0.

---

### Task 1: Create the isolated R2 fork and upstream topology

**Goal:** Establish the exact verified ArcReel baseline and a safe upstream-sync topology.

**Inputs:**
- upstream repository `https://github.com/ArcReel/ArcReel.git`
- tag `v0.29.0`
- expected SHA `6ddedc775e7fe5f398b10081ab741985f7dceda7`

**Outputs:**
- new project repository/worktree;
- `origin` points to the R2 fork;
- `upstream` points to ArcReel;
- baseline branch/tag identity recorded.

**Dependencies:** none.

**Out of Scope:** any source-code feature change.

- [ ] **Step 1: Create an isolated worktree/repository**

Run from the user's project parent directory:

```bash
git clone https://github.com/ArcReel/ArcReel.git content-production-os
cd content-production-os
git fetch --tags origin
git checkout --detach v0.29.0
test "$(git rev-parse HEAD)" = "6ddedc775e7fe5f398b10081ab741985f7dceda7"
git switch -c r2/main
```

Expected:
- SHA assertion succeeds;
- branch is `r2/main`.

- [ ] **Step 2: Configure upstream/fork remotes**

After the user creates or identifies the destination fork URL:

```bash
git remote rename origin upstream
git remote add origin <R2_FORK_GIT_URL>
git remote -v
```

Expected:
- `upstream` = ArcReel public repository;
- `origin` = R2 fork.

Do not invent the fork URL.

- [ ] **Step 3: Record baseline identity**

Create `docs/r2/HOST_BASELINE.txt`:

```text
upstream=https://github.com/ArcReel/ArcReel.git
tag=v0.29.0
sha=6ddedc775e7fe5f398b10081ab741985f7dceda7
branch=r2/main
```

- [ ] **Step 4: Verify no source change**

Run:

```bash
git status --short
git diff --stat v0.29.0 -- .
```

Expected:
- only `docs/r2/HOST_BASELINE.txt` is new;
- no ArcReel source file changed.

- [ ] **Step 5: Commit**

```bash
git add docs/r2/HOST_BASELINE.txt
git commit -m "chore(r2): pin verified ArcReel host baseline"
```

**Acceptance Criteria:**
- exact SHA verified;
- safe two-remote topology established;
- no feature code changed.

**Tests:** exact SHA assertion and clean diff review above.

---

### Task 2: Import the frozen R2 design package as repository authority

**Goal:** Put R2.1–R2.6 frozen decisions beside the code so agents/CI have a canonical source.

**Inputs:**
- approved R2 freeze package.

**Outputs:**
- `docs/r2/*` frozen files.

**Dependencies:** Task 1.

**Out of Scope:** editing the frozen content while copying it.

- [ ] **Step 1: Copy approved artifacts**

Copy exactly the approved files into `docs/r2/`:

```text
00_R2_FREEZE_INDEX.md
R2_01_FROZEN_ARCHITECTURE.md
R2_02_FROZEN_RESPONSIBILITY_MATRIX.md
R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md
R2_03_CONTRACT_REGISTRY.json
R2_04_CONSOLIDATED_DECISION_LOG.md
R2_04_DECISION_REGISTRY.json
R2_04_SUPERSESSION_MAP.json
R2_04_OPEN_DECISIONS.md
R2_05_FROZEN_HOST_HARDENING_REQUIREMENTS.md
R2_05_HOST_HARDENING_REGISTRY.json
R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md
R2_06_ROADMAP_REGISTRY.json
```

- [ ] **Step 2: Validate JSON syntax**

Run:

```bash
python -m json.tool docs/r2/R2_03_CONTRACT_REGISTRY.json >/dev/null
python -m json.tool docs/r2/R2_04_DECISION_REGISTRY.json >/dev/null
python -m json.tool docs/r2/R2_04_SUPERSESSION_MAP.json >/dev/null
python -m json.tool docs/r2/R2_05_HOST_HARDENING_REGISTRY.json >/dev/null
python -m json.tool docs/r2/R2_06_ROADMAP_REGISTRY.json >/dev/null
```

Expected: all exit 0.

- [ ] **Step 3: Scan for unfinished placeholders**

Run:

```bash
grep -RInE '\b(TODO|TBD|FIXME)\b' docs/r2 || true
```

Expected: no matches in frozen R2 documents.

- [ ] **Step 4: Commit**

```bash
git add docs/r2
git commit -m "docs(r2): import frozen architecture package"
```

**Acceptance Criteria:**
- all frozen R2.1–R2.6 files exist;
- JSON registries parse;
- no placeholder markers.

**Tests:** JSON parse + placeholder scan.

---

### Task 3: Add a minimal R2 bootstrap module

**Goal:** Create only the package root needed by later milestones, without prematurely scaffolding domain subsystems.

**Files:**
- Create: `r2/__init__.py`
- Create: `r2/bootstrap.py`
- Test: `tests/architecture/test_r2_frozen_registries.py`

**Interfaces:**
- Produces: `r2.bootstrap.r2_root() -> pathlib.Path`
- Produces: `r2.bootstrap.frozen_docs_dir() -> pathlib.Path`

**Dependencies:** Task 2.

**Out of Scope:** contracts, Canon, adapters, provider code.

- [ ] **Step 1: Write the failing test**

Create `tests/architecture/test_r2_frozen_registries.py`:

```python
from r2.bootstrap import frozen_docs_dir


def test_frozen_docs_dir_contains_decision_registry():
    path = frozen_docs_dir()
    assert (path / "R2_04_DECISION_REGISTRY.json").is_file()
```

- [ ] **Step 2: Run the test and verify RED**

```bash
uv run python -m pytest -q \
  tests/architecture/test_r2_frozen_registries.py::test_frozen_docs_dir_contains_decision_registry
```

Expected: import failure because `r2.bootstrap` does not exist.

- [ ] **Step 3: Implement the minimal module**

Create `r2/__init__.py` with no side effects.

Create `r2/bootstrap.py`:

```python
from pathlib import Path


def r2_root() -> Path:
    return Path(__file__).resolve().parents[1]


def frozen_docs_dir() -> Path:
    return r2_root() / "docs" / "r2"
```

- [ ] **Step 4: Run GREEN**

```bash
uv run python -m pytest -q tests/architecture/test_r2_frozen_registries.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add r2 tests/architecture/test_r2_frozen_registries.py
git commit -m "feat(r2): add minimal architecture bootstrap"
```

**Acceptance Criteria:**
- no domain logic added;
- bootstrap locates frozen docs deterministically.

---

### Task 4: Implement frozen-registry integrity checks

**Goal:** Make frozen decision/contract ownership mechanically verifiable.

**Files:**
- Create: `scripts/r2/verify_frozen_registries.py`
- Modify: `tests/architecture/test_r2_frozen_registries.py`

**Interfaces:**
- Produces: `verify() -> list[str]`, empty list means pass.
- Consumes: frozen JSON registries in `docs/r2`.

**Dependencies:** Task 3.

**Out of Scope:** introspecting not-yet-implemented R2 contracts.

- [ ] **Step 1: Add failing tests**

Append:

```python
import json

from scripts.r2.verify_frozen_registries import verify


def test_frozen_registry_integrity():
    assert verify() == []


def test_every_authoritative_contract_has_one_commit_authority():
    data = json.loads((frozen_docs_dir() / "R2_03_CONTRACT_REGISTRY.json").read_text())
    for item in data["contracts"]:
        if item["authority"] not in {
            "NON_AUTHORITATIVE",
            "PROPOSAL",
            "PROPOSAL_TO_NARRATIVE_AUTHORITY",
            "CROSS_AUTHORITY_LINEAGE",
            "REVIEW_PLANE",
        }:
            assert item.get("commit_authority")
```

- [ ] **Step 2: Verify RED**

```bash
uv run python -m pytest -q tests/architecture/test_r2_frozen_registries.py
```

Expected: import failure for `scripts.r2.verify_frozen_registries`.

- [ ] **Step 3: Implement verifier**

Create package marker if required by repository Python import behavior:

```text
scripts/r2/__init__.py
```

Create `scripts/r2/verify_frozen_registries.py` that:
1. loads all five registry JSON files;
2. rejects duplicate decision IDs;
3. rejects invalid decision statuses;
4. validates all supersession targets exist;
5. verifies authoritative contracts have a commit authority;
6. verifies `SceneSpec` and `ShotSpec` list forbidden fields:
   `provider`, `model`, `endpoint`, `payload`, `provider_job_id`;
7. verifies roadmap dependency order is acyclic;
8. returns human-readable errors.

Do not inspect provider runtime or implement domain classes in this task.

- [ ] **Step 4: Run tests**

```bash
uv run python -m pytest -q tests/architecture/test_r2_frozen_registries.py
python scripts/r2/verify_frozen_registries.py
```

Expected:
- tests PASS;
- script exits 0 and prints a pass summary.

- [ ] **Step 5: Commit**

```bash
git add scripts/r2 tests/architecture
git commit -m "test(r2): enforce frozen architecture registries"
```

**Acceptance Criteria:**
- frozen decision/contract files are machine checked;
- invalid authority/supersession changes fail CI locally.

---

### Task 5: Register the H1 known production blocker

**Goal:** Prevent `R2-HOST-001` from disappearing during implementation before the runtime fix is scheduled.

**Files:**
- Create: `tests/architecture/test_r2_known_blockers.py`
- Modify: `scripts/r2/verify_frozen_registries.py`

**Interfaces:**
- Consumes: `R2_05_HOST_HARDENING_REGISTRY.json`
- Produces: architecture test enforcing H1 severity.

**Dependencies:** Task 4.

**Out of Scope:** fixing ArcReel execution identity.

- [ ] **Step 1: Write failing test**

```python
import json

from r2.bootstrap import frozen_docs_dir


def test_execution_identity_is_registered_as_production_blocker():
    data = json.loads((frozen_docs_dir() / "R2_05_HOST_HARDENING_REGISTRY.json").read_text())
    h1 = next(item for item in data["requirements"] if item["id"] == "H1")
    assert h1["severity"] == "PRODUCTION_BLOCKER"
    assert h1["decision_ref"] == "R2-HOST-001"
```

Temporarily change neither registry nor test fixture. If imported freeze content is correct, this may already be GREEN; in that case first mutate a temporary copy in the test to prove the verifier rejects a downgraded severity.

- [ ] **Step 2: Add negative verifier test**

Create a temp registry with:

```json
{"id":"H1","severity":"ADVISORY","decision_ref":"R2-HOST-001"}
```

Assert the verifier returns an error containing `H1`.

- [ ] **Step 3: Extend verifier**

Require:
- H1 exists;
- `severity == PRODUCTION_BLOCKER`;
- `decision_ref == R2-HOST-001`.

- [ ] **Step 4: Run tests**

```bash
uv run python -m pytest -q tests/architecture/test_r2_known_blockers.py
uv run python -m pytest -q tests/architecture
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/r2 tests/architecture
git commit -m "test(r2): preserve execution identity production blocker"
```

**Acceptance Criteria:**
- no M0/M1 change can silently downgrade H1.

---

### Task 6: Create reproducible ArcReel baseline verification

**Goal:** Turn the R1.8 verified baseline into a repository command that can be rerun after fork creation.

**Files:**
- Create: `scripts/r2/verify_baseline.py`
- Test: `tests/architecture/test_r2_baseline_metadata.py`

**Interfaces:**
- Consumes: `docs/r2/HOST_BASELINE.txt`
- Produces: nonzero exit on SHA/tag/upstream mismatch.

**Dependencies:** Task 2.

**Out of Scope:** upstream merge automation.

- [ ] **Step 1: Write failing unit tests**

Create tests using a temporary git repository and baseline file:
- exact SHA accepted;
- wrong SHA rejected;
- missing baseline key rejected.

Do not run tests against the developer's actual `.git` state for unit cases.

- [ ] **Step 2: Implement parser/verifier**

`verify_baseline.py` should:
- parse key/value baseline file;
- invoke `git rev-parse HEAD`;
- verify exact SHA;
- verify upstream URL when requested;
- never modify git state.

- [ ] **Step 3: Run unit tests**

```bash
uv run python -m pytest -q tests/architecture/test_r2_baseline_metadata.py
```

Expected: PASS.

- [ ] **Step 4: Run against actual fork**

```bash
python scripts/r2/verify_baseline.py
```

Expected: PASS on the initial M0 baseline.

- [ ] **Step 5: Commit**

```bash
git add scripts/r2/verify_baseline.py tests/architecture/test_r2_baseline_metadata.py
git commit -m "test(r2): verify pinned host baseline"
```

**Acceptance Criteria:**
- baseline drift is explicit;
- verifier is read-only.

---

### Task 7: Verify PostgreSQL-first development baseline

**Goal:** Prove the fork still migrates and starts against isolated PostgreSQL after M0 repository changes.

**Files:**
- Create: `scripts/r2/verify_postgres_baseline.sh`
- Reuse: ArcReel's existing Alembic/server entrypoints.
- Reuse: isolated Docker PostgreSQL.

**Dependencies:** Tasks 1–6.

**Out of Scope:** creating a new DB abstraction.

- [ ] **Step 1: Write shell syntax/testability guard**

The script must use:

```bash
set -Eeuo pipefail
```

and configurable values:

```bash
R2_PG_PORT="${R2_PG_PORT:-55432}"
R2_BACKEND_PORT="${R2_BACKEND_PORT:-12418}"
```

It must bind services to localhost.

- [ ] **Step 2: Start isolated PostgreSQL**

Use a dedicated Compose project/container/volume name so it cannot reuse the user's PIOS DB.

Example environment:

```text
POSTGRES_USER=arcreel
POSTGRES_PASSWORD=r2-local-only
POSTGRES_DB=arcreel_r2_m0
```

- [ ] **Step 3: Run migrations**

From the ArcReel fork:

```bash
uv sync
uv run alembic upgrade head
uv run alembic current
```

Expected:
- migration succeeds;
- current revision is head.

- [ ] **Step 4: Start backend localhost-only and check health**

Use ArcReel's documented server command/entrypoint discovered from the pinned source.

Do not guess the module path: first inspect `README`, `pyproject.toml`, server package, and the R1.8 launch script.

Health assertion:

```bash
curl -fsS "http://127.0.0.1:${R2_BACKEND_PORT}/health"
```

- [ ] **Step 5: Restart the backend against the same DB/data**

Stop only the benchmark backend process, restart it, and repeat `/health`.

Expected: PASS.

- [ ] **Step 6: Stop isolated services cleanly**

The verification script must trap EXIT and stop only resources it created.

- [ ] **Step 7: Commit**

```bash
git add scripts/r2/verify_postgres_baseline.sh
git commit -m "test(r2): verify PostgreSQL host baseline"
```

**Acceptance Criteria:**
- PostgreSQL migration passes;
- backend health passes before/after restart;
- no existing project DB/container is modified.

---

### Task 8: Run the frozen M0 regression gate

**Goal:** Prove M0 changed repository/bootstrap policy only and did not regress ArcReel Host behavior.

**Dependencies:** Tasks 1–7.

**Out of Scope:** external-provider E2E.

- [ ] **Step 1: Run R2 architecture tests**

```bash
uv run python -m pytest -q tests/architecture
python scripts/r2/verify_frozen_registries.py
python scripts/r2/verify_baseline.py
```

Expected: PASS.

- [ ] **Step 2: Run ArcReel focused host tests from R1.8**

Run the same pinned focused areas validated in R1.8, including:

```text
tests/integration/lib/test_artifact_manifest_storage.py
tests/integration/lib/test_speech_artifact_provenance_integration.py
tests/integration/lib/test_visual_artifact_provenance.py
tests/integration/lib/test_workflow_plan_adapters.py
tests/integration/lib/test_workflow_state.py
tests/integration/server/services/test_video_artifact_currency.py
tests/integration/server/services/test_workflow_planner.py
tests/unit/lib/test_artifact_manifest.py
tests/unit/lib/test_artifact_provenance.py
tests/unit/lib/test_speech_artifact_provenance.py
tests/unit/lib/test_workflow_plan.py
tests/unit/server/services/test_video_batch_admission.py
```

Command:

```bash
uv run python -m pytest -q <the paths above>
```

Expected baseline: all selected tests pass. R1.8 reference result was 349 passed; if upstream source is still exact pinned SHA but collected count differs, stop and inspect test selection before accepting.

- [ ] **Step 3: Run ArcReel audit gate**

```bash
uv run python scripts/audit_tests.py --check
```

Expected: zero violations.

ArcReel's testing guidance treats external-service tests separately from the default unit/integration gate, so do not add provider spend here. citeturn182889search0

- [ ] **Step 4: Run PostgreSQL baseline verification**

```bash
bash scripts/r2/verify_postgres_baseline.sh
```

Expected: migration + health + restart PASS.

- [ ] **Step 5: Review diff against baseline**

```bash
git diff --stat v0.29.0...HEAD
git diff v0.29.0...HEAD -- \
  lib server alembic
```

Expected:
- no ArcReel runtime implementation changes in M0 unless required solely for packaging/import hygiene and individually justified;
- primarily docs, `r2/bootstrap.py`, architecture tests and verification scripts.

- [ ] **Step 6: Record M0 verification**

Create:

```text
docs/r2/evidence/R2_M0_VERIFICATION.md
```

Record exact:
- HEAD SHA;
- Python/Node/uv/pnpm versions;
- PostgreSQL migration head;
- architecture test result;
- focused test count;
- audit gate result;
- health/restart result;
- known blocker H1 still open.

Do not write “PASS” for a command that was not actually run.

- [ ] **Step 7: Commit evidence**

```bash
git add docs/r2/evidence/R2_M0_VERIFICATION.md
git commit -m "test(r2): record M0 host foundation verification"
```

**Acceptance Criteria:**
- all M0 gates green;
- H1 remains explicitly open;
- no later-phase functionality leaked into M0;
- repository is ready for R2-M1 Contract Kernel.

---

## M0 Final Exit Gate

M0 is complete only if all are true:

```text
[ ] exact ArcReel v0.29.0 baseline provenance recorded
[ ] origin/upstream topology correct
[ ] frozen R2.1–R2.6 docs imported
[ ] frozen registry verifier PASS
[ ] H1 blocker-presence test PASS
[ ] baseline verifier PASS
[ ] PostgreSQL migration PASS
[ ] backend health PASS
[ ] backend restart health PASS
[ ] R1.8 focused Host regression PASS
[ ] ArcReel audit_tests.py --check PASS
[ ] no external provider spend
[ ] no Canon/Director/MethodRouter/ArtifactBridge implementation
[ ] working tree clean after final evidence commit
```

## M0 → M1 handoff

M1 may begin only after M0 evidence is reviewed.

M1's first implementation work is the provider-neutral contract kernel. It must not begin by modifying ArcReel Artifact Manifest; Artifact Bridge belongs to M2.
