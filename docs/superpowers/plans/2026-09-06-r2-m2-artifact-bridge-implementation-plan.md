# R2-M2 Artifact Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect R2-M1 contracts to the existing ArcReel Artifact Manifest/version/activation subsystem with direct dependency snapshots, computed selective invalidation, explicit ApprovedMaster promotion, and zero parallel artifact registry.

**Architecture:** R2-M2 adds pure R2 production models/services under `r2/production/`, then adapts them to the exact Artifact Manifest/currency/activation seam discovered in the pinned local ArcReel v0.29.0 source. ArcReel remains artifact/version/runtime authority; R2 adds semantic lineage, dependency fingerprinting, and ApprovedMaster semantics. Host files may be changed only when Task 0 proves no cleaner extension seam exists.

**Tech Stack:** Python 3.13+, Pydantic v2, pytest, ArcReel Artifact Manifest/version/activation subsystem, existing ArcReel locking/atomic-write discipline.

**Spec:** `docs/superpowers/specs/2026-09-06-r2-m2-artifact-bridge-design.md`

## Global Constraints

- R2.1–R2.7 architecture freeze remains authoritative.
- R2-M1 Contract Kernel is COMPLETE.
- ArcReel pinned baseline remains `v0.29.0` at `6ddedc775e7fe5f398b10081ab741985f7dceda7`.
- Existing ArcReel Artifact Manifest remains the single artifact truth.
- No `.r2_artifacts.json`, parallel artifact registry, or second media/version store.
- No R2 SQL migration.
- No `r2_artifacts`, `r2_dependencies`, or `r2_approved_masters` SQL tables.
- R2 stores direct dependency snapshots only; no transitive graph persistence.
- Currency invalidation is computed from current direct dependencies; evaluation must never silently refresh stored snapshots.
- Provider/model/endpoint/seed/resolution/execution settings do not affect R2 content currency.
- `GenerationCandidate != ApprovedMaster`.
- Failed or merely successful-unapproved generation preserves the prior ApprovedMaster.
- ApprovedMaster promotion must keep host active version and master metadata consistent.
- Legacy non-R2 ArcReel artifacts retain native behavior.
- Malformed R2-aware artifacts are BLOCKED, never silently treated as legacy.
- `R2-HOST-001` remains OPEN / PRODUCTION_BLOCKER.
- No Canon, FactualAuthority, NarrativePlan, Adaptation, DirectorAdapter, provider execution, or UI implementation in M2.
- Tests use ArcReel taxonomy: `tests/unit/r2/production/` and `tests/integration/r2/production/`.
- Local execution must use codebase-memory-MCP first for architecture/symbol/call-graph/impact discovery, then targeted reads.
- Every implementation task follows RED → minimal GREEN → focused regression → commit.
- No push until final M2 verification passes.

---

# File Map

## R2 production files

```text
r2/production/__init__.py
r2/production/artifact_metadata.py
r2/production/dependency_resolver.py
r2/production/artifact_bridge.py
r2/production/approval_service.py
```

Responsibilities:

- `artifact_metadata.py`
  - `R2ContractRef`
  - `DependencySnapshot`
  - `ApprovedMasterMetadata`
  - `R2ArtifactMetadata`

- `dependency_resolver.py`
  - `DependencyResolver`
  - `DependencyResolverRegistry`
  - resolver error types

- `artifact_bridge.py`
  - `ArtifactManifestPort`
  - `ArtifactHostSnapshot`
  - `R2CurrencyEvaluation`
  - `R2ArtifactBridge`
  - legacy-vs-R2-aware metadata parsing
  - semantic currency evaluation

- `approval_service.py`
  - `PromotionResult`
  - `ProductionApprovalService`
  - candidate validation
  - atomic master promotion over the host port

## M2 test files

```text
tests/unit/r2/production/test_artifact_metadata.py
tests/unit/r2/production/test_dependency_resolver.py
tests/unit/r2/production/test_artifact_bridge.py
tests/unit/r2/production/test_approval_service.py

tests/integration/r2/production/test_manifest_bridge_integration.py
tests/integration/r2/production/test_master_promotion_integration.py
tests/integration/r2/production/test_manifest_recovery_integration.py
```

## Discovery/evidence files

```text
docs/r2/evidence/R2_M2_SEAM_DISCOVERY.md
docs/r2/evidence/R2_M2_SEAM_DISCOVERY.json
docs/r2/evidence/R2_M2_VERIFICATION_<timestamp>.md
docs/r2/evidence/R2_M2_VERIFICATION_<timestamp>.json
```

---

# Task 0: Mandatory ArcReel seam discovery

**Files:**
- Create: `docs/r2/evidence/R2_M2_SEAM_DISCOVERY.md`
- Create: `docs/r2/evidence/R2_M2_SEAM_DISCOVERY.json`
- Do not modify production code in this task.

**Interfaces:**
- Produces the exact host symbols and paths consumed by Tasks 4–8.
- Required JSON keys:
  `baseline_sha`, `manifest_model`, `manifest_read`, `manifest_write`,
  `activation_read`, `activation_write`, `currency_projection`,
  `provenance_path`, `lock_or_atomicity`, `legacy_tests`,
  `host_files_if_patch_required`, `extension_seam_available`.

- [ ] **Step 1: Verify repository state**

Run:

```bash
cd ~/content-production-os

git branch --show-current
git status --short
git rev-parse HEAD
git rev-parse origin/r2/main
git merge-base HEAD 6ddedc775e7fe5f398b10081ab741985f7dceda7
```

Required:

```text
branch = r2/main
working tree = clean
HEAD == origin/r2/main
merge-base == 6ddedc775e7fe5f398b10081ab741985f7dceda7
```

- [ ] **Step 2: Query codebase-memory-MCP before reading files**

Use the local codebase-memory-MCP with these queries, in order:

```text
1. Find the Artifact Manifest model/schema and all symbols that read, validate,
   serialize, lock, atomically write, and update the project-local artifact manifest.

2. Find all callers/callees that activate or select an artifact/media version and
   determine whether active-version selection and manifest mutation share a lock
   or transaction boundary.

3. Find the artifact currency projection code that produces CURRENT, STALE,
   MISSING, BLOCKED and identify how provenance/content dependencies feed it.

4. Find the existing tests that protect manifest atomic writes, unchanged-write
   avoidance, path containment/symlink safety, failed-regeneration preservation,
   currency, version activation, and restart/reload behavior.

5. Determine the blast radius of adding an optional R2 metadata envelope to one
   manifest artifact entry and adding an R2 semantic currency input.
```

Record returned symbol names and source paths.

- [ ] **Step 3: Targeted filesystem confirmation**

Run only targeted searches informed by the MCP results:

```bash
rg -n --hidden \
  "artifact[_ -]?manifest|ArtifactManifest|CURRENT|STALE|MISSING|BLOCKED|activate|active_version|artifact.*lock|atomic" \
  lib server tests \
  -g '*.py'
```

Then read only the exact files/symbol ranges identified by MCP/rg.

Do not broadly reread the repository.

- [ ] **Step 4: Write seam discovery Markdown**

Create `docs/r2/evidence/R2_M2_SEAM_DISCOVERY.md` with this exact structure:

```markdown
# R2-M2 ArcReel Seam Discovery

**Baseline:** `6ddedc775e7fe5f398b10081ab741985f7dceda7`
**Branch:** `r2/main`

## Manifest model
- Path:
- Symbol:
- Entry extension mechanism:

## Manifest read/write
- Read path/symbol:
- Write/update path/symbol:
- Lock/atomic replacement path/symbol:

## Version activation
- Read active version path/symbol:
- Activate path/symbol:
- Transaction/lock boundary:

## Currency
- Path/symbol:
- Existing inputs:
- Extension point for R2 semantic currency:

## Provenance
- Path/symbol:

## Existing regression tests
- Manifest:
- Currency:
- Failed regeneration:
- Version activation:
- Restart/reload:
- Concurrency:

## Host patch decision
- Existing extension seam available: YES/NO
- Host files requiring bounded modification:
- Why each file must change:
```

Every blank after a label must be filled with an observed path/symbol or the literal `NONE`.

- [ ] **Step 5: Write machine-readable seam discovery JSON**

Create `docs/r2/evidence/R2_M2_SEAM_DISCOVERY.json`:

```json
{
  "baseline_sha": "6ddedc775e7fe5f398b10081ab741985f7dceda7",
  "manifest_model": {"path": "<observed>", "symbol": "<observed>"},
  "manifest_read": {"path": "<observed>", "symbol": "<observed>"},
  "manifest_write": {"path": "<observed>", "symbol": "<observed>"},
  "activation_read": {"path": "<observed>", "symbol": "<observed>"},
  "activation_write": {"path": "<observed>", "symbol": "<observed>"},
  "currency_projection": {"path": "<observed>", "symbol": "<observed>"},
  "provenance_path": {"path": "<observed>", "symbol": "<observed>"},
  "lock_or_atomicity": {"path": "<observed>", "symbol": "<observed>"},
  "legacy_tests": ["<observed test path>"],
  "extension_seam_available": true,
  "host_files_if_patch_required": []
}
```

Replace every `<observed>` with the actual local result. Do not commit angle-bracket placeholders.

- [ ] **Step 6: Validate discovery completeness**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

p = Path("docs/r2/evidence/R2_M2_SEAM_DISCOVERY.json")
d = json.loads(p.read_text())

required = {
    "baseline_sha",
    "manifest_model",
    "manifest_read",
    "manifest_write",
    "activation_read",
    "activation_write",
    "currency_projection",
    "provenance_path",
    "lock_or_atomicity",
    "legacy_tests",
    "extension_seam_available",
    "host_files_if_patch_required",
}
assert set(d) == required
assert d["baseline_sha"] == "6ddedc775e7fe5f398b10081ab741985f7dceda7"
assert d["legacy_tests"]
for key in (
    "manifest_model", "manifest_read", "manifest_write",
    "activation_read", "activation_write",
    "currency_projection", "provenance_path", "lock_or_atomicity",
):
    assert d[key]["path"]
    assert d[key]["symbol"]
    assert "<" not in d[key]["path"] + d[key]["symbol"]
print("R2-M2 seam discovery: PASS")
PY
```

Expected:

```text
R2-M2 seam discovery: PASS
```

- [ ] **Step 7: Commit Task 0**

```bash
git add docs/r2/evidence/R2_M2_SEAM_DISCOVERY.md \
        docs/r2/evidence/R2_M2_SEAM_DISCOVERY.json

git commit -m "docs(r2): record M2 artifact host seam"
```

**Checkpoint rule:** If the discovery shows no safe Artifact Manifest/currency/activation seam, stop M2 execution and escalate as an implementation blocker. Do not invent a second registry.

---

# Task 1: R2 artifact metadata models

**Files:**
- Create: `r2/production/__init__.py`
- Create: `r2/production/artifact_metadata.py`
- Create: `tests/unit/r2/production/test_artifact_metadata.py`

**Interfaces:**
- Consumes:
  `r2.contracts.ContentBasis`,
  `r2.contracts.GenerationCandidate`,
  `r2.contracts.R2ContractModel`,
  `r2.contracts.NonEmptyStr`.
- Produces:
  `R2ContractRef`,
  `DependencySnapshot`,
  `ApprovedMasterMetadata`,
  `R2ArtifactMetadata`.

- [ ] **Step 1: Write failing metadata tests**

Create `tests/unit/r2/production/test_artifact_metadata.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from r2.contracts import ContentBasis, ContentBasisType
from r2.production import (
    ApprovedMasterMetadata,
    DependencySnapshot,
    R2ArtifactMetadata,
    R2ContractRef,
)


def basis():
    return ContentBasis(
        basis_type=ContentBasisType.NARRATIVE,
        basis_version="canon-v7",
        refs=["event:1"],
    )


def test_r2_artifact_metadata_round_trips_and_sorts_direct_dependencies():
    metadata = R2ArtifactMetadata(
        metadata_schema_version="1",
        contract_ref=R2ContractRef(
            contract_type="ShotSpec",
            id="SH042",
            version=4,
            schema_version="2.1",
        ),
        content_basis=basis(),
        direct_dependencies=[
            DependencySnapshot(
                ref="r2:ProductionBinding:B02",
                version="5",
                fingerprint="b" * 64,
            ),
            DependencySnapshot(
                ref="r2:ProductionBinding:B01",
                version="2",
                fingerprint="a" * 64,
            ),
        ],
        content_fingerprint="c" * 64,
    )

    restored = R2ArtifactMetadata.model_validate(metadata.model_dump(mode="json"))
    assert restored == metadata
    assert [d.ref for d in metadata.direct_dependencies] == [
        "r2:ProductionBinding:B01",
        "r2:ProductionBinding:B02",
    ]


def test_r2_artifact_metadata_requires_content_basis():
    with pytest.raises(ValidationError):
        R2ArtifactMetadata(
            metadata_schema_version="1",
            contract_ref=R2ContractRef(
                contract_type="ShotSpec",
                id="SH042",
                version=4,
                schema_version="2.1",
            ),
            direct_dependencies=[],
            content_fingerprint="c" * 64,
        )


def test_approved_master_requires_timezone_aware_selected_at():
    with pytest.raises(ValidationError):
        ApprovedMasterMetadata(
            selected_candidate_id="C1",
            host_version_ref="V17",
            approval_record="APR1",
            selected_at=datetime(2026, 9, 6, 18, 0),
            selected_by="showrunner:1",
        )

    master = ApprovedMasterMetadata(
        selected_candidate_id="C1",
        host_version_ref="V17",
        approval_record="APR1",
        selected_at=datetime(2026, 9, 6, 18, 0, tzinfo=timezone.utc),
        selected_by="showrunner:1",
    )
    assert master.host_version_ref == "V17"
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest -q \
  tests/unit/r2/production/test_artifact_metadata.py
```

Expected: import failure because `r2.production` does not exist.

- [ ] **Step 3: Implement metadata models**

Create `r2/production/artifact_metadata.py`:

```python
from pydantic import AwareDatetime, Field, field_validator

from r2.contracts import ContentBasis, NonEmptyStr, R2ContractModel


class R2ContractRef(R2ContractModel):
    contract_type: NonEmptyStr
    id: NonEmptyStr
    version: int = Field(ge=1)
    schema_version: NonEmptyStr


class DependencySnapshot(R2ContractModel):
    ref: NonEmptyStr
    version: NonEmptyStr
    fingerprint: NonEmptyStr


class ApprovedMasterMetadata(R2ContractModel):
    selected_candidate_id: NonEmptyStr
    host_version_ref: NonEmptyStr
    approval_record: NonEmptyStr
    selected_at: AwareDatetime
    selected_by: NonEmptyStr


class R2ArtifactMetadata(R2ContractModel):
    metadata_schema_version: NonEmptyStr
    contract_ref: R2ContractRef
    content_basis: ContentBasis
    direct_dependencies: list[DependencySnapshot] = Field(default_factory=list)
    content_fingerprint: NonEmptyStr
    approved_master: ApprovedMasterMetadata | None = None

    @field_validator("direct_dependencies")
    @classmethod
    def normalize_dependencies(
        cls,
        value: list[DependencySnapshot],
    ) -> list[DependencySnapshot]:
        by_ref: dict[str, DependencySnapshot] = {}
        for item in value:
            existing = by_ref.get(item.ref)
            if existing is not None and existing != item:
                raise ValueError(f"conflicting dependency snapshots for {item.ref}")
            by_ref[item.ref] = item
        return [by_ref[key] for key in sorted(by_ref)]
```

Create `r2/production/__init__.py` exporting the four models.

- [ ] **Step 4: Run GREEN**

```bash
uv run python -m pytest -q \
  tests/unit/r2/production/test_artifact_metadata.py
```

Expected: `3 passed`.

- [ ] **Step 5: Run M1 contract regression**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add r2/production tests/unit/r2/production/test_artifact_metadata.py
git commit -m "feat(r2): add artifact bridge metadata"
```

---

# Task 2: Direct dependency resolver registry

**Files:**
- Create: `r2/production/dependency_resolver.py`
- Modify: `r2/production/__init__.py`
- Create: `tests/unit/r2/production/test_dependency_resolver.py`

**Interfaces:**
- Consumes: `DependencySnapshot`.
- Produces:
  `DependencyResolver`,
  `DependencyResolverRegistry`,
  `UnresolvedDependencyError`,
  `AmbiguousDependencyResolverError`.

- [ ] **Step 1: Write failing resolver tests**

```python
import pytest

from r2.production import (
    AmbiguousDependencyResolverError,
    DependencyResolverRegistry,
    DependencySnapshot,
    UnresolvedDependencyError,
)


class Resolver:
    def __init__(self, prefix, snapshot):
        self.prefix = prefix
        self.snapshot = snapshot

    def supports(self, ref):
        return ref.startswith(self.prefix)

    def resolve(self, ref):
        return self.snapshot


def test_registry_resolves_exactly_one_claimant():
    snapshot = DependencySnapshot(
        ref="r2:ShotSpec:SH1",
        version="1",
        fingerprint="a" * 64,
    )
    registry = DependencyResolverRegistry([Resolver("r2:", snapshot)])
    assert registry.resolve(snapshot.ref) == snapshot


def test_registry_rejects_zero_claimants():
    registry = DependencyResolverRegistry([])
    with pytest.raises(UnresolvedDependencyError):
        registry.resolve("canon:Event:E1")


def test_registry_rejects_multiple_claimants():
    snapshot = DependencySnapshot(
        ref="r2:ShotSpec:SH1",
        version="1",
        fingerprint="a" * 64,
    )
    registry = DependencyResolverRegistry([Resolver("r2:", snapshot), Resolver("r2:Shot", snapshot)])
    with pytest.raises(AmbiguousDependencyResolverError):
        registry.resolve(snapshot.ref)
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest -q \
  tests/unit/r2/production/test_dependency_resolver.py
```

Expected: import failure.

- [ ] **Step 3: Implement registry**

Create `r2/production/dependency_resolver.py`:

```python
from collections.abc import Iterable
from typing import Protocol

from .artifact_metadata import DependencySnapshot


class DependencyResolver(Protocol):
    def supports(self, ref: str) -> bool: ...
    def resolve(self, ref: str) -> DependencySnapshot: ...


class UnresolvedDependencyError(LookupError):
    pass


class AmbiguousDependencyResolverError(LookupError):
    pass


class DependencyResolverRegistry:
    def __init__(
        self,
        resolvers: Iterable[DependencyResolver] = (),
    ) -> None:
        self._resolvers = list(resolvers)

    def register(self, resolver: DependencyResolver) -> None:
        self._resolvers.append(resolver)

    def resolve(self, ref: str) -> DependencySnapshot:
        matches = [r for r in self._resolvers if r.supports(ref)]
        if not matches:
            raise UnresolvedDependencyError(ref)
        if len(matches) != 1:
            raise AmbiguousDependencyResolverError(ref)

        snapshot = matches[0].resolve(ref)
        if snapshot.ref != ref:
            raise ValueError(f"resolver returned {snapshot.ref!r} for {ref!r}")
        return snapshot
```

Export all symbols from `r2/production/__init__.py`.

- [ ] **Step 4: Run GREEN and regression**

```bash
uv run python -m pytest -q \
  tests/unit/r2/production/test_dependency_resolver.py \
  tests/unit/r2/production/test_artifact_metadata.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add r2/production tests/unit/r2/production/test_dependency_resolver.py
git commit -m "feat(r2): add dependency resolver registry"
```

---

# Task 3: Pure R2 artifact currency bridge

**Files:**
- Create: `r2/production/artifact_bridge.py`
- Modify: `r2/production/__init__.py`
- Create: `tests/unit/r2/production/test_artifact_bridge.py`

**Interfaces:**
- Consumes:
  `ArtifactCurrencyStatus`,
  `R2ArtifactMetadata`,
  `DependencyResolverRegistry`.
- Produces:
  `ArtifactManifestPort`,
  `ArtifactHostSnapshot`,
  `R2CurrencyEvaluation`,
  `R2ArtifactBridge`.

`ArtifactManifestPort` is the stable R2-facing Host interface:

```python
class ArtifactManifestPort(Protocol):
    def load_artifact(self, artifact_key: str) -> ArtifactHostSnapshot | None: ...
    def write_r2_metadata(
        self,
        artifact_key: str,
        metadata: R2ArtifactMetadata,
    ) -> None: ...
```

- [ ] **Step 1: Write failing currency tests**

Create tests proving all six behaviors:

```text
legacy non-R2 → no R2 override
valid R2 metadata + unchanged deps → CURRENT
related dependency change → STALE
unrelated external change → remains CURRENT
unresolved dependency → BLOCKED
evaluation does not mutate stored dependency snapshots
```

The core assertions must appear directly in each `test_*` function to satisfy ArcReel audit.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest -q \
  tests/unit/r2/production/test_artifact_bridge.py
```

Expected: import failure.

- [ ] **Step 3: Implement host snapshot and semantic evaluation**

Implement in `r2/production/artifact_bridge.py`:

```python
from dataclasses import dataclass
from typing import Protocol

from r2.contracts import ArtifactCurrencyStatus

from .artifact_metadata import R2ArtifactMetadata
from .dependency_resolver import (
    AmbiguousDependencyResolverError,
    DependencyResolverRegistry,
    UnresolvedDependencyError,
)


@dataclass(frozen=True)
class ArtifactHostSnapshot:
    artifact_key: str
    usable: bool
    native_currency: ArtifactCurrencyStatus
    r2_raw: dict | None


@dataclass(frozen=True)
class R2CurrencyEvaluation:
    status: ArtifactCurrencyStatus | None
    reason: str
    metadata: R2ArtifactMetadata | None


class ArtifactManifestPort(Protocol):
    def load_artifact(
        self,
        artifact_key: str,
    ) -> ArtifactHostSnapshot | None: ...

    def write_r2_metadata(
        self,
        artifact_key: str,
        metadata: R2ArtifactMetadata,
    ) -> None: ...
```

`R2ArtifactBridge.evaluate_currency(artifact_key)` must implement:

```text
host artifact absent
→ return native/None according to Host snapshot contract

r2_raw is None
→ status=None, reason="legacy"

r2_raw present but validation fails
→ BLOCKED

native currency is MISSING
→ MISSING

native currency is BLOCKED
→ BLOCKED

dependency resolution error
→ BLOCKED

current direct dependency snapshot differs
→ STALE

all dependency snapshots match
→ CURRENT
```

Comparison must use exact stored `DependencySnapshot` values and must not mutate metadata.

- [ ] **Step 4: Run GREEN**

```bash
uv run python -m pytest -q \
  tests/unit/r2/production/test_artifact_bridge.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add r2/production tests/unit/r2/production/test_artifact_bridge.py
git commit -m "feat(r2): add semantic artifact currency bridge"
```

---

# Task 4: Bind the bridge to the exact ArcReel Artifact Manifest seam

**Files:**
- Modify only the exact Host paths listed in:
  `docs/r2/evidence/R2_M2_SEAM_DISCOVERY.json`
  under `host_files_if_patch_required`.
- Modify: `r2/production/artifact_bridge.py`
- Create: `tests/integration/r2/production/test_manifest_bridge_integration.py`

**Interfaces:**
- Consumes Task 0 exact Host symbols.
- Produces one concrete `ArtifactManifestPort` implementation backed by the existing ArcReel manifest.

**Mandatory precondition:** Load `R2_M2_SEAM_DISCOVERY.json`. If `extension_seam_available=false`, stop. If host files are modified, each modified path must already be listed in `host_files_if_patch_required`.

- [ ] **Step 1: Verify host-patch allowlist**

```bash
python - <<'PY'
import json
from pathlib import Path

d = json.loads(
    Path("docs/r2/evidence/R2_M2_SEAM_DISCOVERY.json").read_text()
)
assert d["extension_seam_available"] is True
print("host patch allowlist:", d["host_files_if_patch_required"])
PY
```

- [ ] **Step 2: Write failing real-manifest integration tests**

`tests/integration/r2/production/test_manifest_bridge_integration.py` must directly assert:

```text
1. write R2 metadata through adapter → actual manifest persists envelope
2. reload manifest → R2 metadata round-trips
3. legacy manifest entry without R2 envelope → native behavior unchanged
4. malformed R2 envelope → bridge returns BLOCKED
5. existing unchanged-write behavior still skips semantically identical write
```

Use existing ArcReel test fixtures/helpers discovered in Task 0 rather than new ad-hoc manifest storage.

- [ ] **Step 3: Run RED**

```bash
uv run python -m pytest -q \
  tests/integration/r2/production/test_manifest_bridge_integration.py
```

Expected: failure because no concrete Host adapter exists.

- [ ] **Step 4: Implement the concrete adapter against discovered symbols**

Rules:

```text
- Call the exact existing manifest read/write/lock APIs from Task 0.
- Do not open/write the manifest file directly if an ArcReel storage API exists.
- Preserve native keys and schema layout.
- Add only an optional additive R2 envelope.
- Reuse existing atomic replacement and lock behavior.
- Do not introduce a second lock.
```

If the native manifest entry schema rejects unknown optional metadata, make the smallest bounded change to the exact manifest model path recorded in Task 0.

- [ ] **Step 5: Run GREEN plus discovered legacy tests**

```bash
uv run python -m pytest -q \
  tests/integration/r2/production/test_manifest_bridge_integration.py
```

Then run every path listed in `legacy_tests` from `R2_M2_SEAM_DISCOVERY.json`.

Expected: all PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add r2/production \
  tests/integration/r2/production/test_manifest_bridge_integration.py \
  $(python - <<'PY'
import json
from pathlib import Path
d=json.loads(Path("docs/r2/evidence/R2_M2_SEAM_DISCOVERY.json").read_text())
print(" ".join(d["host_files_if_patch_required"]))
PY
)

git commit -m "feat(r2): bridge artifact metadata to host manifest"
```

---

# Task 5: Explicit ApprovedMaster promotion service

**Files:**
- Create: `r2/production/approval_service.py`
- Modify: `r2/production/artifact_bridge.py`
- Modify: `r2/production/__init__.py`
- Create: `tests/unit/r2/production/test_approval_service.py`

**Interfaces:**
- Consumes:
  `GenerationCandidate`,
  `GenerationLifecycleStatus`,
  `CandidateSelectionStatus`,
  `ApprovedMasterMetadata`,
  `R2ArtifactMetadata`.
- Extends the Host port with one atomic operation:

```python
class ArtifactManifestPort(Protocol):
    ...

    def promote_version_with_r2_metadata(
        self,
        artifact_key: str,
        *,
        host_version_ref: str,
        metadata: R2ArtifactMetadata,
    ) -> None: ...
```

- Produces:

```python
@dataclass(frozen=True)
class PromotionResult:
    changed: bool
    approved_master: ApprovedMasterMetadata
```

- [ ] **Step 1: Write failing promotion unit tests**

Direct assertions must prove:

```text
FAILED candidate cannot promote
successful UNREVIEWED candidate can be explicitly promoted
promotion records selected candidate + host version + approval
already-selected same candidate/version is idempotent
successful candidate without calling promote leaves previous master unchanged
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest -q \
  tests/unit/r2/production/test_approval_service.py
```

Expected: import failure.

- [ ] **Step 3: Implement minimal ProductionApprovalService**

Required public method:

```python
def promote(
    self,
    *,
    artifact_key: str,
    candidate: GenerationCandidate,
    host_version_ref: str,
    approval_record: str,
    selected_by: str,
    selected_at: datetime,
) -> PromotionResult: ...
```

Validation order:

```text
1. candidate target matches artifact context known by bridge/metadata
2. lifecycle == GENERATED
3. host version ref non-empty
4. approval fields valid
5. build ApprovedMasterMetadata
6. build updated R2ArtifactMetadata without changing stored dependency snapshots
7. call promote_version_with_r2_metadata(...)
8. return changed/no-op result
```

Do not derive promotion from "latest generated".

- [ ] **Step 4: Run GREEN**

```bash
uv run python -m pytest -q \
  tests/unit/r2/production/test_approval_service.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add r2/production tests/unit/r2/production/test_approval_service.py
git commit -m "feat(r2): add approved master promotion service"
```

---

# Task 6: Atomic host activation + ApprovedMaster integration

**Files:**
- Modify only exact Task 0 host activation/manifest paths when required.
- Create: `tests/integration/r2/production/test_master_promotion_integration.py`

**Interfaces:**
- Consumes:
  `ProductionApprovalService`,
  discovered host activation/write/lock seam.
- Produces atomic durable promotion semantics.

- [ ] **Step 1: Write failing integration tests**

Direct assertions must prove:

```text
A. Existing B master + generated C + no promote()
   → B remains active and ApprovedMaster

B. Existing B master + FAILED C
   → B remains active and ApprovedMaster

C. Existing B master + GENERATED C + explicit promote()
   → C host version active
   → ApprovedMaster.selected_candidate_id == C

D. Inject failure between validation and durable commit
   → B remains active
   → B remains ApprovedMaster

E. promote(C) twice
   → second call is no-op/idempotent
```

Use actual ArcReel version/manifest helpers discovered in Task 0.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest -q \
  tests/integration/r2/production/test_master_promotion_integration.py
```

Expected: failure because host atomic promotion seam is not bound yet.

- [ ] **Step 3: Implement atomic promotion using existing Host lock/transaction**

Implementation must satisfy:

```text
load current manifest/master
validate target host version exists
acquire existing artifact/manifest lock
write active-version selection and R2 ApprovedMaster metadata
commit using existing atomic replacement/transaction
```

Do not persist one side first and the other side later through separate durable operations.

If the existing Host abstraction cannot update active version + manifest metadata inside one atomic boundary, add one bounded method to the exact Task 0 activation/manifest seam.

- [ ] **Step 4: Run GREEN + legacy activation tests**

Run M2 integration test and Task 0 activation/manifest legacy tests.

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

```bash
git add r2/production \
  tests/integration/r2/production/test_master_promotion_integration.py \
  <only exact allowlisted host files actually modified>

git commit -m "feat(r2): make approved master promotion atomic"
```

At execution time replace the shell argument above with the exact paths from the Task 0 allowlist; do not commit any unlisted host file.

---

# Task 7: Restart, recovery, concurrency, and snapshot immutability

**Files:**
- Create: `tests/integration/r2/production/test_manifest_recovery_integration.py`
- Modify production code only if a failing test demonstrates a defect.

**Interfaces:**
- Consumes completed bridge and approval service.
- Produces no new public API.

- [ ] **Step 1: Write failing recovery/concurrency tests**

Direct assertions must prove:

```text
1. restart/reload preserves R2 metadata
2. restart/reload preserves ApprovedMaster selection
3. evaluating stale currency does not overwrite stored dependency snapshots
4. concurrent R2 metadata updates use existing Host lock and produce valid manifest
5. concurrent promotion cannot create active-version/master mismatch
6. stale ApprovedMaster remains selected and usable until explicit replacement
```

- [ ] **Step 2: Run tests**

```bash
uv run python -m pytest -q \
  tests/integration/r2/production/test_manifest_recovery_integration.py
```

If already GREEN because Tasks 4/6 correctly reused existing Host atomicity, no production code change is required.

If RED, fix only the demonstrated R2/Host-seam defect and rerun.

- [ ] **Step 3: Run all M2 tests**

```bash
uv run python -m pytest -q \
  tests/unit/r2/production/ \
  tests/integration/r2/production/
```

Expected: PASS.

- [ ] **Step 4: Commit Task 7**

```bash
git add tests/integration/r2/production/test_manifest_recovery_integration.py \
        r2/production \
        <only exact allowlisted host files actually modified>

git commit -m "test(r2): verify artifact bridge recovery semantics"
```

Use only exact allowlisted host paths if a defect required a host change.

---

# Task 8: Architecture boundaries and regression protection

**Files:**
- Create: `tests/unit/r2/production/test_architecture_boundaries.py`
- Modify no production code unless the test exposes a real scope violation.

**Interfaces:**
- Consumes all M2 modules and Task 0 seam report.
- Produces no runtime API.

- [ ] **Step 1: Write architecture tests**

Tests must directly assert:

```text
- r2/production imports no Canon/Factual/Narrative/Director/provider-execution services
- no new R2 SQL migration exists
- no .r2_artifacts.json path is introduced
- dependency snapshots are direct only
- R2 metadata excludes provider/model/endpoint/seed/resolution/execution fingerprint
- Host files changed since M1 are a subset of Task 0 host allowlist
- R2-HOST-001 remains present/open
```

The host-file scope test should compute:

```python
changed = git diff --name-only 9330bcf3..HEAD
host_changed = {p for p in changed if p.startswith(("lib/", "server/"))}
assert host_changed <= set(discovery["host_files_if_patch_required"])
```

- [ ] **Step 2: Run architecture tests**

```bash
uv run python -m pytest -q \
  tests/unit/r2/production/test_architecture_boundaries.py
```

Expected: PASS.

- [ ] **Step 3: Run ArcReel audit gate now, before final verification**

```bash
uv run python scripts/audit_tests.py --check
```

Expected: zero violations.

- [ ] **Step 4: Run M2 + M1 focused regression**

```bash
uv run python -m pytest -q \
  tests/unit/r2/production/ \
  tests/integration/r2/production/ \
  tests/unit/r2/contracts/
```

Expected: PASS.

- [ ] **Step 5: Commit Task 8**

```bash
git add tests/unit/r2/production/test_architecture_boundaries.py
git commit -m "test(r2): enforce artifact bridge architecture boundaries"
```

---

# Task 9: Final M2 verification, evidence, and push

**Files:**
- Create:
  `docs/r2/evidence/R2_M2_VERIFICATION_<timestamp>.json`
- Create:
  `docs/r2/evidence/R2_M2_VERIFICATION_<timestamp>.md`

**Interfaces:**
- Produces milestone evidence only.

- [ ] **Step 1: Verify working tree and changed-file scope**

Run:

```bash
git status --short
git diff --name-only 9330bcf3..HEAD
```

Working tree must be clean before verification.

Changed paths must be limited to:

```text
docs/superpowers/specs/2026-09-06-r2-m2-artifact-bridge-design.md
docs/superpowers/plans/2026-09-06-r2-m2-artifact-bridge-implementation-plan.md
docs/r2/evidence/R2_M2_SEAM_DISCOVERY.*
r2/production/*
tests/unit/r2/production/*
tests/integration/r2/production/*
Task 0 allowlisted Host files only
```

No migration file is permitted.

- [ ] **Step 2: Run fresh M2 tests**

```bash
uv run python -m pytest -q \
  tests/unit/r2/production/ \
  tests/integration/r2/production/
```

Record exact unit/integration counts from fresh output.

- [ ] **Step 3: Run fresh M1 contract regression**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/
```

Expected: current M1 suite PASS.

- [ ] **Step 4: Run M0 R2 regression**

```bash
uv run python -m pytest -q \
  tests/unit/r2/test_bootstrap.py \
  tests/unit/scripts/r2/test_verify_frozen_registries.py \
  tests/unit/scripts/r2/test_known_blockers.py \
  tests/unit/scripts/r2/test_verify_baseline.py \
  tests/unit/scripts/r2/test_verify_postgres_baseline_script.py
```

Expected: PASS.

- [ ] **Step 5: Run frozen registry and host baseline**

```bash
uv run python scripts/r2/verify_frozen_registries.py
uv run python scripts/r2/verify_baseline.py
```

Expected: both PASS.

- [ ] **Step 6: Run original ArcReel focused Host regression**

Use the exact original M1 file set:

```bash
uv run python -m pytest -q \
  tests/integration/lib/test_artifact_manifest_storage.py \
  tests/integration/lib/test_speech_artifact_provenance_integration.py \
  tests/integration/lib/test_visual_artifact_provenance.py \
  tests/integration/lib/test_workflow_plan_adapters.py \
  tests/integration/lib/test_workflow_state.py \
  tests/integration/server/services/test_video_artifact_currency.py \
  tests/integration/server/services/test_workflow_planner.py \
  tests/unit/lib/test_artifact_manifest.py \
  tests/unit/lib/test_artifact_provenance.py \
  tests/unit/lib/test_speech_artifact_provenance.py \
  tests/unit/lib/test_workflow_plan.py \
  tests/unit/server/services/test_video_batch_admission.py
```

Required exactly:

```text
349 passed
```

Any different count is a stop condition.

- [ ] **Step 7: Run ArcReel audit gate**

```bash
uv run python scripts/audit_tests.py --check
```

Required:

```text
0 violations
```

Use the actual output language emitted by the script; do not bypass the gate.

- [ ] **Step 8: Create verification JSON from observed evidence**

Create:

```text
docs/r2/evidence/R2_M2_VERIFICATION_<timestamp>.json
```

Required structure:

```json
{
  "phase": "R2-M2",
  "milestone": "Artifact Bridge",
  "status": "PASS",
  "branch": "r2/main",
  "baseline_sha": "6ddedc775e7fe5f398b10081ab741985f7dceda7",
  "checks": {
    "m2_unit_tests": "<observed> PASS",
    "m2_integration_tests": "<observed> PASS",
    "m1_contract_regression": "<observed> PASS",
    "m0_r2_regression": "<observed> PASS",
    "frozen_registry": "PASS",
    "host_baseline": "PASS",
    "original_arcreel_focused_host_tests": "349 PASS",
    "arcreel_audit_gate": "PASS",
    "legacy_compatibility": "PASS",
    "selective_invalidation": "PASS",
    "failed_regeneration_preserves_master": "PASS",
    "unapproved_candidate_preserves_master": "PASS",
    "atomic_approved_master_promotion": "PASS",
    "restart_reload_persistence": "PASS",
    "r2_sql_migrations_added": "NONE",
    "r2_host_001": "OPEN / PRODUCTION_BLOCKER"
  },
  "host_files_modified": ["<exact allowlisted paths actually modified>"],
  "next": "R2-M3 Golden A General Content"
}
```

Replace all variable values with fresh observed results. Never guess test counts.

- [ ] **Step 9: Create verification Markdown**

Create the matching `.md` with the same evidence in readable form.

- [ ] **Step 10: Commit evidence**

```bash
git add docs/r2/evidence/R2_M2_VERIFICATION_*.json \
        docs/r2/evidence/R2_M2_VERIFICATION_*.md

git commit -m "test(r2): record M2 artifact bridge verification"
```

- [ ] **Step 11: Verify clean tree and push**

```bash
git status --short
git push
git rev-parse HEAD
git rev-parse origin/r2/main
```

Required:

```text
working tree = clean
HEAD == origin/r2/main
```

Only then report:

```text
R2-M2 STATUS: COMPLETE
```

---

# Plan Self-Review

## Spec coverage

- Single Artifact Manifest authority → Tasks 0, 4, 8.
- R2 metadata envelope → Task 1.
- ContentBasis required → Task 1.
- Direct dependency snapshots → Tasks 1–3.
- Resolver zero/multi-match → Task 2.
- Computed selective invalidation → Task 3.
- Legacy compatibility → Tasks 3–4.
- Malformed R2 → BLOCKED → Tasks 3–4.
- No execution fields in currency → Tasks 3, 8.
- ApprovedMaster explicit promotion → Task 5.
- Atomic active-version/master update → Task 6.
- Failed/unapproved candidate preservation → Tasks 5–6.
- Restart/reload/concurrency → Task 7.
- No R2 SQL artifact registry → Task 8.
- Host patch bounded by exact discovered seam → Tasks 0, 4, 6, 8.
- M1/M0/349/audit regression → Task 9.
- R2-HOST-001 remains open → Tasks 8–9.
- M3 boundary preserved → Global Constraints and Task 9.

## Dynamic exact-seam rule

The only paths intentionally not known at plan-authoring time are existing ArcReel Host files. This is not a placeholder: Task 0 deterministically produces the exact path/symbol allowlist in `R2_M2_SEAM_DISCOVERY.json` before any Host edit is permitted. Tasks 4, 6, 7, and 8 consume that recorded allowlist.

## Type consistency

Public M2 names are stable across all tasks:

```text
R2ContractRef
DependencySnapshot
ApprovedMasterMetadata
R2ArtifactMetadata

DependencyResolver
DependencyResolverRegistry
UnresolvedDependencyError
AmbiguousDependencyResolverError

ArtifactManifestPort
ArtifactHostSnapshot
R2CurrencyEvaluation
R2ArtifactBridge

PromotionResult
ProductionApprovalService
```

## Scope

M2 remains one coherent subsystem: semantic artifact metadata, dependency currency, and explicit production-master promotion over the existing ArcReel Artifact Manifest/version subsystem.

No M3 factual flow, Canon, provider execution, or new SQL authority is included.

---

# Execution Handoff

Recommended execution for this project:

**Inline execution using `superpowers:executing-plans`**, with checkpoints:

```text
Checkpoint A: Task 0 seam discovery
Checkpoint B: Tasks 1–3 pure R2 production layer
Checkpoint C: Tasks 4–6 real Host bridge + promotion
Checkpoint D: Tasks 7–8 recovery/architecture
Checkpoint E: Task 9 final verification
```

Task 0 must complete before any production code is touched.

Do not start M2 implementation until this plan has been reviewed and approved.
