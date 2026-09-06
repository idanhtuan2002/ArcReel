# R2-M3 Golden A / General Content Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify the first real factual/general-content R2 production vertical slice from frozen factual authority through validated SceneSpec/ShotSpec, mixed local production, the real M2 Artifact Bridge/ApprovedMaster path, and a real FFmpeg-inspectable final MP4.

**Architecture:** M3 adds only the minimum factual/script contracts plus Golden-A-specific orchestration required by the approved design. It reuses M2's Artifact Manifest/ApprovedMaster integration and existing ArcReel version/recovery machinery, keeps reusable production intelligence deferred to M4, and uses Task 0 seam evidence to select a directly callable OpenMontage donor path or the already-approved deterministic adapter-compatible fallback.

**Tech Stack:** Python 3.13 via `uv`; Pydantic v2; existing R2 contracts and M2 production bridge; ArcReel Artifact Manifest/VersionManager; FFmpeg/ffprobe; pytest; PostgreSQL baseline verification; JSON/Markdown evidence.

**Spec:** `docs/superpowers/specs/2026-09-06-r2-m3-golden-a-general-content-design.md`

## Global Constraints

- Branch remains `r2/main`; completed M2 baseline is `9cc04edd88fe8d96e0610c2d9381f09547da0239`.
- Architecture R2.1–R2.7 remains frozen.
- Golden A topic is **“Git: Working Tree → Index → Commit hoạt động như thế nào”**, target approximately 60–90 seconds.
- Regression is offline from a frozen factual fixture; live Internet is not a Golden A test dependency.
- Required production methods are `REUSE`, `DETERMINISTIC`, and `COMPOSITE`.
- `SCREEN_CAPTURE` is optional only if Task 0 proves a stable reproducible local seam.
- No paid provider or `GENERATED_VIDEO` is required; baseline external provider cost is `0`.
- Stable SceneSpec/ShotSpec remain provider/model/endpoint/API-payload neutral.
- ProductionBinding remains the semantic→production bridge.
- Persist direct dependency snapshots only; never persist a transitive dependency graph.
- ArcReel Artifact Manifest remains the single artifact authority; no parallel R2 artifact registry.
- ArcReel remains the single runtime/media queue authority.
- Candidate success never implies ApprovedMaster; explicit promotion is required.
- Failed or unapproved later candidates preserve the prior usable ApprovedMaster.
- Execution identity/cost does not participate in semantic content currency.
- Do not implement generic M4 `DirectorAdapter`, `MethodRouterService`, `CapabilityRegistry`, `PromptCompilerService`, general VisualIdentity, or Jellyfish readiness.
- Do not introduce Canon/Narrative/Adaptation implementation in M3.
- `R2-HOST-001` / H1 remains OPEN / PRODUCTION_BLOCKER.
- Initial M3 Host runtime modification allowlist is empty.
- No M3 DB migration unless Task 0 proves an executable blocker and the plan is explicitly amended before code.
- codebase-memory-MCP is consulted before architecture/symbol/dependency/impact work; targeted reads follow.
- Every production task follows RED → minimal GREEN → focused regression → diff review → commit.
- No push before Task 9 final verification.

---

# File Structure

Planned new files:

```text
r2/contracts/
  factual.py
  script.py

r2/m3/
  __init__.py
  factual_fixture.py
  director.py
  preparation.py
  local_production.py
  host_integration.py
  composition.py
  lineage.py
  golden_a.py

r2/m3/fixtures/
  golden_a_git.json
  assets/reused_terminal_frame.svg

tests/unit/r2/contracts/
  test_factual.py
  test_script.py

tests/unit/r2/m3/
  test_factual_fixture.py
  test_director.py
  test_preparation.py
  test_local_production.py
  test_lineage.py
  test_m3_architecture_boundaries.py

tests/integration/r2/m3/
  test_host_integration.py
  test_selective_invalidation.py
  test_composition.py
  test_golden_a.py

docs/r2/evidence/
  R2_M3_SEAM_DISCOVERY.json
  R2_M3_SEAM_DISCOVERY.md
  R2_M3_VERIFICATION_<timestamp>.json
  R2_M3_VERIFICATION_<timestamp>.md
```

Expected existing export file after Task 0 confirmation:

```text
r2/contracts/__init__.py
```

Initial M3 Host modification allowlist:

```text
lib/      NONE
server/   NONE
alembic/  NONE
```

---

# Checkpoint Map

```text
Checkpoint A  Task 0      Exact seam discovery
Checkpoint B  Tasks 1–3   Factual contracts + fixture + direction
Checkpoint C  Tasks 4–6   Preparation + local production + real M2 Host bridge
Checkpoint D  Tasks 7–8   Real final MP4 + lineage/invalidation/restart
Checkpoint E  Task 9      Architecture gates + final evidence + push
```

---

### Task 0: Exact M3 Seam Discovery

**Files:**
- Create: `docs/r2/evidence/R2_M3_SEAM_DISCOVERY.json`
- Create: `docs/r2/evidence/R2_M3_SEAM_DISCOVERY.md`
- No production source changes.

**Interfaces:**
- Consumes: completed M2, approved M3 spec, frozen decision registry.
- Produces these machine-readable fields:
  - `contracts_export_path: str`
  - `openmontage_mode: "OPENMONTAGE_CALLABLE" | "FIXTURE_ADAPTER"`
  - `openmontage_module_or_path: str | null`
  - `openmontage_callable: str | null`
  - `composition_mode: "REMOTION_FFMPEG" | "FFMPEG_EXISTING"`
  - `ffmpeg_path: str`
  - `ffprobe_path: str`
  - `artifact_manifest_adapter: str`
  - `r2_artifact_port: str`
  - `version_manager: str`
  - `version_promoter: str`
  - `artifact_key_strategy: str`
  - `cost_provenance_sources: list[str]`
  - `host_patch_allowlist: list[str]`
  - `screen_capture_mode: "AVAILABLE" | "DEFERRED"`

- [ ] **Step 1: Verify the implementation baseline**

Run:

```bash
cd ~/content-production-os
git status --short
git branch --show-current
git rev-parse HEAD
uv run python scripts/r2/verify_frozen_registries.py
uv run python scripts/r2/verify_baseline.py
```

Expected: `r2/main`, clean tree, descendant of completed M2, both verifiers PASS.

- [ ] **Step 2: Query codebase-memory-MCP before source reads**

Query these responsibilities:

```text
R2 contracts public export path
ArtifactManifestEntry / ProjectArtifactManifestAdapter
ArcReelArtifactManifestPort
ProductionApprovalService
ArcReelVersionRestorePromoter
VersionManager.commit_staged_paid_version / restore_version
ArtifactKey constructors/encoding
Remotion composition invocation
FFmpeg export/composition
cost/usage/provenance sources
OpenMontage donor integration or package surface
local screen-capture seam
```

Record concrete symbols, callers/callees and source paths.

- [ ] **Step 3: Run targeted local probes**

```bash
command -v ffmpeg
command -v ffprobe
ffmpeg -version | head -1
ffprobe -version | head -1

find . -maxdepth 4 \( -iname '*openmontage*' -o -iname '*remotion*' \) -print

grep -RIn --exclude-dir=.git --exclude-dir=.venv \
  -E 'ArtifactKey|commit_staged_paid_version|restore_version|ArcReelArtifactManifestPort|ProductionApprovalService' \
  r2 lib server tests | head -240
```

No broader repository reread unless these probes are insufficient.

- [ ] **Step 4: Select the director mode**

Use:

```python
mode = (
    "OPENMONTAGE_CALLABLE"
    if local_openmontage_is_importable_callable_and_usable
    else "FIXTURE_ADAPTER"
)
```

For `OPENMONTAGE_CALLABLE`, record the observed module/path and callable.
For `FIXTURE_ADAPTER`, both donor fields are `null` and the Markdown explains the observed limitation.

- [ ] **Step 5: Select composition and screen-capture modes**

Composition is:
- `REMOTION_FFMPEG` when an existing callable Remotion path is proven; otherwise
- `FFMPEG_EXISTING` when the existing FFmpeg path is the proven production seam.

Screen capture is:
- `AVAILABLE` only when a reproducible local seam is proven;
- otherwise `DEFERRED`.

- [ ] **Step 6: Write seam evidence**

`R2_M3_SEAM_DISCOVERY.json` must contain every interface field listed above plus:
- `schema_version: 1`
- `baseline_head`
- `observed_at`
- `notes: list[str]`

`host_patch_allowlist` starts as `[]`. A non-empty value requires an explicit plan amendment before Task 1.

- [ ] **Step 7: Verify scope**

```bash
git status --short
git diff --check
```

Expected: only the two seam evidence files.

- [ ] **Step 8: Commit Checkpoint A**

```bash
git add docs/r2/evidence/R2_M3_SEAM_DISCOVERY.json \
        docs/r2/evidence/R2_M3_SEAM_DISCOVERY.md
git commit -m "docs(r2): record M3 Golden A seams"
```

**Checkpoint A gate:** seam evidence committed; no production file changed.

---

### Task 1: Minimum Factual Authority + Script Contracts

**Files:**
- Create: `r2/contracts/factual.py`
- Create: `r2/contracts/script.py`
- Modify: `r2/contracts/__init__.py`
- Test: `tests/unit/r2/contracts/test_factual.py`
- Test: `tests/unit/r2/contracts/test_script.py`

**Interfaces:**
- Consumes current M1 `R2ContractModel`, scalar/timestamp conventions, `ContentBasis`, and `ContentBasisType`.
- Produces:

```python
class ClaimStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    RETIRED = "RETIRED"

class SourceRecord(R2ContractModel):
    id: str
    source_type: str
    title: str | None
    origin: str
    captured_at: datetime
    source_fingerprint: str
    provenance: dict[str, JSONValue]

class EvidenceRecord(R2ContractModel):
    id: str
    source_ref: str
    locator: str
    excerpt_or_structured_fact: JSONValue | None
    evidence_type: str
    captured_at: datetime
    provenance: dict[str, JSONValue]

class ResearchPack(R2ContractModel):
    id: str
    version: int
    topic: str
    scope: str
    source_refs: list[str]
    evidence_refs: list[str]
    synthesis: str
    uncertainties: list[str]
    open_questions: list[str]
    provenance: dict[str, JSONValue]

class Claim(R2ContractModel):
    id: str
    version: int
    statement: str
    evidence_refs: list[str]
    confidence: float
    status: ClaimStatus
    provenance: dict[str, JSONValue]

class ClaimLedger(R2ContractModel):
    id: str
    version: int
    research_pack_ref: str
    claims: list[Claim]

class ScriptSection(R2ContractModel):
    id: str
    text: str
    claim_refs: list[str]
    target_duration_seconds: float | None

class ScriptArtifact(R2ContractModel):
    id: str
    version: int
    content_basis: ContentBasis
    sections: list[ScriptSection]
    participants: list[str]
    timing_intent: str
    creative_constraints: list[str]
```

When Task 0 shows a common field is already inherited, Task 1 uses the inherited field rather than redeclaring it.


**Task 1 plan correction (2026-09-06):** Frozen R2.3 `ScriptArtifact`
includes `approval_status`. Checkpoint B binds this field to the single existing
M1 creative-approval enum identified by runtime preflight. No new creative
status family is introduced. This correction supersedes the Task 1 interface
block where that field was accidentally omitted.

- [ ] **Step 1: Write factual RED tests**

Required tests:
- `confidence` is inside `[0, 1]`;
- VERIFIED claim requires evidence;
- ClaimLedger claim IDs are unique;
- refs are non-empty using current M1 conventions;
- timestamps follow current M1 awareness rule.

Example:

```python
def test_verified_claim_requires_evidence():
    with pytest.raises(ValidationError):
        Claim(
            id="CLAIM-001",
            version=1,
            statement="The index is the proposed next commit.",
            evidence_refs=[],
            confidence=1.0,
            status=ClaimStatus.VERIFIED,
            provenance={"fixture": "golden-a"},
        )
```

- [ ] **Step 2: Run factual RED**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/test_factual.py
```

Expected: import/contract failures.

- [ ] **Step 3: Implement factual contracts**

Only the frozen factual shapes and validation above. No web fetch, research agent, DB, vector index or fact-checking runtime.

- [ ] **Step 4: Write ScriptArtifact RED tests**

Required:

```python
def test_script_section_claim_must_exist_in_factual_basis():
    basis = ContentBasis(
        basis_type=ContentBasisType.FACTUAL,
        basis_version="golden-a-v1",
        refs=["research:RP1", "claim:CLAIM-001"],
    )
    with pytest.raises(ValidationError):
        ScriptArtifact(
            id="SCRIPT-GOLDEN-A",
            version=1,
            content_basis=basis,
            sections=[
                ScriptSection(
                    id="SEC-01",
                    text="The index is the proposed next commit.",
                    claim_refs=["CLAIM-999"],
                    target_duration_seconds=20.0,
                )
            ],
            participants=[],
            timing_intent="60-90s explainer",
            creative_constraints=["factual", "concise"],
        )
```

- [ ] **Step 5: Implement script contracts and exports**

Add only factual/script public exports to `r2/contracts/__init__.py`.

- [ ] **Step 6: Run GREEN + M1 regression**

```bash
uv run python -m pytest -q \
  tests/unit/r2/contracts/test_factual.py \
  tests/unit/r2/contracts/test_script.py \
  tests/unit/r2/contracts/
```

- [ ] **Step 7: Commit**

```bash
git diff --check
git add r2/contracts tests/unit/r2/contracts/test_factual.py tests/unit/r2/contracts/test_script.py
git commit -m "feat(r2): add M3 factual and script contracts"
```

---

### Task 2: Frozen Golden A Factual Fixture

**Files:**
- Create: `r2/m3/__init__.py`
- Create: `r2/m3/factual_fixture.py`
- Create: `r2/m3/fixtures/golden_a_git.json`
- Create: `r2/m3/fixtures/assets/reused_terminal_frame.svg`
- Test: `tests/unit/r2/m3/test_factual_fixture.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class GoldenAFactualBundle:
    sources: tuple[SourceRecord, ...]
    evidence: tuple[EvidenceRecord, ...]
    research_pack: ResearchPack
    claim_ledger: ClaimLedger
    script: ScriptArtifact

def load_golden_a_factual_bundle(
    fixture_path: Path | None = None,
) -> GoldenAFactualBundle:
    ...
```

- [ ] **Step 1: Write RED fixture tests**

Assert:
- at least 3 VERIFIED claims;
- every EvidenceRecord source_ref resolves;
- every Claim evidence_ref resolves;
- ResearchPack refs resolve;
- every ScriptSection claim_ref resolves to VERIFIED claim;
- ContentBasis is FACTUAL;
- repeated local loads are equal;
- no network call is made.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest -q tests/unit/r2/m3/test_factual_fixture.py
```

- [ ] **Step 3: Create the frozen Git explainer fixture**

The fixture contains:
- stable source records and origins;
- evidence locators;
- at least 3 claims;
- 3 script sections;
- explicit claim-to-section mapping;
- enough narration text for 60–90 seconds;
- no secrets or live fetch instructions.

- [ ] **Step 4: Implement loader + cross-reference validation**

The loader reads only local JSON and constructs Task 1 contracts.

- [ ] **Step 5: Add `reused_terminal_frame.svg`**

It is a checked-in deterministic local asset with no network references.

- [ ] **Step 6: Run determinism GREEN twice**

```bash
uv run python -m pytest -q tests/unit/r2/m3/test_factual_fixture.py
uv run python -m pytest -q tests/unit/r2/m3/test_factual_fixture.py
```

- [ ] **Step 7: Commit**

```bash
git add r2/m3 tests/unit/r2/m3/test_factual_fixture.py
git commit -m "feat(r2): add Golden A factual fixture"
```

---

### Task 3: Golden A OpenMontage Direction Boundary

**Files:**
- Create: `r2/m3/director.py`
- Test: `tests/unit/r2/m3/test_director.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class GoldenADirectionResult:
    scenes: tuple[SceneSpec, ...]
    shots: tuple[ShotSpec, ...]

class GoldenAOpenMontageBackend(Protocol):
    def direct(self, script: ScriptArtifact) -> GoldenADirectionResult: ...

class GoldenAOpenMontageAdapter:
    def __init__(self, backend: GoldenAOpenMontageBackend) -> None: ...
    def direct(self, script: ScriptArtifact) -> GoldenADirectionResult: ...
```

Concrete backend:
- Task 0 `OPENMONTAGE_CALLABLE` → `CallableOpenMontageBackend`;
- Task 0 `FIXTURE_ADAPTER` → `FixtureOpenMontageBackend`.

- [ ] **Step 1: Write RED boundary tests**

Assert:
- every SceneSpec maps to a script section;
- every ShotSpec maps to one scene;
- at least 4 shots;
- factual ContentBasis remains visible;
- serialized SceneSpec/ShotSpec contain no provider/model/endpoint/API payload fields;
- donor objects never escape the adapter.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest -q tests/unit/r2/m3/test_director.py
```

- [ ] **Step 3: Implement deterministic fallback backend**

Mapping:

```text
SEC-01 → SC01 → SH01
SEC-02 → SC02 → SH02, SH03
SEC-03 → SC03 → SH04
```

Use the exact current M1 SceneSpec/ShotSpec constructor names discovered in Task 0.

- [ ] **Step 4: Implement the direct donor backend only when Task 0 proved it callable**

Translation happens only at the adapter boundary. No donor type is persisted.

- [ ] **Step 5: Run GREEN + production-contract regression**

```bash
uv run python -m pytest -q \
  tests/unit/r2/m3/test_director.py \
  tests/unit/r2/contracts/test_production.py
```

- [ ] **Step 6: Commit Checkpoint B**

```bash
git add r2/m3/director.py tests/unit/r2/m3/test_director.py
git commit -m "feat(r2): add Golden A direction adapter"
```

**Checkpoint B gate:** factual/script contracts, offline fixture and provider-neutral direction all pass; Host runtime unchanged.

---

### Task 4: Golden A Production Preparation and Method Assignment

**Files:**
- Create: `r2/m3/preparation.py`
- Test: `tests/unit/r2/m3/test_preparation.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class GoldenAMethodAssignment:
    target_ref: str
    method: ProductionMethod
    rationale: str

@dataclass(frozen=True)
class GoldenAPreparedShot:
    shot: ShotSpec
    bindings: tuple[ProductionBinding, ...]
    readiness: ProductionReadiness
    method: GoldenAMethodAssignment

class GoldenAProductionPreparation:
    def prepare(
        self,
        shots: Sequence[ShotSpec],
        *,
        reused_asset_ref: str,
    ) -> tuple[GoldenAPreparedShot, ...]:
        ...
```

Baseline:

```text
SH01 → REUSE
SH02 → DETERMINISTIC
SH03 → DETERMINISTIC
SH04 → DETERMINISTIC
FINAL → COMPOSITE (Task 7)
```

- [ ] **Step 1: Write RED tests**

Assert:
- missing required binding → BLOCKED;
- blocked shot cannot proceed;
- SH01 binds the reused SVG and selects REUSE;
- SH02–SH04 select DETERMINISTIC;
- assigned method is allowed by ShotSpec;
- no provider fields are introduced.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest -q tests/unit/r2/m3/test_preparation.py
```

- [ ] **Step 3: Implement Golden-A-specific preparation**

Do not create generic routing/capability services.

- [ ] **Step 4: Run GREEN**

```bash
uv run python -m pytest -q \
  tests/unit/r2/m3/test_preparation.py \
  tests/unit/r2/contracts/test_production.py
```

- [ ] **Step 5: Commit**

```bash
git add r2/m3/preparation.py tests/unit/r2/m3/test_preparation.py
git commit -m "feat(r2): prepare Golden A mixed-method shots"
```

---

### Task 5: Local REUSE and DETERMINISTIC Shot Production

**Files:**
- Create: `r2/m3/local_production.py`
- Test: `tests/unit/r2/m3/test_local_production.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class LocalProducedAsset:
    target_ref: str
    method: ProductionMethod
    path: Path
    sha256: str
    duration_seconds: float
    execution_fingerprint: str
    tool: str
    tool_version: str
    wall_time_seconds: float
    external_provider_cost: Decimal

class GoldenALocalProducer:
    def produce(
        self,
        prepared: GoldenAPreparedShot,
        *,
        work_dir: Path,
    ) -> LocalProducedAsset:
        ...
```

- [ ] **Step 1: Write RED local-production tests**

Assert:
- REUSE does not mutate the source fixture;
- DETERMINISTIC produces valid local media;
- external cost is exactly `Decimal("0")`;
- execution fingerprint changes for execution-only settings;
- semantic content fingerprint is not derived from tool/version.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest -q tests/unit/r2/m3/test_local_production.py
```

- [ ] **Step 3: Implement local producer using discovered FFmpeg seam**

Use local SVG/title/diagram inputs. No API/cloud request.

- [ ] **Step 4: Run GREEN**

```bash
uv run python -m pytest -q tests/unit/r2/m3/test_local_production.py
```

Automated tests must ffprobe one produced sample.

- [ ] **Step 5: Commit**

```bash
git add r2/m3/local_production.py tests/unit/r2/m3/test_local_production.py
git commit -m "feat(r2): add Golden A local shot production"
```

---

### Task 6: Real M2 Host Bridge for Golden A Candidates and Masters

**Files:**
- Create: `r2/m3/host_integration.py`
- Test: `tests/integration/r2/m3/test_host_integration.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class RegisteredGoldenACandidate:
    artifact_key: str
    candidate: GenerationCandidate
    host_version_ref: str

class GoldenAHostIntegration:
    def stage_candidate(
        self,
        *,
        artifact_key: str,
        target_ref: str,
        content_fingerprint: str,
        produced: LocalProducedAsset,
    ) -> RegisteredGoldenACandidate:
        ...

    def approve(
        self,
        registered: RegisteredGoldenACandidate,
        *,
        approval_record: str,
        selected_by: str,
        selected_at: datetime,
    ) -> ApprovedMasterMetadata:
        ...
```

The class delegates to M2 `ArcReelArtifactManifestPort`, `ArcReelVersionRestorePromoter`, `ProductionApprovalService`, and ArcReel `VersionManager`.

- [ ] **Step 1: Write RED Host integration tests**

Prove:
1. candidate B is staged into real version history;
2. explicit B promotion creates ApprovedMaster B;
3. failed C preserves B;
4. successful-unapproved D preserves B;
5. explicit D promotion replaces B atomically;
6. restart/reload preserves active version and ApprovedMaster;
7. manifest R2 metadata contains factual ContentBasis/direct dependencies.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest -q tests/integration/r2/m3/test_host_integration.py
```

- [ ] **Step 3: Implement the narrow facade**

Do not modify Host/M2 internals. A genuine defect in an existing seam stops execution for a plan amendment.

- [ ] **Step 4: Run GREEN + M2 regression**

```bash
uv run python -m pytest -q \
  tests/integration/r2/m3/test_host_integration.py \
  tests/unit/r2/production/ \
  tests/integration/r2/production/
```

- [ ] **Step 5: Verify scope and commit Checkpoint C**

```bash
git diff --check
git add r2/m3/host_integration.py tests/integration/r2/m3/test_host_integration.py
git commit -m "feat(r2): connect Golden A to approved masters"
```

**Checkpoint C gate:** mixed-method preparation and real M2/ArcReel master semantics pass; Host runtime remains unchanged.

---

### Task 7: COMPOSITE Method and Real Final MP4

**Files:**
- Create: `r2/m3/composition.py`
- Test: `tests/integration/r2/m3/test_composition.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class FinalMediaArtifact:
    path: Path
    sha256: str
    duration_seconds: float
    video_codec: str
    width: int
    height: int
    container_format: str
    method: ProductionMethod
    wall_time_seconds: float
    external_provider_cost: Decimal

class GoldenAComposer:
    def compose(
        self,
        approved_inputs: Sequence[Path],
        *,
        output_path: Path,
    ) -> FinalMediaArtifact:
        ...
```

- [ ] **Step 1: Write RED composition test**

Require:
- at least 3 approved input clips;
- output is a non-empty `.mp4`;
- method is COMPOSITE;
- ffprobe sees a video stream;
- duration is within 60–90 seconds;
- external cost is zero.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest -q tests/integration/r2/m3/test_composition.py
```

- [ ] **Step 3: Implement the Task 0 composition mode**

- `REMOTION_FFMPEG`: use the proven existing Remotion projection/invocation and FFmpeg encoding seam.
- `FFMPEG_EXISTING`: use the proven existing FFmpeg composition path directly.

Do not create a new general editing engine.

- [ ] **Step 4: Run GREEN**

```bash
uv run python -m pytest -q tests/integration/r2/m3/test_composition.py
```

- [ ] **Step 5: Commit**

```bash
git add r2/m3/composition.py tests/integration/r2/m3/test_composition.py
git commit -m "feat(r2): compose Golden A final media"
```

---

### Task 8: Lineage, Selective Invalidation, Restart, and Single-Command Golden A

**Files:**
- Create: `r2/m3/lineage.py`
- Create: `r2/m3/golden_a.py`
- Modify: `r2/m3/__init__.py`
- Test: `tests/unit/r2/m3/test_lineage.py`
- Test: `tests/integration/r2/m3/test_selective_invalidation.py`
- Test: `tests/integration/r2/m3/test_golden_a.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class GoldenALineageReport:
    final_ref: str
    shot_master_refs: tuple[str, ...]
    shot_refs: tuple[str, ...]
    scene_refs: tuple[str, ...]
    script_section_refs: tuple[str, ...]
    claim_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    source_refs: tuple[str, ...]

@dataclass(frozen=True)
class GoldenARunResult:
    project_dir: Path
    final_media: FinalMediaArtifact
    lineage: GoldenALineageReport
    method_counts: Mapping[str, int]
    evidence_dir: Path

def run_golden_a(
    *,
    project_dir: Path,
    evidence_dir: Path,
) -> GoldenARunResult:
    ...
```

- [ ] **Step 1: Write RED lineage test**

Trace:

```text
final → masters → shots → scenes → script sections → claims → evidence → sources
```

Every ref resolves and no used claim is orphaned.

- [ ] **Step 2: Write RED selective invalidation test**

Change only CLAIM-002 version/fingerprint:

```text
SH01 CURRENT
SH02 STALE
SH03 STALE
SH04 CURRENT
FINAL STALE
```

Stored dependency snapshots remain unchanged after evaluation.

- [ ] **Step 3: Write RED end-to-end Golden A test**

```python
result = run_golden_a(
    project_dir=tmp_path / "project",
    evidence_dir=tmp_path / "evidence",
)
```

Assert:
- final MP4 exists and is ffprobe-valid;
- duration is 60–90 seconds;
- methods include REUSE, DETERMINISTIC, COMPOSITE;
- external provider cost is zero;
- ApprovedMaster refs resolve;
- B/C/D master scenario is proven;
- restart/reload passes;
- factual lineage reaches sources;
- evidence JSON files are emitted.

- [ ] **Step 4: Implement `lineage.py`**

It projects refs only; it is not a registry or dependency authority.

- [ ] **Step 5: Implement `golden_a.py`**

It coordinates Tasks 2–7 and emits:

```text
factual_snapshot.json
claim_lineage.json
script.json
scenes.json
shots.json
production_plan.json
artifact_lineage.json
cost_provenance.json
ffprobe.json
verification.json
```

- [ ] **Step 6: Run Task 8 GREEN**

```bash
uv run python -m pytest -q \
  tests/unit/r2/m3/test_lineage.py \
  tests/integration/r2/m3/test_selective_invalidation.py \
  tests/integration/r2/m3/test_golden_a.py
```

- [ ] **Step 7: Run full M3 focused suite and commit Checkpoint D**

```bash
uv run python -m pytest -q tests/unit/r2/m3/ tests/integration/r2/m3/
git add r2/m3 tests/unit/r2/m3 tests/integration/r2/m3
git commit -m "feat(r2): complete Golden A vertical slice"
```

**Checkpoint D gate:** one factual Golden A MP4 runs end-to-end with claim lineage, three methods, real ApprovedMaster semantics, selective invalidation, restart/reload, and zero paid-provider cost.

---

### Task 9: Architecture Guards, Final Verification, Evidence, and Push

**Files:**
- Create: `tests/unit/r2/m3/test_m3_architecture_boundaries.py`
- Create: `docs/r2/evidence/R2_M3_VERIFICATION_<timestamp>.json`
- Create: `docs/r2/evidence/R2_M3_VERIFICATION_<timestamp>.md`
- No production source changes after final verification begins.

**Interfaces:**
- Consumes Checkpoint D.
- Produces final M3 evidence and verified `origin/r2/main`.

- [ ] **Step 1: Write architecture guard tests**

Mechanically assert:
- no parallel R2 artifact registry;
- no second media queue;
- no M3 DB migration;
- no M3-introduced generic `MethodRouterService`, `CapabilityRegistry`, `PromptCompilerService`, or general `DirectorAdapter`;
- no new Canon/Narrative/Adaptation implementation;
- Host changes since M2 are empty unless an approved Task 0 plan amendment exists;
- SceneSpec/ShotSpec remain provider-neutral;
- direct dependency snapshots only;
- H1 remains OPEN / PRODUCTION_BLOCKER.

- [ ] **Step 2: Run architecture tests**

```bash
uv run python -m pytest -q tests/unit/r2/m3/test_m3_architecture_boundaries.py
```

- [ ] **Step 3: Run a fresh Golden A outside the repository**

```bash
RUN_ROOT="$(mktemp -d /tmp/r2-m3-golden-a.XXXXXX)"
export RUN_ROOT

uv run python - <<'PY'
from pathlib import Path
import os
from r2.m3 import run_golden_a

root = Path(os.environ["RUN_ROOT"])
result = run_golden_a(
    project_dir=root / "project",
    evidence_dir=root / "evidence",
)
print(result.final_media.path)
print(result.final_media.sha256)
PY
```

- [ ] **Step 4: Run fresh regressions**

```bash
uv run python -m pytest -q tests/unit/r2/m3/ tests/integration/r2/m3/
uv run python -m pytest -q tests/unit/r2/production/ tests/integration/r2/production/
uv run python -m pytest -q tests/unit/r2/contracts/
uv run python -m pytest -q \
  tests/unit/r2/test_bootstrap.py \
  tests/unit/scripts/r2/test_verify_frozen_registries.py \
  tests/unit/scripts/r2/test_known_blockers.py \
  tests/unit/scripts/r2/test_verify_baseline.py \
  tests/unit/scripts/r2/test_verify_postgres_baseline_script.py
```

Record exact pass counts in evidence.

- [ ] **Step 5: Run frozen Host, audit and PostgreSQL gates**

Use the same frozen ArcReel focused path set carried by M2 verification, then:

```bash
uv run python scripts/audit_tests.py --check
uv run python scripts/r2/verify_frozen_registries.py
uv run python scripts/r2/verify_baseline.py
bash scripts/r2/verify_postgres_baseline.sh
```

Expected:
- focused Host baseline PASS;
- audit = 0 violations;
- frozen/baseline PASS;
- PostgreSQL migration + initial health + restart health PASS.

- [ ] **Step 6: Validate final media/method semantics**

Final evidence must include:

```json
{
  "final_mp4": "PASS",
  "duration_target": "PASS",
  "required_methods": {
    "REUSE": "PASS",
    "DETERMINISTIC": "PASS",
    "COMPOSITE": "PASS"
  },
  "external_provider_cost": "0",
  "claim_lineage": "PASS",
  "approved_master": "PASS",
  "failed_regeneration_preserves_master": "PASS",
  "unapproved_candidate_preserves_master": "PASS",
  "selective_invalidation": "PASS",
  "restart_reload": "PASS"
}
```

- [ ] **Step 7: Create immutable M3 verification evidence**

The JSON report records:
- verified HEAD;
- exact test counts;
- final MP4 SHA-256 and ffprobe summary;
- method counts;
- factual lineage counts;
- cost/provenance;
- Host changes since M2;
- DB migration changes since M2;
- audit/PostgreSQL results;
- H1 state;
- `host_maturity_evidence = "INTEGRATION_READY"`.

Markdown summarizes the same evidence and must pass `git diff --check`.

- [ ] **Step 8: Commit architecture tests and evidence**

```bash
git add tests/unit/r2/m3/test_m3_architecture_boundaries.py
git commit -m "test(r2): enforce M3 Golden A boundaries"

git add docs/r2/evidence/R2_M3_VERIFICATION_*.json \
        docs/r2/evidence/R2_M3_VERIFICATION_*.md
git diff --cached --check
git commit -m "test(r2): record M3 Golden A verification"
```

- [ ] **Step 9: Final remote safety and push**

```bash
git fetch origin
git merge-base --is-ancestor origin/r2/main HEAD
test "$(git rev-list --count HEAD..origin/r2/main)" = "0"
git push origin r2/main
git fetch origin
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/r2/main)"
test -z "$(git status --porcelain)"
```

- [ ] **Step 10: Completion markers**

Only after every gate above:

```text
R2-M3 TASK 9: FINAL VERIFICATION + EVIDENCE + PUSH COMPLETE
R2-M3 GOLDEN A: TECHNICALLY COMPLETE
R2 HOST MATURITY EVIDENCE: INTEGRATION_READY
R2-HOST-001: OPEN / PRODUCTION_BLOCKER
```

---

# Plan Self-Review

## Spec coverage

- Factual authority chain: Tasks 1–2.
- ScriptArtifact claim refs: Tasks 1–2.
- OpenMontage general-content seam: Task 3.
- SceneSpec/ShotSpec neutrality: Tasks 3 and 9.
- ProductionBinding/readiness: Task 4.
- Three required methods: Tasks 4, 5, 7; verified in 8–9.
- Real M2 Artifact Bridge/ApprovedMaster: Task 6.
- Failed and unapproved candidate preserve master: Tasks 6 and 8.
- Real final MP4 + ffprobe: Task 7.
- Claim lineage: Task 8.
- Selective invalidation: Task 8.
- Restart/reload: Tasks 6 and 8.
- Zero paid-provider cost/provenance: Tasks 5, 7, 8, 9.
- No parallel registry/queue/M4 leakage: Task 9.
- H1 remains open: Tasks 0 and 9.
- INTEGRATION_READY evidence only, not production approval: Task 9.

## Placeholder scan

The plan contains no unresolved implementation markers. Runtime-observed seam values are produced by Task 0 as evidence, not guessed in advance.

## Type consistency

Public M3 interfaces introduced by this plan are:
- `GoldenAFactualBundle`
- `GoldenADirectionResult`
- `GoldenAOpenMontageBackend`
- `GoldenAOpenMontageAdapter`
- `GoldenAMethodAssignment`
- `GoldenAPreparedShot`
- `GoldenAProductionPreparation`
- `LocalProducedAsset`
- `GoldenALocalProducer`
- `RegisteredGoldenACandidate`
- `GoldenAHostIntegration`
- `FinalMediaArtifact`
- `GoldenAComposer`
- `GoldenALineageReport`
- `GoldenARunResult`
- `run_golden_a(...)`

A real existing-name collision discovered in Task 0 requires an explicit plan correction before implementation rather than silent renaming.
