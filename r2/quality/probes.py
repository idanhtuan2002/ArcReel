"""Immutable deterministic probe measurements; these values grant no quality disposition."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from fractions import Fraction
from math import gcd
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical
from r2.contracts.advanced_creative import Sha256Digest
from r2.contracts.quality import ExactIdentity, M10ContractModel
from r2.quality.digests import verify_caches
from r2.quality.errors import (
    M10Error,
    OperationalEnvelopeExceededError,
    ProbeFailedError,
    ReferenceInvalidError,
    RequiredEvidenceMissingError,
)
from r2.quality.ports import ProbeRequest


class MediaTime(M10ContractModel):
    numerator: StrictInt = Field(ge=-(2**63) + 1, le=2**63 - 1)
    denominator: StrictInt = Field(gt=0, le=2**31 - 1)

    @model_validator(mode="before")
    @classmethod
    def reduced(cls, value: object) -> object:
        body = dict(value) if isinstance(value, cls) else value
        if isinstance(body, dict):
            numerator, denominator = body.get("numerator"), body.get("denominator")
            if type(numerator) is int and type(denominator) is int and denominator > 0:
                common = gcd(numerator, denominator)
                return body | {"numerator": numerator // common, "denominator": denominator // common}
        return body

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


class Interval(M10ContractModel):
    kind: Literal["BLACK", "FREEZE", "SILENCE"]
    start: MediaTime
    end: MediaTime
    ended_at_eof: StrictBool

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not 0 <= self.start.as_fraction() <= self.end.as_fraction():
            raise ValueError("invalid interval bounds")
        return self


class IntervalFacts(M10ContractModel):
    kind: Literal["INTERVALS"] = "INTERVALS"
    measured_duration: MediaTime
    intervals: tuple[Interval, ...] = Field(max_length=10_000)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        duration = self.measured_duration.as_fraction()
        if duration < 0:
            raise ValueError("invalid measured duration")
        keys = tuple((item.start.as_fraction(), item.end.as_fraction(), item.kind) for item in self.intervals)
        if len(set(keys)) != len(keys) or keys != tuple(sorted(keys)):
            raise ValueError("intervals require unique canonical order")
        for item in self.intervals:
            if item.end.as_fraction() > duration or (item.ended_at_eof and item.end.as_fraction() != duration):
                raise ValueError("interval exceeds measured duration or EOF binding")
        return self


def canonical_decimal(value: object) -> str:
    """Normalize bounded decimal strings without float conversion or silent rounding."""
    if (
        not isinstance(value, str)
        or len(value) > 128
        or re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value) is None
    ):
        raise ValueError("invalid measured decimal")
    try:
        exact = Decimal(value)
        exponent = exact.as_tuple().exponent
        if not exact.is_finite() or not isinstance(exponent, int) or not -24 <= exponent <= 24:
            raise ValueError("invalid measured decimal")
        with localcontext(Context(prec=24, rounding=ROUND_HALF_EVEN, Emin=-99, Emax=99)):
            normalized = +exact
        if normalized != exact:
            raise ValueError("measured decimal exceeds precision")
    except InvalidOperation:
        raise ValueError("invalid measured decimal") from None
    if normalized.is_zero():
        return "0"
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


class LoudnessFacts(M10ContractModel):
    kind: Literal["LOUDNESS"] = "LOUDNESS"
    state: Literal["FINITE", "SILENT", "UNMEASURABLE"]
    integrated_lufs: StrictStr | None
    true_peak_dbfs: StrictStr | None

    @field_validator("integrated_lufs", "true_peak_dbfs", mode="before")
    @classmethod
    def numeric_strings(cls, value: object) -> str | None:
        return None if value is None else canonical_decimal(value)

    @model_validator(mode="after")
    def explicit_state(self) -> Self:
        present = (self.integrated_lufs is not None, self.true_peak_dbfs is not None)
        expected = (True, True) if self.state == "FINITE" else (False, False)
        if present != expected:
            raise ValueError("loudness state and numeric measurements disagree")
        return self


class StreamFacts(M10ContractModel):
    index: StrictInt = Field(ge=0)
    kind: Literal["VIDEO", "AUDIO"]
    codec: Literal["h264", "aac"]
    width: StrictInt | None = Field(default=None, gt=0, le=32768)
    height: StrictInt | None = Field(default=None, gt=0, le=32768)
    pixel_format: Literal["yuv420p"] | None = None
    sample_rate: StrictInt | None = Field(default=None, gt=0, le=384000)
    channels: StrictInt | None = Field(default=None, gt=0, le=32)
    frame_rate: MediaTime | None = None
    time_base: MediaTime
    duration: MediaTime | Literal["UNKNOWN"]

    @model_validator(mode="after")
    def consistent_stream(self) -> Self:
        if self.time_base.as_fraction() <= 0 or (
            isinstance(self.duration, MediaTime) and self.duration.as_fraction() < 0
        ):
            raise ValueError("invalid stream timing")
        if self.kind == "VIDEO":
            if (
                self.codec != "h264"
                or self.width is None
                or self.height is None
                or self.pixel_format is None
                or self.sample_rate is not None
                or self.channels is not None
                or self.frame_rate is None
                or self.frame_rate.as_fraction() <= 0
            ):
                raise ValueError("invalid video stream facts")
        elif (
            self.codec != "aac"
            or self.sample_rate is None
            or self.channels is None
            or self.width is not None
            or self.height is not None
            or self.pixel_format is not None
            or self.frame_rate is not None
        ):
            raise ValueError("invalid audio stream facts")
        return self


class ContainerFacts(M10ContractModel):
    kind: Literal["CONTAINER_STREAM"] = "CONTAINER_STREAM"
    format: Literal["MP4"]
    duration: MediaTime
    streams: tuple[StreamFacts, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def canonical_streams(self) -> Self:
        indices = tuple(item.index for item in self.streams)
        if self.duration.as_fraction() < 0 or indices != tuple(sorted(set(indices))):
            raise ValueError("invalid container duration or stream identities")
        return self


class DecodeFacts(M10ContractModel):
    kind: Literal["DECODE"] = "DECODE"
    stream_indices: tuple[StrictInt, ...] = Field(min_length=1, max_length=16)
    complete: StrictBool

    @model_validator(mode="after")
    def canonical_indices(self) -> Self:
        if any(index < 0 for index in self.stream_indices) or self.stream_indices != tuple(
            sorted(set(self.stream_indices))
        ):
            raise ValueError("decoded stream identities require unique canonical order")
        return self


class CaptionCue(M10ContractModel):
    start: MediaTime
    end: MediaTime

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if not 0 <= self.start.as_fraction() < self.end.as_fraction():
            raise ValueError("invalid caption interval")
        return self


class CaptionFacts(M10ContractModel):
    kind: Literal["CAPTIONS"] = "CAPTIONS"
    format: Literal["SRT", "WEBVTT"]
    measured_duration: MediaTime
    cue_count: StrictInt = Field(ge=0, le=10000)
    cue_times: tuple[CaptionCue, ...] = Field(max_length=10000)
    union_coverage: MediaTime
    overlap_count: StrictInt = Field(ge=0, le=10000)

    @model_validator(mode="after")
    def actual_coverage(self) -> Self:
        duration = self.measured_duration.as_fraction()
        times = tuple((cue.start.as_fraction(), cue.end.as_fraction()) for cue in self.cue_times)
        if duration < 0 or len(times) != self.cue_count or times != tuple(sorted(times)):
            raise ValueError("invalid caption count or order")
        covered = Fraction(0)
        right = Fraction(0)
        overlaps = 0
        for start, end in times:
            if end > duration:
                raise ValueError("caption exceeds measured duration")
            overlaps += int(start < right)
            covered += max(Fraction(0), end - max(start, right))
            right = max(right, end)
        if self.union_coverage.as_fraction() != covered or self.overlap_count != overlaps:
            raise ValueError("caption summary differs from timing evidence")
        return self


class VmafFrame(M10ContractModel):
    index: StrictInt = Field(ge=0, le=4)
    score: StrictStr

    @field_validator("score", mode="before")
    @classmethod
    def canonical_score(cls, value: object) -> str:
        score = canonical_decimal(value)
        if not 0 <= Decimal(score) <= 100:
            raise ValueError("VMAF score outside range")
        return score


class VmafFacts(M10ContractModel):
    kind: Literal["REFERENCE_VMAF"] = "REFERENCE_VMAF"
    span: Literal["FIRST_5_FRAMES"]
    width: StrictInt = Field(gt=0, le=2073600)
    height: StrictInt = Field(gt=0, le=2073600)
    frame_rate: MediaTime
    model_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    frames: tuple[VmafFrame, ...] = Field(min_length=5, max_length=5)
    mean: StrictStr

    @field_validator("mean", mode="before")
    @classmethod
    def canonical_mean(cls, value: object) -> str:
        return VmafFrame.canonical_score(value)

    @model_validator(mode="after")
    def comparable_span(self) -> Self:
        if (
            self.width % 2
            or self.height % 2
            or self.width * self.height > 2073600
            or not 1 <= self.frame_rate.as_fraction() <= 60
            or tuple(frame.index for frame in self.frames) != (0, 1, 2, 3, 4)
        ):
            raise ValueError("invalid VMAF geometry, timing or frame indices")
        with localcontext(Context(prec=24, rounding=ROUND_HALF_EVEN, Emin=-99, Emax=99)):
            expected = sum((Decimal(frame.score) for frame in self.frames), Decimal(0)) / 5
            if abs(Decimal(self.mean) - expected) > Decimal("0.000001"):
                raise ValueError("VMAF mean differs from frame evidence")
        return self


type ProbeRecipe = Literal["CONTAINER_STREAM", "DECODE", "INTERVALS", "LOUDNESS", "CAPTIONS", "REFERENCE_VMAF"]


class ProbeFinding(M10ContractModel):
    rule_id: ExactIdentity
    severity: Literal["BLOCKING", "ADVISORY"]
    subject_locator: StrictStr = Field(
        pattern=r"^(?:media|reference|captions|stream:[0-9]+|interval:[0-9]+|frame:[0-4]|cue:[0-9]+)$"
    )
    evidence_digest: Sha256Digest


class ProbeMeasurement(M10ContractModel):
    schema_id: Literal["m10.probe-measurement.v1"]
    recipe: ProbeRecipe
    input_digests: tuple[Sha256Digest, ...] = Field(min_length=1, max_length=3)
    tool_identity_digest: Sha256Digest
    config_digest: Sha256Digest
    parser_version: Literal["host-quality-parser-v1"]
    facts: Annotated[
        ContainerFacts | DecodeFacts | IntervalFacts | LoudnessFacts | CaptionFacts | VmafFacts,
        Field(discriminator="kind"),
    ]
    status: Literal["PASS", "FAIL", "INAPPLICABLE", "INDETERMINATE"]
    findings: tuple[ProbeFinding, ...] = Field(max_length=10000)

    @model_validator(mode="after")
    def meaningful_evidence(self) -> Self:
        if self.recipe != self.facts.kind:
            raise ValueError("measurement recipe differs from facts")
        if self.status == "PASS" and (
            (isinstance(self.facts, DecodeFacts) and not self.facts.complete)
            or (isinstance(self.facts, LoudnessFacts) and self.facts.state != "FINITE")
        ):
            raise ValueError("incomplete or absent numeric evidence cannot pass")
        keys = tuple((f.rule_id, f.subject_locator, f.severity, f.evidence_digest) for f in self.findings)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("findings require unique canonical order")
        if self.status == "PASS" and any(f.severity == "BLOCKING" for f in self.findings):
            raise ValueError("blocking findings cannot pass")
        return self


class ResourceEvidence(M10ContractModel):
    schema_id: Literal["m10.probe-resources.v1"]
    memory_max_bytes: StrictInt = Field(gt=0, le=536870912)
    swap_max_bytes: StrictInt = Field(ge=0, le=0)
    tasks_max: StrictInt = Field(gt=0, le=32)
    cpu_quota_us: StrictInt = Field(gt=0)
    cpu_period_us: StrictInt = Field(gt=0)
    wall_elapsed_ms: StrictInt = Field(ge=0)
    peak_memory_bytes: StrictInt | None = Field(ge=0)
    peak_tasks: StrictInt | None = Field(ge=0)
    stdout_bytes: StrictInt = Field(ge=0)
    stderr_bytes: StrictInt = Field(ge=0)
    scratch_sizes: tuple[StrictInt, StrictInt, StrictInt]
    exit_code: StrictInt
    manager_result: Literal["SUCCESS", "EXIT_CODE", "TIMEOUT", "OOM_KILL", "SIGNAL", "STARTUP_FAILED"]
    oom_killed: StrictBool
    deadline_exceeded: StrictBool
    output_exceeded: StrictBool
    group_cleanup_verified: StrictBool
    kernel_identity_digest: Sha256Digest
    control_identity_digest: Sha256Digest
    tool_identity_digest: Sha256Digest

    @model_validator(mode="after")
    def effective_envelope(self) -> Self:
        if self.cpu_quota_us > self.cpu_period_us or any(size < 0 or size > 67108864 for size in self.scratch_sizes):
            raise ValueError("resource evidence exceeds admitted envelope")
        return self


class ProbeExecutionResult(M10ContractModel):
    schema_id: Literal["m10.probe-execution-result.v1"]
    request_digest: Sha256Digest
    execution_id: ExactIdentity
    measurement: ProbeMeasurement
    resources: ResourceEvidence
    started_at: AwareDatetime
    finished_at: AwareDatetime

    @field_validator("started_at", "finished_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def successful_execution(self) -> Self:
        resources = self.resources
        if (
            self.finished_at < self.started_at
            or resources.exit_code != 0
            or resources.manager_result != "SUCCESS"
            or resources.oom_killed
            or resources.deadline_exceeded
            or resources.output_exceeded
            or not resources.group_cleanup_verified
            or resources.wall_elapsed_ms > 120000
            or resources.stdout_bytes + resources.stderr_bytes > 1048576
            or resources.tool_identity_digest != self.measurement.tool_identity_digest
        ):
            raise ValueError("execution is not a complete bounded success")
        if len(canonical_json_bytes(self)) > 1048576:
            raise ValueError("execution result exceeds byte ceiling")
        return self


def measurement_digest(measurement: ProbeMeasurement) -> str:
    normalized = ProbeMeasurement.model_validate(measurement)
    if len(canonical_json_bytes(normalized)) > 1048576:
        raise ValueError("measurement exceeds byte ceiling")
    return digest_canonical({"domain": "m10.probe-measurement.v1", "contract_version": "1", "body": normalized})


def execution_result_digest(result: ProbeExecutionResult) -> str:
    normalized = ProbeExecutionResult.model_validate(result)
    return digest_canonical({"domain": "m10.probe-execution-result.v1", "contract_version": "1", "body": normalized})


class ToolIdentity(M10ContractModel):
    name: Literal["ffmpeg", "ffprobe", "vmaf"]
    version: StrictStr = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=64)
    executable_digest: Sha256Digest
    build_digest: Sha256Digest
    model_digest: Sha256Digest | None

    @model_validator(mode="after")
    def model_binding(self) -> Self:
        if (self.name == "vmaf") != (self.model_digest is not None):
            raise ValueError("only VMAF requires a model binding")
        return self


class ProbeParameters(M10ContractModel):
    require_video: StrictBool = True
    require_audio: StrictBool = False
    interval_kinds: tuple[Literal["BLACK", "FREEZE", "SILENCE"], ...] = ("BLACK", "FREEZE", "SILENCE")
    black_picture_ratio: StrictStr = "0.98"
    black_pixel_threshold: StrictStr = "0.1"
    black_min_duration_ms: StrictInt = Field(default=2000, gt=0, le=120000)
    freeze_noise_db: StrictStr = "-60"
    freeze_min_duration_ms: StrictInt = Field(default=2000, gt=0, le=120000)
    silence_noise_db: StrictStr = "-50"
    silence_min_duration_ms: StrictInt = Field(default=2000, gt=0, le=120000)
    caption_format: Literal["SRT", "WEBVTT"] = "SRT"
    frame_count: StrictInt = Field(default=5, ge=5, le=5)

    @field_validator(
        "black_picture_ratio", "black_pixel_threshold", "freeze_noise_db", "silence_noise_db", mode="before"
    )
    @classmethod
    def finite_parameters(cls, value: object) -> str:
        return canonical_decimal(value)

    @model_validator(mode="after")
    def bounded_parameters(self) -> Self:
        if not self.require_video and not self.require_audio:
            raise ValueError("a probe requires a declared media stream")
        if not self.interval_kinds or self.interval_kinds != tuple(sorted(set(self.interval_kinds))):
            raise ValueError("detectors require unique canonical order")
        if any(not 0 <= Decimal(value) <= 1 for value in (self.black_picture_ratio, self.black_pixel_threshold)):
            raise ValueError("black detector threshold outside range")
        if any(not -120 <= Decimal(value) <= 0 for value in (self.freeze_noise_db, self.silence_noise_db)):
            raise ValueError("audio or freeze threshold outside range")
        return self


class ApplicabilityPolicy(M10ContractModel):
    schema_id: Literal["m10.probe-applicability.v1"]
    policy_id: ExactIdentity
    revision: StrictInt = Field(ge=1)
    mode: Literal["REQUIRED", "SILENT_AUDIO_INAPPLICABLE"]


class ThresholdPolicy(M10ContractModel):
    schema_id: Literal["m10.probe-threshold.v1"]
    policy_id: ExactIdentity
    revision: StrictInt = Field(ge=1)
    metric: Literal["EVIDENCE_COMPLETE", "MAX_INTERVAL_MS", "INTEGRATED_LUFS", "CAPTION_COVERAGE_RATIO", "VMAF_MEAN"]
    minimum: StrictStr | None
    maximum: StrictStr | None

    @field_validator("minimum", "maximum", mode="before")
    @classmethod
    def numeric_bounds(cls, value: object) -> str | None:
        return None if value is None else canonical_decimal(value)

    @model_validator(mode="after")
    def meaningful_bounds(self) -> Self:
        low = None if self.minimum is None else Decimal(self.minimum)
        high = None if self.maximum is None else Decimal(self.maximum)
        if self.metric == "EVIDENCE_COMPLETE":
            valid = low is None and high is None
        elif self.metric == "MAX_INTERVAL_MS":
            valid = low is None and high is not None and 0 <= high <= 120000
        elif self.metric == "INTEGRATED_LUFS":
            valid = low is not None and high is not None and -120 <= low <= high <= 20
        else:
            ceiling = 1 if self.metric == "CAPTION_COVERAGE_RATIO" else 100
            valid = low is not None and 0 <= low <= ceiling and (high is None or low <= high <= ceiling)
        if not valid:
            raise ValueError("invalid threshold policy bounds")
        return self


class ReferenceEligibilityPolicy(M10ContractModel):
    schema_id: Literal["m10.probe-reference-eligibility.v1"]
    policy_id: ExactIdentity
    revision: StrictInt = Field(ge=1)
    reference_name: StrictStr = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    mode: Literal["SAME_CONTENT_ZERO_OFFSET_EQUAL_GEOMETRY"]
    model_digest: Sha256Digest


class ProbeConfig(M10ContractModel):
    schema_id: Literal["m10.probe-config.v1"]
    config_id: ExactIdentity
    revision: StrictInt = Field(ge=1)
    rule_id: ExactIdentity
    recipe: ProbeRecipe
    tools: tuple[ToolIdentity, ...] = Field(min_length=1, max_length=3)
    parser_version: Literal["host-quality-parser-v1"]
    parser_digest: Sha256Digest
    parameters: ProbeParameters
    applicability_policy: ApplicabilityPolicy
    threshold_policy: ThresholdPolicy
    reference_policy: ReferenceEligibilityPolicy | None
    max_runtime_ms: StrictInt = Field(gt=0, le=120000)
    max_output_bytes: StrictInt = Field(gt=0, le=1048576)

    @model_validator(mode="after")
    def qualified_recipe_shape(self) -> Self:
        names = tuple(tool.name for tool in self.tools)
        required = ("ffprobe",) if self.recipe in {"CONTAINER_STREAM", "CAPTIONS"} else ("ffmpeg", "ffprobe")
        if self.recipe == "REFERENCE_VMAF":
            required = ("ffmpeg", "ffprobe", "vmaf")
        if names != required:
            raise ValueError("probe tool set is incomplete or unordered")
        metrics = {
            "CONTAINER_STREAM": "EVIDENCE_COMPLETE",
            "DECODE": "EVIDENCE_COMPLETE",
            "INTERVALS": "MAX_INTERVAL_MS",
            "LOUDNESS": "INTEGRATED_LUFS",
            "CAPTIONS": "CAPTION_COVERAGE_RATIO",
            "REFERENCE_VMAF": "VMAF_MEAN",
        }
        if self.threshold_policy.metric != metrics[self.recipe]:
            raise ValueError("threshold policy does not match recipe")
        if self.recipe == "REFERENCE_VMAF":
            reference = self.reference_policy
            if reference is None or self.tools[-1].model_digest != reference.model_digest:
                raise ValueError("VMAF requires an exact reference/model policy")
        elif self.reference_policy is not None:
            raise ValueError("non-reference recipe cannot consume reference policy")
        if self.applicability_policy.mode != "REQUIRED" and self.recipe != "LOUDNESS":
            raise ValueError("silent applicability applies only to measured loudness")
        if (
            self.recipe == "LOUDNESS" or (self.recipe == "INTERVALS" and "SILENCE" in self.parameters.interval_kinds)
        ) and not self.parameters.require_audio:
            raise ValueError("audio detector requires an explicit audio stream")
        if len(canonical_json_bytes(self)) > 1048576:
            raise ValueError("configuration exceeds byte ceiling")
        return self

    def primary_tool(self) -> ToolIdentity:
        name = (
            "vmaf"
            if self.recipe == "REFERENCE_VMAF"
            else "ffprobe"
            if self.recipe in {"CONTAINER_STREAM", "CAPTIONS"}
            else "ffmpeg"
        )
        return next(tool for tool in self.tools if tool.name == name)


def _private_digest(domain: str, body: object) -> str:
    return digest_canonical({"domain": domain, "contract_version": "1", "body": body})


def facts_digest(facts: ContainerFacts | DecodeFacts | IntervalFacts | LoudnessFacts | CaptionFacts | VmafFacts) -> str:
    return _private_digest("m10.probe-facts.v1", type(facts).model_validate(facts))


def probe_request_digest(request: ProbeRequest) -> str:
    validate_probe_envelope(request)
    return _private_digest("m10.probe-request.v1", ProbeRequest.model_validate(request))


def config_digest(config: ProbeConfig) -> str:
    return _private_digest("m10.probe-config.v1", ProbeConfig.model_validate(config))


def policy_digest(policy: ApplicabilityPolicy | ThresholdPolicy | ReferenceEligibilityPolicy) -> str:
    normalized = type(policy).model_validate(policy)
    return _private_digest(normalized.schema_id, normalized)


def tool_identity_digest(config: ProbeConfig) -> str:
    normalized = ProbeConfig.model_validate(config)
    return _private_digest(
        "m10.probe-tool-identity.v1",
        {
            "tools": normalized.tools,
            "parser_version": normalized.parser_version,
            "parser_digest": normalized.parser_digest,
        },
    )


class ProbeInputBinding(M10ContractModel):
    """Host-owned scoped locator beneath a project root; public requests never supply paths."""

    schema_id: Literal["m10.probe-input-binding.v1"]
    user_id: ExactIdentity
    project_name: ExactIdentity
    role: Literal["CAPTION", "REFERENCE"]
    name: StrictStr = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    relative_path: StrictStr = Field(
        max_length=255, pattern=r"^[A-Za-z0-9_][A-Za-z0-9._-]*(/[A-Za-z0-9_][A-Za-z0-9._-]*)*$"
    )
    content_digest: Sha256Digest


class ProbeCatalog(M10ContractModel):
    schema_id: Literal["m10.probe-catalog.v1"]
    configs: tuple[ProbeConfig, ...] = Field(max_length=256)
    bindings: tuple[ProbeInputBinding, ...] = Field(default=(), max_length=1024)

    @model_validator(mode="after")
    def immutable_entries(self) -> Self:
        keys = tuple((entry.config_id, entry.revision) for entry in self.configs)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("catalog requires unique canonical config revisions")
        named = [(entry.user_id, entry.project_name, entry.role, entry.name) for entry in self.bindings]
        captions = [
            (entry.user_id, entry.project_name, entry.content_digest)
            for entry in self.bindings
            if entry.role == "CAPTION"
        ]
        if len(set(named)) != len(named) or len(set(captions)) != len(captions):
            raise ValueError("catalog input bindings are ambiguous")
        policies: dict[tuple[str, str, int], str] = {}
        for config in self.configs:
            for policy in (config.applicability_policy, config.threshold_policy, config.reference_policy):
                if policy is None:
                    continue
                key = (policy.schema_id, policy.policy_id, policy.revision)
                digest = policy_digest(policy)
                if key in policies and policies[key] != digest:
                    raise ValueError("catalog policy identity has conflicting bodies")
                policies[key] = digest
        if len(canonical_json_bytes(self)) > 1048576:
            raise ValueError("catalog exceeds byte ceiling")
        return self

    def resolve(self, request: ProbeRequest) -> ProbeConfig:
        validate_probe_envelope(request)
        request = ProbeRequest.model_validate(request)
        catalog = ProbeCatalog.model_validate(self)
        rule = request.rule
        for config in catalog.configs:
            primary = config.primary_tool()
            if (
                (rule.rule_id, rule.probe_kind, rule.config_schema_id, rule.config_digest)
                == (config.rule_id, config.recipe, config.schema_id, config_digest(config))
                and rule.tool_identity == primary.name
                and rule.tool_version_constraint in {primary.version, "==" + primary.version}
                and (rule.applicability_policy_id, rule.applicability_policy_digest)
                == (config.applicability_policy.policy_id, policy_digest(config.applicability_policy))
                and (rule.threshold_policy_id, rule.threshold_policy_digest)
                == (config.threshold_policy.policy_id, policy_digest(config.threshold_policy))
            ):
                if config.reference_policy is not None and (
                    request.profile.policy.reference_eligibility_policy_id,
                    request.profile.policy.reference_eligibility_policy_digest,
                ) != (config.reference_policy.policy_id, policy_digest(config.reference_policy)):
                    raise RequiredEvidenceMissingError()
                return config
        raise RequiredEvidenceMissingError()

    def input_binding(self, request: ProbeRequest, config: ProbeConfig) -> ProbeInputBinding | None:
        """Select the scoped companion locator of an admitted recipe; absence keeps its typed cause."""
        scope = (request.user_id, request.project_name)
        if config.recipe == "CAPTIONS":
            caption = request.subject.caption_digest
            matches = [
                entry
                for entry in self.bindings
                if entry.role == "CAPTION"
                and (entry.user_id, entry.project_name, entry.content_digest) == (*scope, caption)
            ]
            if caption is None or len(matches) != 1:
                raise RequiredEvidenceMissingError()
            return matches[0]
        if config.recipe == "REFERENCE_VMAF":
            reference = config.reference_policy
            matches = [
                entry
                for entry in self.bindings
                if reference is not None
                and entry.role == "REFERENCE"
                and (entry.user_id, entry.project_name, entry.name) == (*scope, reference.reference_name)
            ]
            if len(matches) != 1:
                raise ReferenceInvalidError()
            return matches[0]
        return None

    def digest(self) -> str:
        return _private_digest(self.schema_id, ProbeCatalog.model_validate(self))


_IDENTITY_FIELDS = frozenset(
    {
        "actor_id",
        "applicability_policy_id",
        "approval_record",
        "artifact_key",
        "artifact_ref",
        "assessor_identity",
        "assessor_qualification_ref",
        "assessor_version",
        "audio_description_policy_id",
        "authorization_id",
        "candidate_id",
        "caption_rubric_id",
        "child_artifact_key",
        "claim_ledger_projection_ref",
        "cohort_id",
        "command_id",
        "config_schema_id",
        "conformance_target",
        "created_by",
        "custodian_authorization_id",
        "custodian_policy_id",
        "custodian_policy_version",
        "dependency_ref",
        "disagreement_policy_id",
        "distinct_independence_groups",
        "escalation_requirement_id",
        "evidence_refs",
        "execution_ref",
        "execution_refs",
        "fingerprint",
        "host_version_ref",
        "id",
        "independence_group",
        "invariant_ids",
        "issuer_id",
        "language",
        "measurement_schema_id",
        "non_waiverable_failure_codes",
        "object_ref",
        "parent_artifact_key",
        "policy_id",
        "policy_version",
        "probe_kind",
        "probe_receipt_ref",
        "product_surface",
        "project_name",
        "publication_authorization_id",
        "publication_policy_id",
        "publication_policy_version",
        "qualification_policy_id",
        "ref",
        "reference_eligibility_policy_id",
        "reference_relationship",
        "refs",
        "requirement_id",
        "research_pack_ref",
        "result_ref",
        "rubric_id",
        "rule_id",
        "rule_ids",
        "scope",
        "selected_by",
        "selected_candidate_id",
        "slot_id",
        "subject_locator",
        "threshold_policy_id",
        "tool_identity",
        "tool_version_constraint",
        "user_id",
        "validity_receipt_ref",
        "version",
        "waiverable_rule_ids",
    }
)


def _identity_lengths(value: object, field: str = "") -> None:
    if isinstance(value, str) and field in _IDENTITY_FIELDS and len(value.encode("utf-8")) > 255:
        raise OperationalEnvelopeExceededError()
    if isinstance(value, dict):
        for key, child in value.items():
            _identity_lengths(child, key)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _identity_lengths(child, field)


def validate_probe_envelope(request: ProbeRequest) -> None:
    """Validate complete data and cached bodies, without resolving stored authority or doing I/O."""
    try:
        normalized = ProbeRequest.model_validate(request)
        if len(canonical_json_bytes(normalized)) > 1048576:
            raise OperationalEnvelopeExceededError()
        _identity_lengths(normalized.model_dump(mode="json"))
        verify_caches(normalized)
    except M10Error:
        raise
    except (TypeError, ValueError, RecursionError):
        raise RequiredEvidenceMissingError() from None


def _within(value: Fraction, policy: ThresholdPolicy) -> bool:
    return (policy.minimum is None or value >= Fraction(policy.minimum)) and (
        policy.maximum is None or value <= Fraction(policy.maximum)
    )


def _technical_status(
    config: ProbeConfig, facts: ContainerFacts | DecodeFacts | IntervalFacts | LoudnessFacts | CaptionFacts | VmafFacts
) -> Literal["PASS", "FAIL", "INAPPLICABLE", "INDETERMINATE"]:
    if config.recipe != facts.kind:
        raise ProbeFailedError()
    if isinstance(facts, ContainerFacts):
        kinds = {stream.kind for stream in facts.streams}
        if (config.parameters.require_video and "VIDEO" not in kinds) or (
            config.parameters.require_audio and "AUDIO" not in kinds
        ):
            return "FAIL"
        return "PASS" if facts.duration.as_fraction() > 0 else "INDETERMINATE"
    if isinstance(facts, DecodeFacts):
        return "PASS" if facts.complete else "INDETERMINATE"
    if isinstance(facts, IntervalFacts):
        if any(item.kind not in config.parameters.interval_kinds for item in facts.intervals):
            raise ProbeFailedError()
        if facts.measured_duration.as_fraction() <= 0:
            return "INDETERMINATE"
        maximum = max(
            ((item.end.as_fraction() - item.start.as_fraction()) * 1000 for item in facts.intervals),
            default=Fraction(0),
        )
        return "PASS" if _within(maximum, config.threshold_policy) else "FAIL"
    if isinstance(facts, LoudnessFacts):
        if facts.state == "SILENT":
            return "INAPPLICABLE" if config.applicability_policy.mode == "SILENT_AUDIO_INAPPLICABLE" else "FAIL"
        if facts.integrated_lufs is None:
            return "INDETERMINATE"
        return "PASS" if _within(Fraction(facts.integrated_lufs), config.threshold_policy) else "FAIL"
    if isinstance(facts, CaptionFacts):
        if facts.format != config.parameters.caption_format:
            raise ProbeFailedError()
        if facts.measured_duration.as_fraction() <= 0:
            return "INDETERMINATE"
        ratio = facts.union_coverage.as_fraction() / facts.measured_duration.as_fraction()
        return "PASS" if _within(ratio, config.threshold_policy) else "FAIL"
    if config.reference_policy is None or facts.model_digest != config.reference_policy.model_digest:
        raise ReferenceInvalidError()
    return "PASS" if _within(Fraction(facts.mean), config.threshold_policy) else "FAIL"


def build_probe_measurement(
    config: ProbeConfig,
    *,
    input_digests: tuple[str, ...],
    facts: ContainerFacts | DecodeFacts | IntervalFacts | LoudnessFacts | CaptionFacts | VmafFacts,
) -> ProbeMeasurement:
    """Project deterministic technical policy outcomes; construction grants no execution custody."""
    config = ProbeConfig.model_validate(config)
    expected_inputs = 2 if config.recipe in {"CAPTIONS", "REFERENCE_VMAF"} else 1
    if len(input_digests) != expected_inputs:
        if config.recipe == "REFERENCE_VMAF":
            raise ReferenceInvalidError()
        raise ProbeFailedError()
    facts = type(facts).model_validate(facts)
    status = _technical_status(config, facts)
    findings = ()
    if status in {"FAIL", "INDETERMINATE"}:
        locator = (
            "reference" if config.recipe == "REFERENCE_VMAF" else "captions" if config.recipe == "CAPTIONS" else "media"
        )
        findings = (
            ProbeFinding(
                rule_id=config.rule_id,
                severity="BLOCKING" if status == "FAIL" else "ADVISORY",
                subject_locator=locator,
                evidence_digest=facts_digest(facts),
            ),
        )
    return ProbeMeasurement(
        schema_id="m10.probe-measurement.v1",
        recipe=config.recipe,
        input_digests=input_digests,
        tool_identity_digest=tool_identity_digest(config),
        config_digest=config_digest(config),
        parser_version=config.parser_version,
        facts=facts,
        status=status,
        findings=findings,
    )


def _unique_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_json_constant(value: str) -> None:
    raise ValueError("nonfinite JSON number")


def normalize_probe_result(config: ProbeConfig, raw: bytes) -> ProbeMeasurement:
    try:
        config = ProbeConfig.model_validate(config)
        if type(raw) is not bytes:
            raise ProbeFailedError()
        if len(raw) > config.max_output_bytes:
            raise OperationalEnvelopeExceededError()
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_json_pairs, parse_constant=_invalid_json_constant
        )
        measurement = ProbeMeasurement.model_validate(value)
        expected = build_probe_measurement(config, input_digests=measurement.input_digests, facts=measurement.facts)
        if canonical_json_bytes(measurement) != canonical_json_bytes(expected):
            raise ProbeFailedError()
        return expected
    except M10Error:
        raise
    except (TypeError, ValueError, RecursionError):
        raise ProbeFailedError() from None


DEFAULT_PROBE_CATALOG = ProbeCatalog(schema_id="m10.probe-catalog.v1", configs=())
