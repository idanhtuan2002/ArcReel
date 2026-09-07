# R2-M1 Contract Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the provider-neutral R2 Contract Kernel as pure Pydantic v2 domain models plus deterministic content/execution fingerprint utilities, without modifying ArcReel runtime or persistence.

**Architecture:** R2-M1 lives under `r2/contracts/` and depends only on Python stdlib, Pydantic, and sibling R2 contract modules. Stable production-semantic models reject provider/runtime coupling; provider-specific fields are isolated to `ProviderRequest`. The implementation is TDD-first, uses ArcReel's required `tests/unit/...` taxonomy, and ends with M1 verification evidence.

**Tech Stack:** Python 3.13+, Pydantic v2, pytest, stdlib `enum.StrEnum`, `hashlib.sha256`, deterministic JSON serialization.

**Spec:** `docs/superpowers/specs/2026-09-06-r2-m1-contract-kernel-design.md`

## Global Constraints

- R2.1–R2.7 architecture freeze remains authoritative.
- R2-M0 Host Fork Foundation is COMPLETE.
- `r2/contracts/*` must not import ArcReel runtime/application modules such as `server.*` or runtime/provider/task modules from `lib.*`.
- No database migration in M1.
- No SQLAlchemy persistence mapping in M1.
- No ArcReel Artifact Manifest extension in M1.
- No DirectorAdapter, Canon, Method Router service, CapabilityRegistry service, provider execution, or UI work in M1.
- `SceneSpec`, `ShotSpec`, `MethodDecision`, and `PromptPlan` must remain provider-neutral.
- `ProviderRequest` is the adapter/runtime boundary and may contain provider/model/endpoint/payload/execution options.
- `SceneSpec.content_basis` and `ShotSpec.content_basis` are REQUIRED.
- Candidate lifecycle state and editorial selection state are independent.
- `FAILED` generation candidates cannot be `SELECTED`.
- Production readiness must not permit contradictory overall state vs requirement state.
- `content_fingerprint` and `execution_fingerprint` are separate and deterministic.
- Provider/model/execution-only changes must not change the content fingerprint.
- Tests live under `tests/unit/r2/contracts/`.
- Each task follows RED → minimal GREEN → focused regression → commit.
- Do not push until the milestone verification task is complete.

---

## File Map

### Production files

- `r2/contracts/__init__.py` — public exports for the M1 contract kernel.
- `r2/contracts/enums.py` — independent enum families.
- `r2/contracts/common.py` — shared Pydantic configuration, stable identity/version, JSON-compatible value validation helpers.
- `r2/contracts/content_basis.py` — `ContentBasis`.
- `r2/contracts/provenance.py` — `Provenance` and provenance actor enum usage.
- `r2/contracts/production.py` — `SceneSpec`, `ShotSpec`.
- `r2/contracts/preparation.py` — `ProductionBinding`, `VisualIdentityProfile`, readiness contracts.
- `r2/contracts/execution.py` — `MethodDecision`, `PromptPlan`, `ProviderRequest`.
- `r2/contracts/results.py` — `GenerationCandidate`, `ApprovedMaster`, `QualityFinding`, `QualityReport`.
- `r2/contracts/fingerprints.py` — canonical serialization plus content/execution fingerprint APIs.

### Test files

- `tests/unit/r2/contracts/test_common.py`
- `tests/unit/r2/contracts/test_content_basis.py`
- `tests/unit/r2/contracts/test_provenance.py`
- `tests/unit/r2/contracts/test_production.py`
- `tests/unit/r2/contracts/test_preparation.py`
- `tests/unit/r2/contracts/test_execution.py`
- `tests/unit/r2/contracts/test_results.py`
- `tests/unit/r2/contracts/test_fingerprints.py`
- `tests/unit/r2/contracts/test_architecture_boundaries.py`
- `tests/unit/r2/contracts/test_roundtrip.py`

### Evidence

- `docs/r2/evidence/R2_M1_VERIFICATION_<timestamp>.json`
- `docs/r2/evidence/R2_M1_VERIFICATION_<timestamp>.md`

---

### Task 1: Contract identity, shared configuration, JSON value support, and enum families

**Files:**
- Create: `r2/contracts/__init__.py`
- Create: `r2/contracts/common.py`
- Create: `r2/contracts/enums.py`
- Test: `tests/unit/r2/contracts/test_common.py`

**Interfaces:**
- Produces: `R2ContractModel`, `ContractIdentity`, `JSONValue`, `ensure_json_value(value)`.
- Produces enums:
  `CreativeApprovalStatus`, `ArtifactCurrencyStatus`, `RuntimeTaskStatus`,
  `CandidateSelectionStatus`, `GenerationLifecycleStatus`, `ReadinessState`,
  `ContentBasisType`, `ProductionMethod`, `ProductionBindingTarget`,
  `ProductionBindingRole`, `ProvenanceActor`, `ReviewerType`.
- Later tasks import these types only from `r2.contracts`.

- [ ] **Step 1: Write failing identity/config tests**

Create `tests/unit/r2/contracts/test_common.py`:

```python
from enum import Enum

import pytest
from pydantic import ValidationError

from r2.contracts import (
    ArtifactCurrencyStatus,
    CandidateSelectionStatus,
    ContractIdentity,
    CreativeApprovalStatus,
    GenerationLifecycleStatus,
    RuntimeTaskStatus,
    ensure_json_value,
)


def test_contract_identity_requires_non_empty_id_and_positive_version():
    identity = ContractIdentity(id="SH042", schema_version="2.1", version=7)
    assert identity.id == "SH042"
    assert identity.version == 7
    assert identity.schema_version == "2.1"

    with pytest.raises(ValidationError):
        ContractIdentity(id="", schema_version="2.1", version=1)

    with pytest.raises(ValidationError):
        ContractIdentity(id="SH042", schema_version="", version=1)

    with pytest.raises(ValidationError):
        ContractIdentity(id="SH042", schema_version="2.1", version=0)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        ContractIdentity(
            id="SH042",
            schema_version="2.1",
            version=1,
            provider="seedance",
        )


def test_status_families_are_distinct_enum_types():
    assert CreativeApprovalStatus.APPROVED.value == "APPROVED"
    assert ArtifactCurrencyStatus.CURRENT.value == "CURRENT"
    assert RuntimeTaskStatus.RUNNING.value == "RUNNING"
    assert CandidateSelectionStatus.SELECTED.value == "SELECTED"
    assert GenerationLifecycleStatus.GENERATED.value == "GENERATED"

    assert CreativeApprovalStatus is not ArtifactCurrencyStatus
    assert CandidateSelectionStatus is not GenerationLifecycleStatus


def test_ensure_json_value_rejects_arbitrary_python_objects():
    assert ensure_json_value({"nested": [1, "x", True, None, {"score": 0.5}]}) == {
        "nested": [1, "x", True, None, {"score": 0.5}]
    }

    class NotJSON:
        pass

    with pytest.raises(ValueError, match="JSON-compatible"):
        ensure_json_value({"bad": NotJSON()})
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```bash
uv run python -m pytest -q tests/unit/r2/contracts/test_common.py
```

Expected: collection/import failure because `r2.contracts` does not exist.

- [ ] **Step 3: Implement independent enum families**

Create `r2/contracts/enums.py`:

```python
from enum import StrEnum


class CreativeApprovalStatus(StrEnum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ArtifactCurrencyStatus(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    MISSING = "MISSING"
    BLOCKED = "BLOCKED"


class RuntimeTaskStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CandidateSelectionStatus(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    REJECTED = "REJECTED"
    SELECTED = "SELECTED"


class GenerationLifecycleStatus(StrEnum):
    GENERATED = "GENERATED"
    FAILED = "FAILED"


class ReadinessState(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class ContentBasisType(StrEnum):
    FACTUAL = "FACTUAL"
    NARRATIVE = "NARRATIVE"
    ADAPTATION = "ADAPTATION"


class ProductionMethod(StrEnum):
    REUSE = "REUSE"
    STOCK = "STOCK"
    SCREEN_CAPTURE = "SCREEN_CAPTURE"
    DETERMINISTIC = "DETERMINISTIC"
    GENERATED_IMAGE = "GENERATED_IMAGE"
    GENERATED_VIDEO = "GENERATED_VIDEO"
    COMPOSITE = "COMPOSITE"


class ProductionBindingTarget(StrEnum):
    SCENE = "SCENE"
    SHOT = "SHOT"


class ProductionBindingRole(StrEnum):
    CHARACTER = "CHARACTER"
    LOCATION = "LOCATION"
    PROP = "PROP"
    WARDROBE = "WARDROBE"
    VOICE = "VOICE"
    STYLE = "STYLE"
    SOURCE_FOOTAGE = "SOURCE_FOOTAGE"
    OPENING_FRAME = "OPENING_FRAME"
    ENDING_FRAME = "ENDING_FRAME"
    PREVIOUS_SHOT = "PREVIOUS_SHOT"


class ProvenanceActor(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    IMPORT = "IMPORT"


class ReviewerType(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
```

- [ ] **Step 4: Implement shared contract base and JSON-value validator**

Create `r2/contracts/common.py`:

```python
from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class R2ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        frozen=False,
    )


class ContractIdentity(R2ContractModel):
    id: NonEmptyStr
    schema_version: NonEmptyStr
    version: int = Field(ge=1)


def ensure_json_value(value: Any) -> JSONValue:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        return [ensure_json_value(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON-compatible mappings require string keys")
            result[key] = ensure_json_value(item)
        return result
    raise ValueError(f"value is not JSON-compatible: {type(value).__name__}")
```

- [ ] **Step 5: Export the public base types**

Create `r2/contracts/__init__.py`:

```python
from .common import ContractIdentity, JSONValue, R2ContractModel, ensure_json_value
from .enums import (
    ArtifactCurrencyStatus,
    CandidateSelectionStatus,
    ContentBasisType,
    CreativeApprovalStatus,
    GenerationLifecycleStatus,
    ProductionBindingRole,
    ProductionBindingTarget,
    ProductionMethod,
    ProvenanceActor,
    ReadinessState,
    ReviewerType,
    RuntimeTaskStatus,
)

__all__ = [
    "ArtifactCurrencyStatus",
    "CandidateSelectionStatus",
    "ContentBasisType",
    "ContractIdentity",
    "CreativeApprovalStatus",
    "GenerationLifecycleStatus",
    "JSONValue",
    "ProductionBindingRole",
    "ProductionBindingTarget",
    "ProductionMethod",
    "ProvenanceActor",
    "R2ContractModel",
    "ReadinessState",
    "ReviewerType",
    "RuntimeTaskStatus",
    "ensure_json_value",
]
```

- [ ] **Step 6: Run Task 1 tests and confirm GREEN**

Run:

```bash
uv run python -m pytest -q tests/unit/r2/contracts/test_common.py
```

Expected: `4 passed`.

- [ ] **Step 7: Run existing M0 R2 tests**

Run:

```bash
uv run python -m pytest -q \
  tests/unit/r2/test_bootstrap.py \
  tests/unit/scripts/r2/test_verify_frozen_registries.py \
  tests/unit/scripts/r2/test_known_blockers.py \
  tests/unit/scripts/r2/test_verify_baseline.py \
  tests/unit/scripts/r2/test_verify_postgres_baseline_script.py
```

Expected: existing M0 suite remains green.

- [ ] **Step 8: Commit Task 1**

```bash
git add r2/contracts tests/unit/r2/contracts/test_common.py
git commit -m "feat(r2): add contract identity and enums"
```

---

### Task 2: ContentBasis and Provenance

**Files:**
- Create: `r2/contracts/content_basis.py`
- Create: `r2/contracts/provenance.py`
- Modify: `r2/contracts/__init__.py`
- Test: `tests/unit/r2/contracts/test_content_basis.py`
- Test: `tests/unit/r2/contracts/test_provenance.py`

**Interfaces:**
- Consumes: `ContractIdentity`, `NonEmptyStr`, `R2ContractModel`, `ContentBasisType`, `ProvenanceActor`.
- Produces:
  `ContentBasis(basis_type, basis_version, refs)`.
- Produces:
  `Provenance(created_by, source_refs, created_at, ...)`.

- [ ] **Step 1: Write failing ContentBasis tests**

Create `tests/unit/r2/contracts/test_content_basis.py`:

```python
import pytest
from pydantic import ValidationError

from r2.contracts import ContentBasis, ContentBasisType


def test_content_basis_requires_non_empty_refs_and_deduplicates_deterministically():
    basis = ContentBasis(
        basis_type=ContentBasisType.NARRATIVE,
        basis_version="canon-v7",
        refs=["scene:2", "scene:1", "scene:2"],
    )
    assert basis.refs == ["scene:1", "scene:2"]

    with pytest.raises(ValidationError):
        ContentBasis(
            basis_type=ContentBasisType.NARRATIVE,
            basis_version="canon-v7",
            refs=[],
        )


def test_content_basis_requires_non_empty_basis_version():
    with pytest.raises(ValidationError):
        ContentBasis(
            basis_type=ContentBasisType.FACTUAL,
            basis_version="",
            refs=["claim:1"],
        )
```

- [ ] **Step 2: Write failing Provenance tests**

Create `tests/unit/r2/contracts/test_provenance.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from r2.contracts import Provenance, ProvenanceActor


def test_provenance_requires_timezone_aware_created_at():
    item = Provenance(
        created_by=ProvenanceActor.AGENT,
        source_refs=["source:b", "source:a", "source:b"],
        created_at=datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc),
        tool_or_adapter="r2-test",
        parent_revision_refs=["rev:2", "rev:1", "rev:2"],
    )
    assert item.source_refs == ["source:a", "source:b"]
    assert item.parent_revision_refs == ["rev:1", "rev:2"]

    with pytest.raises(ValidationError):
        Provenance(
            created_by=ProvenanceActor.SYSTEM,
            source_refs=[],
            created_at=datetime(2026, 9, 6, 10, 0),
        )
```

- [ ] **Step 3: Run Task 2 tests and confirm RED**

Run:

```bash
uv run python -m pytest -q \
  tests/unit/r2/contracts/test_content_basis.py \
  tests/unit/r2/contracts/test_provenance.py
```

Expected: import failure for `ContentBasis` / `Provenance`.

- [ ] **Step 4: Implement ContentBasis**

Create `r2/contracts/content_basis.py`:

```python
from pydantic import Field, field_validator

from .common import NonEmptyStr, R2ContractModel
from .enums import ContentBasisType


class ContentBasis(R2ContractModel):
    basis_type: ContentBasisType
    basis_version: NonEmptyStr
    refs: list[NonEmptyStr] = Field(min_length=1)

    @field_validator("refs")
    @classmethod
    def normalize_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))
```

- [ ] **Step 5: Implement Provenance**

Create `r2/contracts/provenance.py`:

```python
from datetime import datetime

from pydantic import AwareDatetime, Field, field_validator

from .common import NonEmptyStr, R2ContractModel
from .enums import ProvenanceActor


class Provenance(R2ContractModel):
    created_by: ProvenanceActor
    source_refs: list[NonEmptyStr] = Field(default_factory=list)
    tool_or_adapter: NonEmptyStr | None = None
    model: NonEmptyStr | None = None
    model_version: NonEmptyStr | None = None
    created_at: AwareDatetime
    operation_id: NonEmptyStr | None = None
    parent_revision_refs: list[NonEmptyStr] = Field(default_factory=list)

    @field_validator("source_refs", "parent_revision_refs")
    @classmethod
    def normalize_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))
```

- [ ] **Step 6: Export ContentBasis and Provenance**

Add to `r2/contracts/__init__.py`:

```python
from .content_basis import ContentBasis
from .provenance import Provenance
```

Add `"ContentBasis"` and `"Provenance"` to `__all__`.

- [ ] **Step 7: Run Task 2 tests and confirm GREEN**

Run:

```bash
uv run python -m pytest -q \
  tests/unit/r2/contracts/test_content_basis.py \
  tests/unit/r2/contracts/test_provenance.py
```

Expected: `3 passed`.

- [ ] **Step 8: Run Task 1–2 contract regression**

Run:

```bash
uv run python -m pytest -q tests/unit/r2/contracts/
```

Expected: all current contract tests pass.

- [ ] **Step 9: Commit Task 2**

```bash
git add r2/contracts tests/unit/r2/contracts
git commit -m "feat(r2): add content basis and provenance contracts"
```

---

### Task 3: Provider-neutral SceneSpec and ShotSpec

**Files:**
- Create: `r2/contracts/production.py`
- Modify: `r2/contracts/__init__.py`
- Test: `tests/unit/r2/contracts/test_production.py`

**Interfaces:**
- Consumes:
  `ContractIdentity`, `ContentBasis`, `CreativeApprovalStatus`,
  `ProductionMethod`, `ProductionBindingRole`.
- Produces:
  `SceneSpec` and `ShotSpec`.
- Later fingerprint task consumes `ShotSpec`.

- [ ] **Step 1: Write failing production-contract tests**

Create `tests/unit/r2/contracts/test_production.py`:

```python
import pytest
from pydantic import ValidationError

from r2.contracts import (
    ContentBasis,
    ContentBasisType,
    CreativeApprovalStatus,
    ProductionBindingRole,
    ProductionMethod,
    SceneSpec,
    ShotSpec,
)


def _basis():
    return ContentBasis(
        basis_type=ContentBasisType.NARRATIVE,
        basis_version="canon-v7",
        refs=["event:1"],
    )


def test_scene_spec_requires_content_basis_and_rejects_provider_fields():
    scene = SceneSpec(
        id="SC001",
        schema_version="2.1",
        version=1,
        source_artifact_ref="screenplay:7",
        source_unit_refs=["beat:2", "beat:1", "beat:2"],
        content_basis=_basis(),
        purpose="Establish the confrontation",
        duration_target=30.0,
        entity_refs=["char:b", "char:a", "char:b"],
        required_beats=["reveal", "reaction"],
        continuity_requirements=["costume:v3"],
        allowed_methods=[ProductionMethod.REUSE, ProductionMethod.GENERATED_VIDEO],
        approval_status=CreativeApprovalStatus.APPROVED,
    )
    assert scene.source_unit_refs == ["beat:1", "beat:2"]
    assert scene.entity_refs == ["char:a", "char:b"]

    with pytest.raises(ValidationError):
        SceneSpec(
            **scene.model_dump(),
            provider="seedance",
        )


def test_shot_spec_requires_positive_duration_and_rejects_provider_fields():
    shot = ShotSpec(
        id="SH042",
        schema_version="2.1",
        version=1,
        scene_id="SC001",
        content_basis=_basis(),
        purpose="Reaction close-up",
        target_duration=4.0,
        framing="close-up",
        camera="locked",
        entity_refs=["char:a"],
        required_continuity=["costume:v3"],
        required_reference_roles=[ProductionBindingRole.CHARACTER],
        allowed_methods=[ProductionMethod.GENERATED_VIDEO],
        quality_tier=3,
        approval_status=CreativeApprovalStatus.APPROVED,
    )
    assert shot.target_duration == 4.0

    with pytest.raises(ValidationError):
        ShotSpec(**shot.model_dump(), model="h3")

    with pytest.raises(ValidationError):
        ShotSpec(**{**shot.model_dump(), "target_duration": 0})


def test_required_beat_order_is_preserved():
    scene = SceneSpec(
        id="SC002",
        schema_version="2.1",
        version=1,
        source_artifact_ref="screenplay:7",
        source_unit_refs=["beat:1"],
        content_basis=_basis(),
        purpose="Escalation",
        duration_target=40,
        required_beats=["first", "second", "third"],
        allowed_methods=[ProductionMethod.DETERMINISTIC],
        approval_status=CreativeApprovalStatus.DRAFT,
    )
    assert scene.required_beats == ["first", "second", "third"]
```

- [ ] **Step 2: Run production tests and confirm RED**

Run:

```bash
uv run python -m pytest -q tests/unit/r2/contracts/test_production.py
```

Expected: import failure for `SceneSpec` / `ShotSpec`.

- [ ] **Step 3: Implement SceneSpec and ShotSpec**

Create `r2/contracts/production.py`:

```python
from pydantic import Field, field_validator

from .common import ContractIdentity, NonEmptyStr
from .content_basis import ContentBasis
from .enums import (
    CreativeApprovalStatus,
    ProductionBindingRole,
    ProductionMethod,
)


class SceneSpec(ContractIdentity):
    source_artifact_ref: NonEmptyStr
    source_unit_refs: list[NonEmptyStr] = Field(default_factory=list)
    content_basis: ContentBasis

    purpose: NonEmptyStr
    duration_target: float = Field(gt=0)

    temporal_context: NonEmptyStr | None = None
    location_ref: NonEmptyStr | None = None
    entity_refs: list[NonEmptyStr] = Field(default_factory=list)

    required_beats: list[NonEmptyStr] = Field(default_factory=list)
    continuity_requirements: list[NonEmptyStr] = Field(default_factory=list)

    allowed_methods: list[ProductionMethod] = Field(min_length=1)
    approval_status: CreativeApprovalStatus

    @field_validator("source_unit_refs", "entity_refs")
    @classmethod
    def normalize_set_like_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))


class ShotSpec(ContractIdentity):
    scene_id: NonEmptyStr
    content_basis: ContentBasis

    purpose: NonEmptyStr
    target_duration: float = Field(gt=0)

    framing: NonEmptyStr
    camera: NonEmptyStr

    entity_refs: list[NonEmptyStr] = Field(default_factory=list)
    audio_intent: NonEmptyStr | None = None

    required_continuity: list[NonEmptyStr] = Field(default_factory=list)
    required_reference_roles: list[ProductionBindingRole] = Field(default_factory=list)

    allowed_methods: list[ProductionMethod] = Field(min_length=1)
    quality_tier: int = Field(ge=0)

    approval_status: CreativeApprovalStatus

    @field_validator("entity_refs")
    @classmethod
    def normalize_entity_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))
```

- [ ] **Step 4: Export SceneSpec and ShotSpec**

Add to `r2/contracts/__init__.py`:

```python
from .production import SceneSpec, ShotSpec
```

Add both names to `__all__`.

- [ ] **Step 5: Run production tests and confirm GREEN**

Run:

```bash
uv run python -m pytest -q tests/unit/r2/contracts/test_production.py
```

Expected: `3 passed`.

- [ ] **Step 6: Run current contract regression**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/
```

Expected: all current contract tests pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add r2/contracts tests/unit/r2/contracts/test_production.py
git commit -m "feat(r2): add production semantic contracts"
```

---

### Task 4: ProductionBinding, VisualIdentityProfile, and ProductionReadiness

**Files:**
- Create: `r2/contracts/preparation.py`
- Modify: `r2/contracts/__init__.py`
- Test: `tests/unit/r2/contracts/test_preparation.py`

**Interfaces:**
- Consumes:
  `ContractIdentity`, `NonEmptyStr`, `ProductionBindingRole`,
  `ProductionBindingTarget`, `ReadinessState`.
- Produces:
  `ProductionBinding`, `VisualIdentityProfile`,
  `ReadinessRequirement`, `ProductionReadiness`.
- Later fingerprint task consumes `ProductionBinding`.

- [ ] **Step 1: Write failing preparation tests**

Create `tests/unit/r2/contracts/test_preparation.py`:

```python
import pytest
from pydantic import ValidationError

from r2.contracts import (
    ProductionBinding,
    ProductionBindingRole,
    ProductionBindingTarget,
    ProductionReadiness,
    ReadinessRequirement,
    ReadinessState,
    VisualIdentityProfile,
)


def test_production_binding_keeps_semantic_and_production_identity_separate():
    binding = ProductionBinding(
        id="B001",
        schema_version="2.1",
        version=1,
        target_type=ProductionBindingTarget.SHOT,
        target_id="SH042",
        semantic_ref="character:maya",
        production_ref="character-profile:maya-v3",
        role=ProductionBindingRole.CHARACTER,
        asset_refs=["asset:b", "asset:a", "asset:b"],
    )
    assert binding.semantic_ref != binding.production_ref
    assert binding.asset_refs == ["asset:a", "asset:b"]


def test_readiness_is_derived_from_required_requirements():
    blocked = ProductionReadiness(
        id="READY-SH042",
        target_id="SH042",
        requirements=[
            ReadinessRequirement(
                requirement_id="char",
                role=ProductionBindingRole.CHARACTER,
                required=True,
                status=ReadinessState.BLOCKED,
                reason="character binding missing",
            ),
            ReadinessRequirement(
                requirement_id="style",
                role=ProductionBindingRole.STYLE,
                required=False,
                status=ReadinessState.BLOCKED,
                reason="optional style reference missing",
            ),
        ],
    )
    assert blocked.state is ReadinessState.BLOCKED

    ready = ProductionReadiness(
        id="READY-SH043",
        target_id="SH043",
        requirements=[
            ReadinessRequirement(
                requirement_id="char",
                role=ProductionBindingRole.CHARACTER,
                required=True,
                status=ReadinessState.READY,
                resolved_binding="B001",
            ),
            ReadinessRequirement(
                requirement_id="style",
                role=ProductionBindingRole.STYLE,
                required=False,
                status=ReadinessState.BLOCKED,
            ),
        ],
    )
    assert ready.state is ReadinessState.READY


def test_required_ready_requirement_must_have_resolved_binding():
    with pytest.raises(ValidationError, match="resolved_binding"):
        ReadinessRequirement(
            requirement_id="char",
            role=ProductionBindingRole.CHARACTER,
            required=True,
            status=ReadinessState.READY,
        )


def test_visual_identity_profile_preserves_lock_order():
    profile = VisualIdentityProfile(
        id="VIP-MAYA",
        schema_version="2.1",
        version=1,
        semantic_character_ref="character:maya",
        costume_locks=["jacket", "boots"],
        accessory_locks=["ring", "watch"],
        approved_reference_refs=["asset:b", "asset:a", "asset:b"],
    )
    assert profile.costume_locks == ["jacket", "boots"]
    assert profile.approved_reference_refs == ["asset:a", "asset:b"]
```

- [ ] **Step 2: Run preparation tests and confirm RED**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/test_preparation.py
```

Expected: import failure for preparation contracts.

- [ ] **Step 3: Implement ProductionBinding and VisualIdentityProfile**

Create `r2/contracts/preparation.py`:

```python
from pydantic import Field, computed_field, field_validator, model_validator

from .common import ContractIdentity, NonEmptyStr, R2ContractModel
from .enums import (
    ProductionBindingRole,
    ProductionBindingTarget,
    ReadinessState,
)


class ProductionBinding(ContractIdentity):
    target_type: ProductionBindingTarget
    target_id: NonEmptyStr
    semantic_ref: NonEmptyStr
    production_ref: NonEmptyStr
    role: ProductionBindingRole
    asset_refs: list[NonEmptyStr] = Field(default_factory=list)
    variant_ref: NonEmptyStr | None = None
    state_ref: NonEmptyStr | None = None

    @field_validator("asset_refs")
    @classmethod
    def normalize_asset_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))


class VisualIdentityProfile(ContractIdentity):
    semantic_character_ref: NonEmptyStr
    face_master_ref: NonEmptyStr | None = None
    full_body_master_ref: NonEmptyStr | None = None
    side_profile_ref: NonEmptyStr | None = None
    hairstyle_lock: NonEmptyStr | None = None
    costume_locks: list[NonEmptyStr] = Field(default_factory=list)
    accessory_locks: list[NonEmptyStr] = Field(default_factory=list)
    state_variants: list[NonEmptyStr] = Field(default_factory=list)
    approved_reference_refs: list[NonEmptyStr] = Field(default_factory=list)

    @field_validator("approved_reference_refs")
    @classmethod
    def normalize_reference_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))
```

- [ ] **Step 4: Implement readiness contracts with derived state**

Append to `r2/contracts/preparation.py`:

```python
class ReadinessRequirement(R2ContractModel):
    requirement_id: NonEmptyStr
    role: ProductionBindingRole
    required: bool
    status: ReadinessState
    resolved_binding: NonEmptyStr | None = None
    reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_resolution(self):
        if self.required and self.status is ReadinessState.READY and self.resolved_binding is None:
            raise ValueError("required READY requirement must include resolved_binding")
        return self


class ProductionReadiness(R2ContractModel):
    id: NonEmptyStr
    target_id: NonEmptyStr
    requirements: list[ReadinessRequirement] = Field(default_factory=list)

    @computed_field
    @property
    def state(self) -> ReadinessState:
        for requirement in self.requirements:
            if requirement.required and requirement.status is not ReadinessState.READY:
                return ReadinessState.BLOCKED
        return ReadinessState.READY
```

- [ ] **Step 5: Export preparation contracts**

Add to `r2/contracts/__init__.py`:

```python
from .preparation import (
    ProductionBinding,
    ProductionReadiness,
    ReadinessRequirement,
    VisualIdentityProfile,
)
```

Add names to `__all__`.

- [ ] **Step 6: Run preparation tests and confirm GREEN**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/test_preparation.py
```

Expected: `4 passed`.

- [ ] **Step 7: Run current contract regression**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/
```

Expected: all current contract tests pass.

- [ ] **Step 8: Commit Task 4**

```bash
git add r2/contracts tests/unit/r2/contracts/test_preparation.py
git commit -m "feat(r2): add production preparation contracts"
```

---

### Task 5: MethodDecision, PromptPlan, and ProviderRequest

**Files:**
- Create: `r2/contracts/execution.py`
- Modify: `r2/contracts/__init__.py`
- Test: `tests/unit/r2/contracts/test_execution.py`

**Interfaces:**
- Consumes:
  `ContractIdentity`, `NonEmptyStr`, `R2ContractModel`,
  `JSONValue`, `ensure_json_value`, `ProductionMethod`.
- Produces:
  `MethodDecision`, `PromptPlan`, `ProviderRequest`.
- Fingerprint task consumes ProviderRequest execution fields only indirectly via explicit parameters.

- [ ] **Step 1: Write failing execution-boundary tests**

Create `tests/unit/r2/contracts/test_execution.py`:

```python
import pytest
from pydantic import ValidationError

from r2.contracts import (
    MethodDecision,
    ProductionMethod,
    PromptPlan,
    ProviderRequest,
)


def test_method_decision_is_provider_neutral():
    decision = MethodDecision(
        id="MD-SH042",
        target_ref="SH042",
        method=ProductionMethod.GENERATED_VIDEO,
        rationale="Continuity requires motion",
        capability_requirements=["i2v", "reference-image"],
        cost_class="MEDIUM",
        quality_tier=3,
        fallback_methods=[ProductionMethod.GENERATED_IMAGE, ProductionMethod.REUSE],
    )
    with pytest.raises(ValidationError):
        MethodDecision(**decision.model_dump(), provider="seedance")


def test_prompt_plan_is_provider_neutral():
    plan = PromptPlan(
        id="PP-SH042",
        schema_version="2.1",
        version=1,
        target_ref="SH042",
        semantic_instruction="Maya reacts to the reveal",
        positive_prompt="close-up reaction",
        negative_prompt="identity drift",
        identity_tokens=["maya-v3"],
        style_tokens=["noir", "soft-key"],
        reference_binding_ids=["B001"],
        exclusions=["extra fingers"],
        compiler_version="butterfly-compiler-v1",
    )
    with pytest.raises(ValidationError):
        PromptPlan(**plan.model_dump(), endpoint="https://example.invalid")


def test_provider_request_accepts_execution_fields_and_rejects_python_objects():
    request = ProviderRequest(
        id="REQ-SH042-1",
        method_decision_ref="MD-SH042",
        prompt_plan_ref="PP-SH042",
        provider="seedance",
        model="seedance-2.5",
        endpoint="i2v",
        payload={"prompt": "hello", "refs": ["asset:1"]},
        execution_options={"seed": 42, "resolution": "1080p"},
        adapter_version="seedance-adapter-v2",
    )
    assert request.provider == "seedance"

    class NotJSON:
        pass

    with pytest.raises(ValidationError, match="JSON-compatible"):
        ProviderRequest(
            **{
                **request.model_dump(),
                "payload": {"bad": NotJSON()},
            }
        )
```

- [ ] **Step 2: Run execution tests and confirm RED**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/test_execution.py
```

Expected: import failure for execution contracts.

- [ ] **Step 3: Implement MethodDecision and PromptPlan**

Create `r2/contracts/execution.py`:

```python
from typing import Any

from pydantic import Field, field_validator

from .common import (
    ContractIdentity,
    JSONValue,
    NonEmptyStr,
    R2ContractModel,
    ensure_json_value,
)
from .enums import ProductionMethod


class MethodDecision(R2ContractModel):
    id: NonEmptyStr
    target_ref: NonEmptyStr
    method: ProductionMethod
    rationale: NonEmptyStr
    capability_requirements: list[NonEmptyStr] = Field(default_factory=list)
    cost_class: NonEmptyStr
    quality_tier: int = Field(ge=0)
    fallback_methods: list[ProductionMethod] = Field(default_factory=list)


class PromptPlan(ContractIdentity):
    target_ref: NonEmptyStr
    semantic_instruction: NonEmptyStr
    positive_prompt: str = ""
    negative_prompt: str = ""
    identity_tokens: list[NonEmptyStr] = Field(default_factory=list)
    style_tokens: list[NonEmptyStr] = Field(default_factory=list)
    reference_binding_ids: list[NonEmptyStr] = Field(default_factory=list)
    exclusions: list[NonEmptyStr] = Field(default_factory=list)
    compiler_version: NonEmptyStr
```

- [ ] **Step 4: Implement ProviderRequest JSON boundary**

Append:

```python
class ProviderRequest(R2ContractModel):
    id: NonEmptyStr
    method_decision_ref: NonEmptyStr
    prompt_plan_ref: NonEmptyStr | None = None
    provider: NonEmptyStr
    model: NonEmptyStr
    endpoint: NonEmptyStr
    payload: dict[str, JSONValue]
    execution_options: dict[str, JSONValue] = Field(default_factory=dict)
    adapter_version: NonEmptyStr

    @field_validator("payload", "execution_options", mode="before")
    @classmethod
    def validate_json_mappings(cls, value: Any) -> dict[str, JSONValue]:
        normalized = ensure_json_value(value)
        if not isinstance(normalized, dict):
            raise ValueError("provider execution fields must be JSON-compatible mappings")
        return normalized
```

- [ ] **Step 5: Export execution contracts**

Add to `r2/contracts/__init__.py`:

```python
from .execution import MethodDecision, PromptPlan, ProviderRequest
```

Add names to `__all__`.

- [ ] **Step 6: Run execution tests and confirm GREEN**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/test_execution.py
```

Expected: `3 passed`.

- [ ] **Step 7: Run current contract regression**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/
```

Expected: all current contract tests pass.

- [ ] **Step 8: Commit Task 5**

```bash
git add r2/contracts tests/unit/r2/contracts/test_execution.py
git commit -m "feat(r2): add execution boundary contracts"
```

---

### Task 6: GenerationCandidate, ApprovedMaster, QualityReport

**Files:**
- Create: `r2/contracts/results.py`
- Modify: `r2/contracts/__init__.py`
- Test: `tests/unit/r2/contracts/test_results.py`

**Interfaces:**
- Consumes:
  `CandidateSelectionStatus`, `GenerationLifecycleStatus`,
  `NonEmptyStr`, `R2ContractModel`, `ReviewerType`.
- Produces:
  `GenerationCandidate`, `ApprovedMaster`, `QualityFinding`, `QualityReport`.

- [ ] **Step 1: Write failing result-contract tests**

Create `tests/unit/r2/contracts/test_results.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from r2.contracts import (
    ApprovedMaster,
    CandidateSelectionStatus,
    GenerationCandidate,
    GenerationLifecycleStatus,
    QualityFinding,
    QualityReport,
    ReviewerType,
)


def _candidate(**overrides):
    data = dict(
        id="CAND-1",
        target_ref="SH042",
        content_fingerprint="a" * 64,
        execution_fingerprint="b" * 64,
        provider_execution_ref="job:123",
        output_asset_ref="asset:generated-1",
        lifecycle_state=GenerationLifecycleStatus.GENERATED,
        selection_state=CandidateSelectionStatus.UNREVIEWED,
    )
    data.update(overrides)
    return GenerationCandidate(**data)


def test_generation_candidate_separates_lifecycle_and_selection():
    item = _candidate()
    assert item.lifecycle_state is GenerationLifecycleStatus.GENERATED
    assert item.selection_state is CandidateSelectionStatus.UNREVIEWED


def test_failed_generation_cannot_be_selected():
    with pytest.raises(ValidationError, match="FAILED candidate cannot be SELECTED"):
        _candidate(
            lifecycle_state=GenerationLifecycleStatus.FAILED,
            selection_state=CandidateSelectionStatus.SELECTED,
        )


def test_selected_candidate_must_be_generated():
    selected = _candidate(selection_state=CandidateSelectionStatus.SELECTED)
    assert selected.lifecycle_state is GenerationLifecycleStatus.GENERATED


def test_approved_master_is_explicit_not_latest_generation():
    master = ApprovedMaster(
        id="MASTER-SH042",
        target_ref="SH042",
        selected_candidate_id="CAND-1",
        approval_record="approval:77",
        selected_at=datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc),
        selected_by="showrunner:1",
    )
    assert master.selected_candidate_id == "CAND-1"


def test_quality_report_score_is_bounded():
    report = QualityReport(
        id="QR-1",
        target_ref="CAND-1",
        checks=["identity", "continuity"],
        score=0.95,
        blocking_findings=[],
        advisory_findings=[QualityFinding(code="MINOR", message="tiny drift", blocking=False)],
        reviewer_type=ReviewerType.AGENT,
        created_at=datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc),
    )
    assert report.score == 0.95

    with pytest.raises(ValidationError):
        QualityReport(**{**report.model_dump(), "score": 1.5})
```

- [ ] **Step 2: Run result tests and confirm RED**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/test_results.py
```

Expected: import failure for result contracts.

- [ ] **Step 3: Implement result contracts and state invariant**

Create `r2/contracts/results.py`:

```python
from pydantic import AwareDatetime, Field, model_validator

from .common import NonEmptyStr, R2ContractModel
from .enums import (
    CandidateSelectionStatus,
    GenerationLifecycleStatus,
    ReviewerType,
)


class GenerationCandidate(R2ContractModel):
    id: NonEmptyStr
    target_ref: NonEmptyStr
    content_fingerprint: NonEmptyStr
    execution_fingerprint: NonEmptyStr
    provider_execution_ref: NonEmptyStr
    output_asset_ref: NonEmptyStr
    quality_report_ref: NonEmptyStr | None = None
    lifecycle_state: GenerationLifecycleStatus
    selection_state: CandidateSelectionStatus

    @model_validator(mode="after")
    def validate_state_combination(self):
        if (
            self.lifecycle_state is GenerationLifecycleStatus.FAILED
            and self.selection_state is CandidateSelectionStatus.SELECTED
        ):
            raise ValueError("FAILED candidate cannot be SELECTED")
        if (
            self.selection_state is CandidateSelectionStatus.SELECTED
            and self.lifecycle_state is not GenerationLifecycleStatus.GENERATED
        ):
            raise ValueError("SELECTED candidate must be GENERATED")
        return self


class ApprovedMaster(R2ContractModel):
    id: NonEmptyStr
    target_ref: NonEmptyStr
    selected_candidate_id: NonEmptyStr
    approval_record: NonEmptyStr
    selected_at: AwareDatetime
    selected_by: NonEmptyStr


class QualityFinding(R2ContractModel):
    code: NonEmptyStr
    message: NonEmptyStr
    blocking: bool


class QualityReport(R2ContractModel):
    id: NonEmptyStr
    target_ref: NonEmptyStr
    checks: list[NonEmptyStr] = Field(default_factory=list)
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    blocking_findings: list[QualityFinding] = Field(default_factory=list)
    advisory_findings: list[QualityFinding] = Field(default_factory=list)
    reviewer_type: ReviewerType
    created_at: AwareDatetime
```

- [ ] **Step 4: Export result contracts**

Add to `r2/contracts/__init__.py`:

```python
from .results import (
    ApprovedMaster,
    GenerationCandidate,
    QualityFinding,
    QualityReport,
)
```

Add names to `__all__`.

- [ ] **Step 5: Run result tests and confirm GREEN**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/test_results.py
```

Expected: `5 passed`.

- [ ] **Step 6: Run current contract regression**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/
```

Expected: all current contract tests pass.

- [ ] **Step 7: Commit Task 6**

```bash
git add r2/contracts tests/unit/r2/contracts/test_results.py
git commit -m "feat(r2): add generation result contracts"
```

---

### Task 7: Deterministic canonical serialization and fingerprint split

**Files:**
- Create: `r2/contracts/fingerprints.py`
- Modify: `r2/contracts/__init__.py`
- Test: `tests/unit/r2/contracts/test_fingerprints.py`

**Interfaces:**
- Consumes:
  `ShotSpec`, `ProductionBinding`, `JSONValue`, `ensure_json_value`.
- Produces:
  `canonical_json_bytes(value) -> bytes`.
- Produces:
  `compute_content_fingerprint(...) -> str`.
- Produces:
  `compute_execution_fingerprint(...) -> str`.

- [ ] **Step 1: Write failing fingerprint tests**

Create `tests/unit/r2/contracts/test_fingerprints.py`:

```python
from r2.contracts import (
    CandidateSelectionStatus,
    ContentBasis,
    ContentBasisType,
    CreativeApprovalStatus,
    ProductionBinding,
    ProductionBindingRole,
    ProductionBindingTarget,
    ProductionMethod,
    ShotSpec,
    compute_content_fingerprint,
    compute_execution_fingerprint,
)


def _shot(purpose="Reaction close-up"):
    return ShotSpec(
        id="SH042",
        schema_version="2.1",
        version=1,
        scene_id="SC001",
        content_basis=ContentBasis(
            basis_type=ContentBasisType.NARRATIVE,
            basis_version="canon-v7",
            refs=["event:1"],
        ),
        purpose=purpose,
        target_duration=4.0,
        framing="close-up",
        camera="locked",
        entity_refs=["character:maya"],
        required_continuity=["costume:v3"],
        required_reference_roles=[ProductionBindingRole.CHARACTER],
        allowed_methods=[ProductionMethod.GENERATED_VIDEO],
        quality_tier=3,
        approval_status=CreativeApprovalStatus.APPROVED,
    )


def _binding(version=1):
    return ProductionBinding(
        id="B001",
        schema_version="2.1",
        version=version,
        target_type=ProductionBindingTarget.SHOT,
        target_id="SH042",
        semantic_ref="character:maya",
        production_ref="character-profile:maya-v3",
        role=ProductionBindingRole.CHARACTER,
        asset_refs=["asset:char-master"],
    )


def test_content_fingerprint_is_deterministic_and_ignores_set_input_order():
    a = compute_content_fingerprint(
        shot_spec=_shot(),
        bindings=[_binding()],
        visual_identity_refs=["vip:b", "vip:a"],
        approved_source_asset_refs=["src:b", "src:a"],
    )
    b = compute_content_fingerprint(
        shot_spec=_shot(),
        bindings=[_binding()],
        visual_identity_refs=["vip:a", "vip:b"],
        approved_source_asset_refs=["src:a", "src:b"],
    )
    assert a == b
    assert len(a) == 64


def test_provider_changes_only_execution_fingerprint():
    content = compute_content_fingerprint(
        shot_spec=_shot(),
        bindings=[_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )

    e1 = compute_execution_fingerprint(
        provider="seedance",
        model="2.5",
        endpoint="i2v",
        seed=42,
        resolution="1080p",
        generation_settings={"cfg": 7.0},
        prompt_compiler_version="compiler-v1",
        provider_adapter_version="adapter-v1",
    )
    e2 = compute_execution_fingerprint(
        provider="h3",
        model="h3-v1",
        endpoint="i2v",
        seed=42,
        resolution="1080p",
        generation_settings={"cfg": 7.0},
        prompt_compiler_version="compiler-v1",
        provider_adapter_version="adapter-v1",
    )

    assert e1 != e2

    content_again = compute_content_fingerprint(
        shot_spec=_shot(),
        bindings=[_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    assert content_again == content


def test_semantic_change_changes_content_fingerprint():
    a = compute_content_fingerprint(
        shot_spec=_shot("Reaction close-up"),
        bindings=[_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    b = compute_content_fingerprint(
        shot_spec=_shot("Angry reaction close-up"),
        bindings=[_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    assert a != b


def test_binding_version_change_changes_content_fingerprint():
    a = compute_content_fingerprint(
        shot_spec=_shot(),
        bindings=[_binding(version=1)],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    b = compute_content_fingerprint(
        shot_spec=_shot(),
        bindings=[_binding(version=2)],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    assert a != b
```

- [ ] **Step 2: Run fingerprint tests and confirm RED**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/test_fingerprints.py
```

Expected: import failure for fingerprint functions.

- [ ] **Step 3: Implement canonical JSON and SHA-256 helper**

Create `r2/contracts/fingerprints.py`:

```python
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from .common import JSONValue, ensure_json_value
from .preparation import ProductionBinding
from .production import ShotSpec


def canonical_json_bytes(value: JSONValue) -> bytes:
    normalized = ensure_json_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: JSONValue) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
```

- [ ] **Step 4: Implement content fingerprint**

Append:

```python
def compute_content_fingerprint(
    *,
    shot_spec: ShotSpec,
    bindings: Sequence[ProductionBinding],
    visual_identity_refs: Sequence[str],
    approved_source_asset_refs: Sequence[str],
) -> str:
    binding_payload = [
        binding.model_dump(mode="json")
        for binding in sorted(
            bindings,
            key=lambda item: (item.id, item.version),
        )
    ]

    payload: dict[str, JSONValue] = {
        "shot_spec": shot_spec.model_dump(mode="json"),
        "bindings": binding_payload,
        "visual_identity_refs": sorted(set(visual_identity_refs)),
        "approved_source_asset_refs": sorted(set(approved_source_asset_refs)),
    }
    return _sha256(payload)
```

- [ ] **Step 5: Implement execution fingerprint**

Append:

```python
def compute_execution_fingerprint(
    *,
    provider: str,
    model: str,
    endpoint: str,
    seed: int | None,
    resolution: str | None,
    generation_settings: Mapping[str, JSONValue],
    prompt_compiler_version: str,
    provider_adapter_version: str,
) -> str:
    payload: dict[str, JSONValue] = {
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "seed": seed,
        "resolution": resolution,
        "generation_settings": ensure_json_value(dict(generation_settings)),
        "prompt_compiler_version": prompt_compiler_version,
        "provider_adapter_version": provider_adapter_version,
    }
    return _sha256(payload)
```

- [ ] **Step 6: Export fingerprint APIs**

Add to `r2/contracts/__init__.py`:

```python
from .fingerprints import (
    canonical_json_bytes,
    compute_content_fingerprint,
    compute_execution_fingerprint,
)
```

Add names to `__all__`.

- [ ] **Step 7: Run fingerprint tests and confirm GREEN**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/test_fingerprints.py
```

Expected: `4 passed`.

- [ ] **Step 8: Run current contract regression**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/
```

Expected: all current contract tests pass.

- [ ] **Step 9: Commit Task 7**

```bash
git add r2/contracts tests/unit/r2/contracts/test_fingerprints.py
git commit -m "feat(r2): add deterministic contract fingerprints"
```

---

### Task 8: Architecture boundaries and JSON round-trip regression

**Files:**
- Create: `tests/unit/r2/contracts/test_architecture_boundaries.py`
- Create: `tests/unit/r2/contracts/test_roundtrip.py`
- Modify only if tests expose a contract bug: files under `r2/contracts/`.

**Interfaces:**
- Consumes all public M1 contracts.
- Produces no new runtime API.
- Protects provider-neutrality, import boundaries, registry alignment, and serialization stability.

- [ ] **Step 1: Write architecture-boundary tests**

Create `tests/unit/r2/contracts/test_architecture_boundaries.py`:

```python
from __future__ import annotations

import ast
import json
from pathlib import Path

from r2.bootstrap import frozen_docs_dir
from r2.contracts import MethodDecision, PromptPlan, SceneSpec, ShotSpec


FORBIDDEN_PROVIDER_FIELDS = {
    "provider",
    "model",
    "endpoint",
    "payload",
    "provider_job_id",
    "provider_request",
    "execution_options",
}


def test_provider_neutral_contracts_have_no_provider_runtime_fields():
    for model in (SceneSpec, ShotSpec, MethodDecision, PromptPlan):
        fields = set(model.model_fields)
        assert not (fields & FORBIDDEN_PROVIDER_FIELDS), (
            model.__name__,
            fields & FORBIDDEN_PROVIDER_FIELDS,
        )


def test_frozen_registry_forbidden_fields_are_not_weakened():
    registry = json.loads((frozen_docs_dir() / "R2_03_CONTRACT_REGISTRY.json").read_text())
    by_name = {item["name"]: item for item in registry["contracts"]}

    for name in ("SceneSpec", "ShotSpec"):
        forbidden = set(by_name[name].get("forbidden_fields", []))
        assert {"provider", "model", "endpoint", "payload", "provider_job_id"} <= forbidden


def test_contract_modules_do_not_import_arcreel_runtime_layers():
    root = Path(__file__).resolve().parents[4] / "r2" / "contracts"
    forbidden_prefixes = ("server", "lib")

    violations: list[str] = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if name == forbidden_prefixes or name.startswith(("server.", "lib.")):
                    violations.append(f"{path.name}: {name}")

    assert violations == []
```

- [ ] **Step 2: Write round-trip tests**

Create `tests/unit/r2/contracts/test_roundtrip.py`:

```python
import json
from datetime import datetime, timezone

from r2.contracts import (
    CandidateSelectionStatus,
    ContentBasis,
    ContentBasisType,
    CreativeApprovalStatus,
    GenerationCandidate,
    GenerationLifecycleStatus,
    ProductionBindingRole,
    ProductionMethod,
    PromptPlan,
    Provenance,
    ProvenanceActor,
    SceneSpec,
)


def _roundtrip(model):
    raw = model.model_dump(mode="json")
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    decoded = json.loads(encoded)
    restored = type(model).model_validate(decoded)
    assert restored == model


def test_content_basis_round_trip():
    _roundtrip(
        ContentBasis(
            basis_type=ContentBasisType.FACTUAL,
            basis_version="research-v3",
            refs=["claim:1"],
        )
    )


def test_provenance_timezone_round_trip():
    _roundtrip(
        Provenance(
            created_by=ProvenanceActor.SYSTEM,
            source_refs=["source:1"],
            created_at=datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc),
        )
    )


def test_scene_spec_round_trip():
    _roundtrip(
        SceneSpec(
            id="SC001",
            schema_version="2.1",
            version=1,
            source_artifact_ref="script:1",
            source_unit_refs=["unit:1"],
            content_basis=ContentBasis(
                basis_type=ContentBasisType.NARRATIVE,
                basis_version="canon-v1",
                refs=["event:1"],
            ),
            purpose="Opening",
            duration_target=20,
            required_beats=["setup"],
            allowed_methods=[ProductionMethod.REUSE],
            approval_status=CreativeApprovalStatus.APPROVED,
        )
    )


def test_generation_candidate_round_trip():
    _roundtrip(
        GenerationCandidate(
            id="CAND-1",
            target_ref="SH001",
            content_fingerprint="a" * 64,
            execution_fingerprint="b" * 64,
            provider_execution_ref="job:1",
            output_asset_ref="asset:1",
            lifecycle_state=GenerationLifecycleStatus.GENERATED,
            selection_state=CandidateSelectionStatus.UNREVIEWED,
        )
    )
```

- [ ] **Step 3: Run boundary and round-trip tests**

```bash
uv run python -m pytest -q \
  tests/unit/r2/contracts/test_architecture_boundaries.py \
  tests/unit/r2/contracts/test_roundtrip.py
```

Expected: all tests pass. If a failure occurs, modify only the contract responsible for that violated frozen invariant, then rerun this exact command.

- [ ] **Step 4: Run full M1 contract suite**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/
```

Expected: all M1 contract tests pass.

- [ ] **Step 5: Run frozen registry and baseline verifiers**

```bash
uv run python scripts/r2/verify_frozen_registries.py
uv run python scripts/r2/verify_baseline.py
```

Expected:

```text
R2 frozen registry verification: PASS
R2 host baseline verification: PASS (...)
```

- [ ] **Step 6: Commit architecture regression tests**

```bash
git add tests/unit/r2/contracts r2/contracts
git commit -m "test(r2): enforce contract architecture boundaries"
```

---

### Task 9: M1 final verification and evidence

**Files:**
- Create: `docs/r2/evidence/R2_M1_VERIFICATION_<timestamp>.json`
- Create: `docs/r2/evidence/R2_M1_VERIFICATION_<timestamp>.md`
- No production code changes unless a final gate reveals a real defect.

**Interfaces:**
- Consumes M1 test suite and M0 verifiers.
- Produces the milestone evidence record.
- M2 may start only after this task passes.

- [ ] **Step 1: Verify changed-file scope before final regression**

Run:

```bash
git diff --name-only 61c8508b..HEAD
```

Expected files are limited to:

```text
docs/superpowers/specs/2026-09-06-r2-m1-contract-kernel-design.md
docs/superpowers/plans/2026-09-06-r2-m1-contract-kernel-implementation-plan.md
r2/contracts/*
tests/unit/r2/contracts/*
```

At final evidence commit, `docs/r2/evidence/R2_M1_VERIFICATION_*` will also appear.

Explicitly fail review if any of these changed:

```text
alembic/
server/
lib/
pyproject.toml
uv.lock
```

unless the user approved a scope change.

- [ ] **Step 2: Run full M1 contract tests**

```bash
uv run python -m pytest -q tests/unit/r2/contracts/
```

Expected: PASS, zero failures.

Record the exact pass count from pytest output.

- [ ] **Step 3: Run M0 R2 regression**

```bash
uv run python -m pytest -q \
  tests/unit/r2/test_bootstrap.py \
  tests/unit/scripts/r2/test_verify_frozen_registries.py \
  tests/unit/scripts/r2/test_known_blockers.py \
  tests/unit/scripts/r2/test_verify_baseline.py \
  tests/unit/scripts/r2/test_verify_postgres_baseline_script.py
```

Expected: PASS.

- [ ] **Step 4: Run frozen registry and host baseline verifiers**

```bash
uv run python scripts/r2/verify_frozen_registries.py
uv run python scripts/r2/verify_baseline.py
```

Expected both PASS.

- [ ] **Step 5: Run ArcReel focused Host regression**

Run the same R1.8/M0 focused set:

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

Expected: `349 passed` unless upstream test collection in the pinned baseline changed locally, which it must not. Any different count is a stop condition, not an automatic acceptance.

- [ ] **Step 6: Run ArcReel audit gate**

```bash
uv run python scripts/audit_tests.py --check
```

Expected: zero violations.

- [ ] **Step 7: Create M1 evidence JSON**

Create `docs/r2/evidence/R2_M1_VERIFICATION_<timestamp>.json` with the exact observed values:

```json
{
  "phase": "R2-M1",
  "milestone": "Contract Kernel",
  "status": "PASS",
  "branch": "r2/main",
  "baseline_sha": "6ddedc775e7fe5f398b10081ab741985f7dceda7",
  "checks": {
    "m1_contract_tests": "<EXACT OBSERVED COUNT> PASS",
    "m0_r2_regression": "PASS",
    "frozen_registry": "PASS",
    "host_baseline": "PASS",
    "arcreel_focused_host_tests": "349 PASS",
    "arcreel_audit_gate": "PASS",
    "provider_neutrality": "PASS",
    "content_vs_execution_fingerprint": "PASS",
    "json_roundtrip": "PASS",
    "database_migrations_added": "NONE",
    "arcreel_runtime_files_modified": "NONE",
    "known_blocker_h1": "OPEN / PRODUCTION_BLOCKER"
  },
  "next": "R2-M2 Artifact Bridge"
}
```

Replace `<EXACT OBSERVED COUNT>` with the real pytest pass count. Do not invent it.

- [ ] **Step 8: Create M1 evidence Markdown**

Create `docs/r2/evidence/R2_M1_VERIFICATION_<timestamp>.md`:

```markdown
# R2-M1 Verification

**Milestone:** Contract Kernel
**Status:** PASS
**Branch:** `r2/main`
**ArcReel baseline:** `6ddedc775e7fe5f398b10081ab741985f7dceda7`

## Verified

- M1 contract test suite: `<EXACT OBSERVED COUNT>` PASS
- M0 R2 regression: PASS
- Frozen registry verifier: PASS
- Host baseline verifier: PASS
- ArcReel focused Host regression: 349 PASS
- ArcReel audit gate: PASS
- Provider-neutral stable production contracts: PASS
- Content fingerprint vs execution fingerprint separation: PASS
- JSON round-trip: PASS
- Database migrations added: NONE
- ArcReel runtime files modified: NONE
- `R2-HOST-001`: remains OPEN / PRODUCTION_BLOCKER

## Next

R2-M2 — Artifact Bridge.
```

Again replace the count with the exact observed test count.

- [ ] **Step 9: Commit M1 evidence**

```bash
git add docs/r2/evidence
git commit -m "test(r2): record M1 contract kernel verification"
```

- [ ] **Step 10: Verify clean working tree**

```bash
git status --short
```

Expected: no output.

- [ ] **Step 11: Push reviewed M1 branch**

```bash
git push
```

Expected: current `r2/main` advances on `origin/r2/main`. Never push to `upstream`.

---

## Plan Self-Review

### Spec coverage

- Contract identity/version/schema-version: Task 1.
- Independent enum families: Task 1.
- ContentBasis: Task 2.
- Provenance: Task 2.
- SceneSpec/ShotSpec provider neutrality and ContentBasis: Task 3.
- ProductionBinding/VisualIdentity/Readiness: Task 4.
- MethodDecision/PromptPlan/ProviderRequest boundary: Task 5.
- GenerationCandidate/ApprovedMaster/QualityReport: Task 6.
- Content/execution fingerprint separation: Task 7.
- Runtime-import boundary and frozen-registry alignment: Task 8.
- JSON round-trip: Task 8.
- M0 + ArcReel regression and evidence: Task 9.
- No DB/runtime integration: enforced globally and in Task 9 scope check.

### Type consistency

Public names used by later tasks exactly match prior producing tasks:

```text
ContractIdentity
R2ContractModel
NonEmptyStr
JSONValue
ensure_json_value

ContentBasis
Provenance

SceneSpec
ShotSpec

ProductionBinding
VisualIdentityProfile
ReadinessRequirement
ProductionReadiness

MethodDecision
PromptPlan
ProviderRequest

GenerationCandidate
ApprovedMaster
QualityFinding
QualityReport

canonical_json_bytes
compute_content_fingerprint
compute_execution_fingerprint
```

### Placeholder scan

The plan contains no implementation placeholders. The only intentionally variable value is the **exact observed M1 pytest pass count** in Task 9 evidence, which must be copied from fresh test output rather than guessed.

### Scope check

M1 remains one coherent subsystem: provider-neutral domain contracts plus deterministic fingerprint semantics. Persistence and Artifact Manifest integration remain deferred to R2-M2.

---

## Execution Handoff

Recommended for this project:

**Inline execution using `superpowers:executing-plans`**, because the local repository is on the user's Ubuntu host and changes are transferred/run through deterministic packages with checkpointed terminal evidence.

Alternative:

**Subagent-driven execution** is possible, but the user's resource policy limits unnecessary subagents and this milestone is sufficiently sequential that inline execution is cleaner.

Do not start implementation until this plan has been reviewed and approved.
