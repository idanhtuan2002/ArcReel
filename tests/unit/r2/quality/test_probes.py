"""Measured timing and loudness have strict, immutable canonical representations."""

from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError


def probes():
    try:
        return importlib.import_module("r2.quality.probes")
    except ModuleNotFoundError:
        pytest.fail("Probe measurements are unavailable")


def time(numerator: int, denominator: int = 1):
    return probes().MediaTime(numerator=numerator, denominator=denominator)


def interval(start: int, end: int, *, eof: bool = False):
    return probes().Interval(kind="BLACK", start=time(start), end=time(end), ended_at_eof=eof)


def test_time_reduces_exact_rationals_without_float_conversion() -> None:
    assert time(2, 6) == time(1, 3)
    assert time(-2, 6).model_dump() == {"numerator": -1, "denominator": 3}
    assert time(0, 123).denominator == 1
    assert time(1, 3).as_fraction() * 3 == 1


@pytest.mark.parametrize(("numerator", "denominator"), [(True, 1), (1, True), ("1", 2), (1, "2"), (1, 0), (1, -1)])
def test_time_rejects_coerced_integer_and_nonpositive_denominator(numerator, denominator) -> None:
    with pytest.raises(ValidationError):
        probes().MediaTime(numerator=numerator, denominator=denominator)


def test_measurements_are_frozen_extra_forbid_and_revalidated() -> None:
    measured = time(2, 3)
    with pytest.raises(ValidationError):
        measured.numerator = 5
    with pytest.raises(ValidationError):
        probes().MediaTime(numerator=1, denominator=1, guessed_duration=100)
    forged = measured.model_copy(update={"denominator": 0})
    with pytest.raises(ValidationError):
        probes().MediaTime.model_validate(forged)


@pytest.mark.parametrize(("start", "end"), [(-1, 1), (2, 1)])
def test_interval_refuses_negative_or_reversed_bounds(start: int, end: int) -> None:
    with pytest.raises(ValidationError):
        interval(start, end)


def test_eof_interval_must_close_at_the_independently_measured_duration() -> None:
    facts = probes().IntervalFacts(measured_duration=time(3), intervals=(interval(1, 3, eof=True),))
    assert facts.intervals[0].ended_at_eof is True
    for item in (interval(1, 2, eof=True), interval(1, 4)):
        with pytest.raises(ValidationError):
            probes().IntervalFacts(measured_duration=time(3), intervals=(item,))


def test_interval_input_preserves_explicit_order_and_rejects_duplicates() -> None:
    first, second = interval(0, 1), interval(2, 3)
    for items in [(second, first), (first, first), {first, second}]:
        with pytest.raises((ValidationError, ValueError)):
            probes().IntervalFacts(measured_duration=time(3), intervals=items)
    assert probes().IntervalFacts(measured_duration=time(3), intervals=(first, second)).intervals == (first, second)


@pytest.mark.parametrize(
    ("value", "expected"), [("-23.0000", "-23"), ("-0.000", "0"), ("1e-3", "0.001"), ("+2.500", "2.5")]
)
def test_loudness_decimal_strings_are_canonical(value: str, expected: str) -> None:
    facts = probes().LoudnessFacts(state="FINITE", integrated_lufs=value, true_peak_dbfs="-1.00")
    assert facts.integrated_lufs == expected
    assert facts.true_peak_dbfs == "-1"


@pytest.mark.parametrize("value", [float("nan"), -23.0, "NaN", "Infinity", "-inf", " 1", "1_000", "1e9999", "1e-9999"])
def test_loudness_rejects_nonfinite_nonstrings_and_unbounded_decimal_expansion(value) -> None:
    with pytest.raises(ValidationError):
        probes().LoudnessFacts(state="FINITE", integrated_lufs=value, true_peak_dbfs="-1")


@pytest.mark.parametrize("state", ["SILENT", "UNMEASURABLE"])
def test_absent_numeric_loudness_is_explicit_and_never_zero(state: str) -> None:
    facts = probes().LoudnessFacts(state=state, integrated_lufs=None, true_peak_dbfs=None)
    assert facts.integrated_lufs is None
    for values in [("0", None), (None, "0"), ("0", "0")]:
        with pytest.raises(ValidationError):
            probes().LoudnessFacts(state=state, integrated_lufs=values[0], true_peak_dbfs=values[1])
    with pytest.raises(ValidationError):
        probes().LoudnessFacts(state="FINITE", integrated_lufs=None, true_peak_dbfs=None)


def test_decimal_normalization_does_not_inherit_the_callers_arithmetic_context() -> None:
    from decimal import ROUND_DOWN, DecimalException, localcontext

    with localcontext() as context:
        context.prec = 3
        context.Emax = 3
        context.rounding = ROUND_DOWN
        try:
            result = probes().canonical_decimal("1e4")
        except DecimalException:
            pytest.fail("Measurement normalization inherited an unrelated arithmetic context")
    assert result == "10000"


def video_stream():
    return {
        "index": 0,
        "kind": "VIDEO",
        "codec": "h264",
        "width": 64,
        "height": 64,
        "pixel_format": "yuv420p",
        "sample_rate": None,
        "channels": None,
        "frame_rate": time(5),
        "time_base": time(1, 10240),
        "duration": time(1),
    }


def test_container_has_scoped_typed_stream_facts_and_no_unfiltered_metadata() -> None:
    stream = probes().StreamFacts.model_validate(video_stream())
    facts = probes().ContainerFacts(format="MP4", duration=time(1), streams=(stream,))
    assert facts.streams[0].width == 64
    with pytest.raises(ValidationError):
        probes().ContainerFacts(format="MP4", duration=time(1), streams=(stream, stream))
    with pytest.raises(ValidationError):
        probes().StreamFacts.model_validate(video_stream() | {"filename": "/private/project/master.mp4"})


@pytest.mark.parametrize(
    "change", [{"index": True}, {"width": "64"}, {"channels": 2}, {"codec": "unknown"}, {"frame_rate": time(0)}]
)
def test_stream_shape_is_strict_and_kind_specific(change) -> None:
    with pytest.raises(ValidationError):
        probes().StreamFacts.model_validate(video_stream() | change)


def test_audio_has_no_invented_video_dimensions_or_frame_rate() -> None:
    data = video_stream() | {
        "index": 1,
        "kind": "AUDIO",
        "codec": "aac",
        "width": None,
        "height": None,
        "pixel_format": None,
        "frame_rate": None,
        "sample_rate": 16000,
        "channels": 1,
    }
    audio = probes().StreamFacts.model_validate(data)
    assert audio.frame_rate is None
    with pytest.raises(ValidationError):
        probes().StreamFacts.model_validate(data | {"width": 64})


def test_decode_preserves_incomplete_state_and_rejects_ambiguous_stream_order() -> None:
    assert probes().DecodeFacts(stream_indices=(0, 1), complete=False).complete is False
    for indices in [(1, 0), (0, 0), (-1,), (True,)]:
        with pytest.raises(ValidationError):
            probes().DecodeFacts(stream_indices=indices, complete=True)


def caption_data():
    return {
        "format": "SRT",
        "measured_duration": time(5),
        "cue_count": 3,
        "cue_times": [
            {"start": time(0), "end": time(2)},
            {"start": time(1), "end": time(3)},
            {"start": time(4), "end": time(5)},
        ],
        "union_coverage": time(4),
        "overlap_count": 1,
    }


def test_caption_coverage_uses_union_and_preserves_no_caption_text() -> None:
    facts = probes().CaptionFacts.model_validate(caption_data())
    assert facts.union_coverage.as_fraction() == 4
    assert facts.overlap_count == 1
    with pytest.raises(ValidationError):
        probes().CaptionFacts.model_validate(caption_data() | {"text": "private caption"})


@pytest.mark.parametrize(
    "change", [{"cue_count": 2}, {"union_coverage": time(5)}, {"overlap_count": 0}, {"measured_duration": time(4)}]
)
def test_caption_summary_must_match_the_actual_timing_evidence(change) -> None:
    with pytest.raises(ValidationError):
        probes().CaptionFacts.model_validate(caption_data() | change)


def vmaf_data():
    return {
        "span": "FIRST_5_FRAMES",
        "width": 64,
        "height": 64,
        "frame_rate": time(5),
        "model_digest": "sha256:5950d61fa1f861bd45d8149d80539ed9f3376cfc2495b8f0fa8e9f57cb131ee3",
        "frames": [{"index": i, "score": str((i + 1) * 10)} for i in range(5)],
        "mean": "30.000000",
    }


def test_vmaf_retains_exact_five_frame_span_and_canonical_scores() -> None:
    facts = probes().VmafFacts.model_validate(vmaf_data())
    assert facts.mean == "30"
    assert tuple(frame.index for frame in facts.frames) == (0, 1, 2, 3, 4)


@pytest.mark.parametrize(
    "change",
    [
        {"span": "FULL_VIDEO"},
        {"width": 65},
        {"frame_rate": time(61)},
        {"mean": "101"},
        {"mean": "0"},
        {"frames": vmaf_data()["frames"][:4]},
    ],
)
def test_vmaf_refuses_unsupported_spans_geometry_rates_and_incoherent_scores(change) -> None:
    with pytest.raises(ValidationError):
        probes().VmafFacts.model_validate(vmaf_data() | change)


DIGEST = "sha256:" + "1" * 64


def measurement_data():
    return {
        "schema_id": "m10.probe-measurement.v1",
        "recipe": "DECODE",
        "input_digests": [DIGEST],
        "tool_identity_digest": DIGEST,
        "config_digest": DIGEST,
        "parser_version": "host-quality-parser-v1",
        "facts": {"kind": "DECODE", "stream_indices": [0], "complete": True},
        "status": "PASS",
        "findings": [],
    }


def resources_data():
    return {
        "schema_id": "m10.probe-resources.v1",
        "memory_max_bytes": 536870912,
        "swap_max_bytes": 0,
        "tasks_max": 32,
        "cpu_quota_us": 100000,
        "cpu_period_us": 100000,
        "wall_elapsed_ms": 100,
        "peak_memory_bytes": 1000000,
        "peak_tasks": 2,
        "stdout_bytes": 100,
        "stderr_bytes": 0,
        "scratch_sizes": [0, 0, 0],
        "exit_code": 0,
        "manager_result": "SUCCESS",
        "oom_killed": False,
        "deadline_exceeded": False,
        "output_exceeded": False,
        "group_cleanup_verified": True,
        "kernel_identity_digest": DIGEST,
        "control_identity_digest": DIGEST,
        "tool_identity_digest": DIGEST,
    }


def result_data():
    return {
        "schema_id": "m10.probe-execution-result.v1",
        "request_digest": DIGEST,
        "execution_id": "execution-1",
        "measurement": measurement_data(),
        "resources": resources_data(),
        "started_at": "2026-10-27T00:00:00Z",
        "finished_at": "2026-10-27T00:00:01Z",
    }


def test_incomplete_decode_cannot_be_a_passing_measurement() -> None:
    data = measurement_data()
    data["facts"]["complete"] = False
    with pytest.raises(ValidationError):
        probes().ProbeMeasurement.model_validate(data)
    measured = probes().ProbeMeasurement.model_validate(data | {"status": "INDETERMINATE"})
    assert measured.facts.complete is False


def test_measurement_kind_and_public_finding_locator_are_bound() -> None:
    with pytest.raises(ValidationError):
        probes().ProbeMeasurement.model_validate(measurement_data() | {"recipe": "LOUDNESS"})
    finding = {
        "rule_id": "decode",
        "severity": "BLOCKING",
        "subject_locator": "/home/private/master.mp4",
        "evidence_digest": DIGEST,
    }
    with pytest.raises(ValidationError):
        probes().ProbeMeasurement.model_validate(measurement_data() | {"status": "FAIL", "findings": [finding]})
    finding["subject_locator"] = "stream:0"
    assert (
        len(
            probes()
            .ProbeMeasurement.model_validate(measurement_data() | {"status": "FAIL", "findings": [finding]})
            .findings
        )
        == 1
    )


@pytest.mark.parametrize(
    "change",
    [
        {"group_cleanup_verified": False},
        {"deadline_exceeded": True},
        {"output_exceeded": True},
        {"oom_killed": True},
        {"exit_code": 1},
        {"wall_elapsed_ms": 120001},
        {"manager_result": "TIMEOUT"},
        {"stdout_bytes": 1048577},
        {"swap_max_bytes": 1},
    ],
)
def test_failed_or_unbounded_execution_never_becomes_a_successful_result(change) -> None:
    data = result_data()
    data["resources"].update(change)
    with pytest.raises(ValidationError):
        probes().ProbeExecutionResult.model_validate(data)


def test_measurement_identity_excludes_execution_variation_but_result_digest_binds_it() -> None:
    from r2.quality.digests import DIGEST_DOMAINS

    before = tuple(DIGEST_DOMAINS)
    first = probes().ProbeExecutionResult.model_validate(result_data())
    data = result_data()
    data["resources"]["peak_memory_bytes"] += 1
    data["finished_at"] = "2026-10-27T00:00:02Z"
    second = probes().ProbeExecutionResult.model_validate(data)
    assert probes().measurement_digest(first.measurement) == probes().measurement_digest(second.measurement)
    assert probes().execution_result_digest(first) != probes().execution_result_digest(second)
    assert tuple(DIGEST_DOMAINS) == before
    assert "m10.probe-measurement.v1" not in DIGEST_DOMAINS


@pytest.mark.parametrize("field", ["config_digest", "tool_identity_digest", "input_digests"])
def test_changed_input_tool_or_config_changes_measurement_digest(field: str) -> None:
    data = measurement_data()
    first = probes().ProbeMeasurement.model_validate(data)
    other = "sha256:" + "2" * 64
    data[field] = [other] if field == "input_digests" else other
    second = probes().ProbeMeasurement.model_validate(data)
    assert probes().measurement_digest(first) != probes().measurement_digest(second)


def config_data():
    return {
        "schema_id": "m10.probe-config.v1",
        "config_id": "decode-test",
        "revision": 1,
        "rule_id": "probe",
        "recipe": "DECODE",
        "tools": [
            {
                "name": name,
                "version": "8.0.1",
                "executable_digest": DIGEST,
                "build_digest": DIGEST,
                "model_digest": None,
            }
            for name in ("ffmpeg", "ffprobe")
        ],
        "parser_version": "host-quality-parser-v1",
        "parser_digest": DIGEST,
        "parameters": {},
        "applicability_policy": {
            "schema_id": "m10.probe-applicability.v1",
            "policy_id": "required",
            "revision": 1,
            "mode": "REQUIRED",
        },
        "threshold_policy": {
            "schema_id": "m10.probe-threshold.v1",
            "policy_id": "decode-complete",
            "revision": 1,
            "metric": "EVIDENCE_COMPLETE",
            "minimum": None,
            "maximum": None,
        },
        "reference_policy": None,
        "max_runtime_ms": 120000,
        "max_output_bytes": 1048576,
    }


def probe_request_data(config):
    from r2.quality.digests import compute_digest
    from tests.unit.r2.quality.test_quality_digests import valid_subject
    from tests.unit.r2.quality.test_quality_ports import probe_data

    data = probe_data()
    data["subject"] = valid_subject()
    rule = data["profile"]["policy"]["probe_rules"][0]
    rule.update(
        probe_kind=config.recipe,
        tool_identity="ffmpeg",
        tool_version_constraint="==8.0.1",
        config_schema_id=config.schema_id,
        config_digest=probes().config_digest(config),
        applicability_policy_id=config.applicability_policy.policy_id,
        applicability_policy_digest=probes().policy_digest(config.applicability_policy),
        threshold_policy_id=config.threshold_policy.policy_id,
        threshold_policy_digest=probes().policy_digest(config.threshold_policy),
    )
    data["rule"] = rule
    profile = data["profile"]
    profile["policy_digest"] = compute_digest("m10.quality-policy.v1", profile["policy"])
    profile["profile_digest"] = compute_digest("m10.quality-profile.v1", profile)
    return data


def test_catalog_resolves_only_the_complete_published_rule_binding() -> None:
    from r2.quality.digests import compute_digest
    from r2.quality.errors import RequiredEvidenceMissingError
    from r2.quality.ports import ProbeRequest

    config = probes().ProbeConfig.model_validate(config_data())
    request = ProbeRequest.model_validate(probe_request_data(config))
    catalog = probes().ProbeCatalog(schema_id="m10.probe-catalog.v1", configs=(config,))
    assert catalog.resolve(request) == config
    assert probes().DEFAULT_PROBE_CATALOG.configs == ()
    with pytest.raises(RequiredEvidenceMissingError):
        probes().DEFAULT_PROBE_CATALOG.resolve(request)
    data = probe_request_data(config)
    data["rule"]["tool_version_constraint"] = ">=8"
    data["profile"]["policy_digest"] = compute_digest("m10.quality-policy.v1", data["profile"]["policy"])
    data["profile"]["profile_digest"] = compute_digest("m10.quality-profile.v1", data["profile"])
    with pytest.raises(RequiredEvidenceMissingError):
        catalog.resolve(ProbeRequest.model_validate(data))


def test_request_envelope_checks_nested_cached_bodies_and_identity_bytes() -> None:
    from r2.quality.errors import OperationalEnvelopeExceededError, RequiredEvidenceMissingError
    from r2.quality.ports import ProbeRequest

    config = probes().ProbeConfig.model_validate(config_data())
    request = ProbeRequest.model_validate(probe_request_data(config))
    probes().validate_probe_envelope(request)
    with pytest.raises(OperationalEnvelopeExceededError):
        probes().validate_probe_envelope(request.model_copy(update={"actor_id": "a" * 256}))
    profile = request.profile.model_copy(update={"policy_digest": "sha256:" + "2" * 64})
    with pytest.raises(RequiredEvidenceMissingError):
        probes().validate_probe_envelope(request.model_copy(update={"profile": profile}))


def test_config_and_catalog_reject_commands_duplicates_and_incomplete_tool_sets() -> None:
    data = config_data()
    with pytest.raises(ValidationError):
        probes().ProbeConfig.model_validate(data | {"argv": ["sh", "-c", "echo injected"]})
    with pytest.raises(ValidationError):
        probes().ProbeConfig.model_validate(data | {"tools": data["tools"][:1]})
    config = probes().ProbeConfig.model_validate(data)
    with pytest.raises(ValidationError):
        probes().ProbeCatalog(schema_id="m10.probe-catalog.v1", configs=(config, config))


def normalized_worker_data(config):
    data = measurement_data()
    data["config_digest"] = probes().config_digest(config)
    data["tool_identity_digest"] = probes().tool_identity_digest(config)
    return data


def test_normalizer_checks_configuration_tool_identity_and_canonical_status() -> None:
    import json

    from r2.quality.errors import ProbeFailedError

    config = probes().ProbeConfig.model_validate(config_data())
    data = normalized_worker_data(config)
    assert probes().normalize_probe_result(config, json.dumps(data).encode()).status == "PASS"
    for field, value in [
        ("config_digest", "sha256:" + "2" * 64),
        ("tool_identity_digest", "sha256:" + "3" * 64),
        ("status", "INDETERMINATE"),
    ]:
        with pytest.raises(ProbeFailedError):
            probes().normalize_probe_result(config, json.dumps(data | {field: value}).encode())


def test_normalizer_refuses_duplicate_json_keys_nonfinite_output_and_byte_flood() -> None:
    import json

    from r2.quality.errors import OperationalEnvelopeExceededError, ProbeFailedError

    config = probes().ProbeConfig.model_validate(config_data())
    valid = json.dumps(normalized_worker_data(config)).encode()
    for raw in [valid[:-1] + b',"status":"FAIL"}', b'{"value":NaN}', b"\xff", valid[:-1]]:
        with pytest.raises(ProbeFailedError):
            probes().normalize_probe_result(config, raw)
    with pytest.raises(OperationalEnvelopeExceededError):
        probes().normalize_probe_result(config, b" " * 1048577)


def recipe_config(recipe: str):
    data = config_data()
    data.update(config_id=recipe.lower(), recipe=recipe)
    policy = data["threshold_policy"]
    if recipe == "INTERVALS":
        data["parameters"] = {"require_audio": True}
        policy.update(metric="MAX_INTERVAL_MS", minimum=None, maximum="1500")
    elif recipe == "LOUDNESS":
        data["parameters"] = {"require_audio": True}
        policy.update(metric="INTEGRATED_LUFS", minimum="-24", maximum="-14")
    elif recipe == "CAPTIONS":
        data["tools"] = [data["tools"][1]]
        policy.update(metric="CAPTION_COVERAGE_RATIO", minimum="0.9", maximum=None)
    elif recipe == "REFERENCE_VMAF":
        model = vmaf_data()["model_digest"]
        data["tools"].append(
            {
                "name": "vmaf",
                "version": "3.2.1",
                "executable_digest": DIGEST,
                "build_digest": DIGEST,
                "model_digest": model,
            }
        )
        data["reference_policy"] = {
            "schema_id": "m10.probe-reference-eligibility.v1",
            "policy_id": "reference",
            "revision": 1,
            "reference_name": "approved-source",
            "mode": "SAME_CONTENT_ZERO_OFFSET_EQUAL_GEOMETRY",
            "model_digest": model,
        }
        policy.update(metric="VMAF_MEAN", minimum="95", maximum="100")
    return probes().ProbeConfig.model_validate(data)


def test_reference_measurement_requires_both_target_and_reference_input_identities() -> None:
    from r2.quality.errors import ReferenceInvalidError

    config = recipe_config("REFERENCE_VMAF")
    facts = probes().VmafFacts.model_validate(vmaf_data())
    with pytest.raises(ReferenceInvalidError):
        probes().build_probe_measurement(config, input_digests=(DIGEST,), facts=facts)
    assert probes().build_probe_measurement(config, input_digests=(DIGEST, DIGEST), facts=facts).status == "FAIL"


def test_caption_measurement_requires_the_caption_bytes_as_well_as_media() -> None:
    from r2.quality.errors import ProbeFailedError

    config = recipe_config("CAPTIONS")
    facts = probes().CaptionFacts.model_validate(caption_data())
    with pytest.raises(ProbeFailedError):
        probes().build_probe_measurement(config, input_digests=(DIGEST,), facts=facts)


def test_profile_specific_detectors_and_loudness_policies_produce_evidence_only() -> None:
    config = recipe_config("INTERVALS")
    facts = probes().IntervalFacts(measured_duration=time(4), intervals=(interval(0, 2),))
    measurement = probes().build_probe_measurement(config, input_digests=(DIGEST,), facts=facts)
    assert measurement.status == "FAIL"
    assert measurement.findings[0].subject_locator == "media"
    assert not hasattr(measurement, "decision")
    config = recipe_config("LOUDNESS")
    facts = probes().LoudnessFacts(state="FINITE", integrated_lufs="-20", true_peak_dbfs="-1")
    assert probes().build_probe_measurement(config, input_digests=(DIGEST,), facts=facts).status == "PASS"
    silent = probes().LoudnessFacts(state="SILENT", integrated_lufs=None, true_peak_dbfs=None)
    assert probes().build_probe_measurement(config, input_digests=(DIGEST,), facts=silent).status == "FAIL"
    data = config.model_dump(mode="python")
    data["applicability_policy"]["mode"] = "SILENT_AUDIO_INAPPLICABLE"
    allowed = probes().ProbeConfig.model_validate(data)
    assert probes().build_probe_measurement(allowed, input_digests=(DIGEST,), facts=silent).status == "INAPPLICABLE"


def test_same_policy_identity_cannot_have_conflicting_bodies_inside_a_catalog() -> None:
    first = recipe_config("INTERVALS")
    data = first.model_dump(mode="python")
    data["config_id"] = "intervals-second"
    data["threshold_policy"]["maximum"] = "1000"
    second = probes().ProbeConfig.model_validate(data)
    with pytest.raises(ValidationError):
        probes().ProbeCatalog(schema_id="m10.probe-catalog.v1", configs=(first, second))


@pytest.mark.parametrize("case", ["tool_version", "model_digest", "public_locator", "reference_name"])
def test_scalar_strings_never_accept_coerced_byte_values(case: str) -> None:
    if case == "tool_version":
        data = config_data()["tools"][0] | {"version": b"8.0.1"}
        model = probes().ToolIdentity
    elif case == "model_digest":
        data = vmaf_data() | {"model_digest": vmaf_data()["model_digest"].encode()}
        model = probes().VmafFacts
    elif case == "reference_name":
        data = recipe_config("REFERENCE_VMAF").reference_policy.model_dump() | {"reference_name": b"approved-source"}
        model = probes().ReferenceEligibilityPolicy
    else:
        data = {"rule_id": "probe", "severity": "ADVISORY", "subject_locator": b"media", "evidence_digest": DIGEST}
        model = probes().ProbeFinding
    with pytest.raises(ValidationError):
        model.model_validate(data)
