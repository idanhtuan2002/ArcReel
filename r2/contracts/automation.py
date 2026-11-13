"""Immutable production-run data. Construction confers neither authority nor currentness."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from r2.contracts.common import R2ContractModel
from r2.contracts.quality import QualityProfileRevision


def _exact_identity(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or value == "*"
        or len(value.encode("utf-8")) > 255
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
    ):
        raise ValueError("identity must be exact, bounded and free of control characters")
    return value


type ExactIdentity = Annotated[str, StringConstraints(min_length=1, max_length=255), BeforeValidator(_exact_identity)]
type Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
type PositiveInt = Annotated[StrictInt, Field(ge=1, le=9_223_372_036_854_775_807)]
type NonnegativeInt = Annotated[StrictInt, Field(ge=0, le=9_223_372_036_854_775_807)]


class AutomationContract(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always", allow_inf_nan=False)


class AutomationMode(StrEnum):
    AUTO = "auto"
    SEMI = "semi"


class Checkpoint(StrEnum):
    STORY_MANUSCRIPT = "STORY_MANUSCRIPT"
    SCRIPT_PACKAGE = "SCRIPT_PACKAGE"
    FINAL_FILM = "FINAL_FILM"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_TASK = "WAITING_TASK"
    WAITING_REVIEW = "WAITING_REVIEW"
    PAUSED = "PAUSED"
    BLOCKED_CONFIGURATION = "BLOCKED_CONFIGURATION"
    BLOCKED_RESOURCE = "BLOCKED_RESOURCE"
    BLOCKED_BUDGET = "BLOCKED_BUDGET"
    BLOCKED_UNKNOWN = "BLOCKED_UNKNOWN"
    BLOCKED_INPUT_CHANGED = "BLOCKED_INPUT_CHANGED"
    FAILED_QUALITY = "FAILED_QUALITY"
    FAILED = "FAILED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    SUCCEEDED = "SUCCEEDED"


class RunStage(StrEnum):
    BRIEF = "BRIEF"
    STORY = "STORY"
    STORY_COMMIT = "STORY_COMMIT"
    HANDOFF = "HANDOFF"
    ASSET_ANALYSIS = "ASSET_ANALYSIS"
    EPISODE_PLAN = "EPISODE_PLAN"
    ADAPTATION = "ADAPTATION"
    SCRIPT_PLAN = "SCRIPT_PLAN"
    SCRIPT = "SCRIPT"
    MEDIA = "MEDIA"
    RENDER = "RENDER"
    MASTER = "MASTER"
    QUALITY = "QUALITY"
    PACKAGE = "PACKAGE"
    EXPORT = "EXPORT"


class RunScope(AutomationContract):
    user_id: ExactIdentity
    project_name: ExactIdentity
    run_id: ExactIdentity


class ModelRoute(AutomationContract):
    role: Literal["writer", "script", "reviewer_a", "reviewer_b", "image", "video", "audio", "lip_sync"]
    provider_id: ExactIdentity
    model_id: ExactIdentity
    model_identity: ExactIdentity
    config_digest: Digest
    local: StrictBool
    paid: StrictBool
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,31}$")]
    max_cost_per_call: NonnegativeInt | None


class RunPolicy(AutomationContract):
    schema_id: Literal["r2.production-policy.v1"] = "r2.production-policy.v1"
    mode: AutomationMode = AutomationMode.AUTO
    profile_id: ExactIdentity
    profile_digest: Digest
    launch_profile_id: ExactIdentity = "fiction_narration_vi_v1"
    local_only: StrictBool = False
    routes: tuple[ModelRoute, ...] = ()
    checkpoints: frozenset[Checkpoint] | None = None
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,31}$")]
    max_cost_minor_units: NonnegativeInt
    max_model_calls: PositiveInt
    max_tasks: PositiveInt
    max_runtime_seconds: PositiveInt
    max_target_episodes: PositiveInt = 1
    unit_repair_limit: Annotated[StrictInt, Field(ge=0, le=2)] = 2
    final_evaluation_limit: Annotated[StrictInt, Field(ge=1, le=3)] = 3
    route_digests: tuple[Digest, ...] = Field(min_length=1)
    #: The project's episode target in seconds when the run started (``episode_target_duration``, within the product
    #: episode interval); ``None`` when the project sets none. QUALITY compares each final's length with it.
    target_duration_seconds: Annotated[StrictInt, Field(ge=10, le=600)] | None = None
    width: PositiveInt = 576
    height: PositiveInt = 1024
    fps: PositiveInt = 24
    language: ExactIdentity = "vi"
    #: Frozen from the launch profile: ``record`` exports a rejected final with its REWORK disposition.
    quality_gate: Literal["enforce", "record"] = "enforce"
    #: Frozen from the launch profile: storyboard versions MEDIA makes for the ranking judge to choose from (ADR-0112).
    image_candidates: Annotated[StrictInt, Field(ge=1, le=3)] = 1
    #: The ranking judge's exact model identity and prompt digest when ``image_candidates`` is above 1.
    image_judge_identity: ExactIdentity | None = None
    image_judge_prompt_digest: Digest | None = None
    #: Frozen from the launch profile: the continuity judge's exact model identity and prompt digest (ADR-0134);
    #: ``None`` when storyboards are not judged for continuity.
    continuity_judge_identity: ExactIdentity | None = None
    continuity_judge_prompt_digest: Digest | None = None
    continuity_judge_max_pictures: Annotated[StrictInt, Field(ge=2, le=16)] | None = None

    @model_validator(mode="after")
    def image_selection(self) -> Self:
        pinned = (self.image_judge_identity is not None, self.image_judge_prompt_digest is not None)
        if pinned != ((self.image_candidates > 1),) * 2:
            raise ValueError("storyboard candidates need exactly one pinned ranking judge, and one storyboard none")
        if (self.continuity_judge_identity is None) != (self.continuity_judge_prompt_digest is None):
            raise ValueError("a continuity judge is pinned by both its identity and its prompt digest")
        return self

    @model_validator(mode="after")
    def checkpoint_policy(self) -> Self:
        checkpoints = self.checkpoints
        if checkpoints is None:
            checkpoints = (
                frozenset({Checkpoint.SCRIPT_PACKAGE, Checkpoint.FINAL_FILM})
                if self.mode is AutomationMode.SEMI
                else frozenset()
            )
            object.__setattr__(self, "checkpoints", checkpoints)
        if self.mode is AutomationMode.AUTO and checkpoints:
            raise ValueError("automatic mode cannot have routine Human checkpoints")
        return self


class OwnerReceipt(AutomationContract):
    owner: ExactIdentity
    receipt_ref: ExactIdentity
    digest: Digest
    task_id: ExactIdentity | None = None
    execution_id: ExactIdentity | None = None


class StepIdentity(AutomationContract):
    run_id: ExactIdentity
    stage: RunStage
    unit_key: ExactIdentity
    generation: PositiveInt
    input_digest: Digest
    policy_digest: Digest
    repair_index: NonnegativeInt
    command_id: ExactIdentity
    task_id: ExactIdentity


class DispatchIntent(AutomationContract):
    scope: RunScope
    identity: StepIdentity
    owner: ExactIdentity
    input_refs: tuple[OwnerReceipt, ...] = ()
    estimated_cost_minor_units: NonnegativeInt
    estimated_model_calls: NonnegativeInt
    estimated_tasks: NonnegativeInt
    estimated_runtime_seconds: NonnegativeInt

    @model_validator(mode="after")
    def same_run(self) -> Self:
        if self.scope.run_id != self.identity.run_id:
            raise ValueError("intent identity does not belong to run")
        return self


class TargetOutput(AutomationContract):
    target: ExactIdentity
    generation: PositiveInt
    input_digest: Digest
    policy_digest: Digest
    master_digest: Digest
    quality_run: OwnerReceipt
    quality_decision: Literal["PASS", "REWORK"]
    export: OwnerReceipt
    final_digest: Digest
    archive_digest: Digest
    archive_size: PositiveInt
    verified: Literal[True]


class StageOutcome(AutomationContract):
    stage: RunStage
    generation: PositiveInt
    input_digest: Digest
    policy_digest: Digest
    kind: Literal["WAIT", "BLOCK", "REWORK", "PASS"]
    receipts: tuple[OwnerReceipt, ...] = ()
    owner_state: ExactIdentity | None = None
    reason: ExactIdentity | None = None
    unit_key: ExactIdentity | None = None
    repair_stage: RunStage | None = None
    outputs: tuple[TargetOutput, ...] = ()

    @model_validator(mode="after")
    def complete_outcome(self) -> Self:
        if self.kind == "REWORK" and (self.unit_key is None or self.repair_stage is None):
            raise ValueError("rework requires exact unit and stage")
        if self.kind == "BLOCK" and self.reason is None:
            raise ValueError("blocked outcome requires reason")
        return self


class RepairCount(AutomationContract):
    stage: RunStage
    unit_key: ExactIdentity
    count: PositiveInt


class PendingReview(AutomationContract):
    checkpoint: Checkpoint
    binding_digest: Digest


class ReviewApproval(AutomationContract):
    checkpoint: Checkpoint
    binding_digest: Digest
    actor_id: ExactIdentity
    receipt: OwnerReceipt


class RunSnapshot(RunScope):
    schema_id: Literal["r2.production-run.v1"] = "r2.production-run.v1"
    policy: RunPolicy
    input_digest: Digest
    status: RunStatus = RunStatus.PENDING
    stage: RunStage = RunStage.BRIEF
    generation: PositiveInt = 1
    version: PositiveInt = 1
    fencing_epoch: NonnegativeInt = 0
    targets: tuple[ExactIdentity, ...] = ()
    completed_targets: tuple[TargetOutput, ...] = ()
    repair_counts: tuple[RepairCount, ...] = ()
    final_evaluations: NonnegativeInt = 0
    final_evaluation_receipts: tuple[Digest, ...] = ()
    pending_review: PendingReview | None = None
    review_approvals: tuple[ReviewApproval, ...] = ()
    reason: ExactIdentity | None = None
    created_at: AwareDatetime
    #: The last stage; a story-only run (ADR-0124) succeeds at ``HANDOFF`` without film outputs.
    end_stage: RunStage = Field(default=RunStage.EXPORT, exclude_if=lambda value: value is RunStage.EXPORT)

    @model_validator(mode="after")
    def coherent_run(self) -> Self:
        if self.end_stage not in {RunStage.HANDOFF, RunStage.EXPORT}:
            raise ValueError("a run ends at the handoff or the export")
        if len(set(self.targets)) != len(self.targets) or len(self.targets) > self.policy.max_target_episodes:
            raise ValueError("duplicate or out-of-scope targets")
        outputs = [output.target for output in self.completed_targets]
        if len(set(outputs)) != len(outputs) or not set(outputs) <= set(self.targets):
            raise ValueError("invalid completed target scope")
        repairs = [(r.stage, r.unit_key) for r in self.repair_counts]
        if len(set(repairs)) != len(repairs):
            raise ValueError("duplicate repair counters")
        if len(set(self.final_evaluation_receipts)) != len(self.final_evaluation_receipts):
            raise ValueError("duplicate final evaluation receipts")
        if self.final_evaluations > self.policy.final_evaluation_limit:
            raise ValueError("final evaluation budget exceeded")
        if self.status is RunStatus.WAITING_REVIEW and self.pending_review is None:
            raise ValueError("review wait requires exact binding")
        if self.status is RunStatus.SUCCEEDED and self.end_stage is RunStage.HANDOFF:
            if self.stage is not RunStage.HANDOFF:
                raise ValueError("a story-only run succeeds at the handoff")
        elif self.status is RunStatus.SUCCEEDED and (
            not self.targets
            or set(outputs) != set(self.targets)
            or any(
                o.generation > self.generation or o.input_digest != self.input_digest for o in self.completed_targets
            )
        ):
            raise ValueError("success requires every verified current target")
        return self


class RunCommand(AutomationContract):
    """Internal command; the API derives user identity before constructing it."""

    user_id: ExactIdentity
    project_name: ExactIdentity
    command_id: ExactIdentity
    action: Literal["START", "PAUSE", "RESUME", "CANCEL", "MODE"]
    expected_version: NonnegativeInt
    expected_input_digest: Digest
    policy_digest: Digest
    mode: AutomationMode = AutomationMode.AUTO
    run_id: ExactIdentity | None = None
    idea: Annotated[str, StringConstraints(min_length=1, max_length=4000)] | None = None
    targets: tuple[ExactIdentity, ...] = ("episode:1",)
    #: ``idea`` writes a new story first; ``project`` films the story already in the project's sources (ADR-0115).
    #: Left out of the stored command at its default, so earlier commands keep their digests.
    #: ``continue`` writes the next part of the project's story; ``variant`` writes, into this project, another
    #: version of ``source_project``'s story (an instruction in ``idea``, a ``variant_profile``, or both).
    story_source: Literal["idea", "project", "continue", "variant"] = Field(
        default="idea", exclude_if=lambda value: value == "idea"
    )
    source_project: ExactIdentity | None = Field(default=None, exclude_if=lambda value: value is None)
    variant_profile: ExactIdentity | None = Field(default=None, exclude_if=lambda value: value is None)
    #: ADR-0116: a run from an idea may start a book of this many chapters (it writes part 1); a ``continue`` run
    #: of a book project writes the book's next part on its own.
    book_chapters: Annotated[int, Field(ge=6, le=120)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    #: ADR-0124: ``HANDOFF`` ends a run once its story is committed and handed off (a story project's autopilot).
    end_stage: Literal["HANDOFF", "EXPORT"] = Field(default="EXPORT", exclude_if=lambda value: value == "EXPORT")
    #: ADR-0125: ``auto`` starts a story with no idea; BRIEF draws the idea and its settings on the writer route.
    idea_mode: Literal["given", "auto"] = Field(default="given", exclude_if=lambda value: value == "given")

    @model_validator(mode="after")
    def command_shape(self) -> Self:
        if self.action == "START":
            if self.run_id is not None or self.expected_version != 0:
                raise ValueError("start requires the genesis version")
            variant = self.story_source == "variant"
            if self.story_source == "project" and self.idea is not None:
                raise ValueError("a run of the project's story takes no idea")
            if self.idea_mode == "auto" and (self.story_source != "idea" or self.idea is not None):
                raise ValueError("a drawn idea starts a new story and replaces the given idea")
            if self.story_source in {"idea", "continue"} and self.idea is None and self.idea_mode == "given":
                raise ValueError("start requires an idea")
            if variant and self.idea is None and self.variant_profile is None:
                raise ValueError("a variant requires an instruction (idea) or a profile")
            if variant != (self.source_project is not None) or (not variant and self.variant_profile is not None):
                raise ValueError("only a variant names its source project and profile")
            if self.source_project == self.project_name:
                raise ValueError("a variant is written into another project than its source")
            if self.book_chapters is not None and self.story_source != "idea":
                raise ValueError("only a run from an idea starts a book")
            if self.end_stage == "HANDOFF" and self.story_source == "project":
                raise ValueError("a run that ends at the handoff writes a story")
        elif (
            self.run_id is None
            or self.expected_version < 1
            or self.idea is not None
            or self.story_source != "idea"
            or self.source_project is not None
            or self.variant_profile is not None
            or self.book_chapters is not None
            or self.end_stage != "EXPORT"
            or self.idea_mode != "given"
        ):
            raise ValueError("control requires an exact existing run")
        if not self.targets or len(set(self.targets)) != len(self.targets):
            raise ValueError("target selection must be nonempty and unique")
        return self


class ReviewCommand(AutomationContract):
    """Internal Human checkpoint decision; the API derives user identity before constructing it."""

    user_id: ExactIdentity
    project_name: ExactIdentity
    run_id: ExactIdentity
    command_id: ExactIdentity
    expected_version: PositiveInt
    checkpoint: Checkpoint
    binding_digest: Digest
    #: REWORK (FINAL_FILM only) sends the final back to MEDIA as a new generation instead of ending the run.
    decision: Literal["APPROVE", "REJECT", "REWORK"]


class BudgetReservation(AutomationContract):
    """Run allocation, independent of the host's provider charge ledger."""

    scope: RunScope
    reservation_id: ExactIdentity
    command_id: ExactIdentity
    policy_digest: Digest
    currency: ExactIdentity
    cost_minor_units: NonnegativeInt
    model_calls: NonnegativeInt
    tasks: NonnegativeInt
    runtime_seconds: NonnegativeInt
    state: Literal["RESERVED", "UNKNOWN", "SETTLED"]


class UsageReceipt(OwnerReceipt):
    reservation_id: ExactIdentity
    currency: ExactIdentity
    cost_minor_units: NonnegativeInt
    model_calls: NonnegativeInt
    tasks: NonnegativeInt
    runtime_seconds: NonnegativeInt
    outcome: Literal["KNOWN", "UNKNOWN"]


class AutomationOperation(StrEnum):
    BRIEF = "BRIEF"
    STORY = "STORY"
    STORY_COMMIT = "STORY_COMMIT"
    HANDOFF = "HANDOFF"
    ASSET_ANALYSIS = "ASSET_ANALYSIS"
    EPISODE_PLAN = "EPISODE_PLAN"
    ADAPTATION = "ADAPTATION"
    SCRIPT_PLAN = "SCRIPT_PLAN"
    SCRIPT = "SCRIPT"
    MEDIA = "MEDIA"
    RENDER = "RENDER"
    MASTER = "MASTER"
    QUALITY = "QUALITY"
    PACKAGE = "PACKAGE"
    EXPORT = "EXPORT"


class GrantRequest(RunScope):
    issuer_id: ExactIdentity
    command_id: ExactIdentity
    expected_run_version: PositiveInt
    input_digest: Digest
    policy_digest: Digest
    operations: frozenset[AutomationOperation] = Field(min_length=1)
    expires_at: AwareDatetime


class AutomationGrant(RunScope):
    schema_id: Literal["r2.automation-grant.v1"] = "r2.automation-grant.v1"
    grant_id: ExactIdentity
    version: PositiveInt
    state: Literal["ACTIVE", "REVOKED"]
    principal: ExactIdentity
    issuer_id: ExactIdentity
    start_command_id: ExactIdentity
    request_digest: Digest
    parent_sequence: PositiveInt
    parent_event_digest: Digest
    policy_digest: Digest
    input_digest: Digest
    operations: frozenset[AutomationOperation] = Field(min_length=1)
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("delegation window is empty")
        return self


class AuthorizationSubject(RunScope):
    grant_id: ExactIdentity
    grant_version: PositiveInt
    expected_run_version: PositiveInt
    generation: PositiveInt
    input_digest: Digest
    policy_digest: Digest
    operation: AutomationOperation
    command_id: ExactIdentity
    subject_digest: Digest


class AutomationAuthorizationV1(AutomationContract):
    schema_id: Literal["r2.automation-authorization.v1"] = "r2.automation-authorization.v1"
    actor_kind: Literal["RUN_AUTOMATION"] = "RUN_AUTOMATION"
    principal: ExactIdentity
    subject: AuthorizationSubject
    request_digest: Digest
    parent_sequence: PositiveInt
    parent_event_digest: Digest
    admitted_at: AwareDatetime


class QualificationCase(AutomationContract):
    split: Literal["CALIBRATION", "HOLDOUT"]
    label: Literal["CLEAN", "CRITICAL_DEFECT"]
    accepted: StrictBool
    case_digest: Digest
    receipt_ref: ExactIdentity
    receipt_digest: Digest


class ReviewerQualification(AutomationContract):
    profile_digest: Digest
    launch_profile_id: ExactIdentity
    language: ExactIdentity
    provider_id: ExactIdentity
    model_id: ExactIdentity
    model_identity: ExactIdentity
    config_digest: Digest
    prompt_digest: Digest
    cases: Annotated[tuple[QualificationCase, ...], Field(max_length=1000)]


class LaunchQualification(OwnerReceipt):
    user_id: ExactIdentity
    project_name: ExactIdentity
    launch_profile_id: ExactIdentity
    profile_digest: Digest
    route_digests: tuple[Digest, ...]
    required_disk_bytes: PositiveInt
    required_gpu_bytes: PositiveInt


class PreflightSnapshot(AutomationContract):
    user_id: ExactIdentity
    project_name: ExactIdentity
    input_digest: Digest
    content_mode: ExactIdentity
    generation_mode: ExactIdentity
    language: ExactIdentity
    routes: tuple[ModelRoute, ...]
    profile: QualityProfileRevision | None
    qualifications: tuple[ReviewerQualification, ...]
    launch_qualification: LaunchQualification | None = None
    #: Route digests of image, video and audio routes whose host media probe passed (``media_probe``).
    media_route_probes: frozenset[Digest] = frozenset()
    voice_available: StrictBool
    disk_free_bytes: NonnegativeInt
    required_disk_bytes: NonnegativeInt
    gpu_free_bytes: NonnegativeInt
    required_gpu_bytes: NonnegativeInt
    checked_at: AwareDatetime


class PreflightReport(AutomationContract):
    user_id: ExactIdentity
    project_name: ExactIdentity
    input_digest: Digest
    policy_digest: Digest
    route_digests: tuple[Digest, ...]
    dispatch_allowed: StrictBool
    blocking_reasons: tuple[ExactIdentity, ...]
    checked_at: AwareDatetime

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.dispatch_allowed != (not self.blocking_reasons):
            raise ValueError("preflight outcome differs from blockers")
        return self
