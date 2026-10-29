"""Fixed recipes measure committed fixtures through the real isolated worker on the qualification host.

The pinned VMAF 3.2.1 binary lives in a private developer cache (`M10_VMAF_BINARY` overrides the default
location); its bytes are checked against the qualified digest before use. Tiny fixtures qualify the mechanism
only, not any cohort threshold.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from r2.quality.errors import (
    OperationalEnvelopeExceededError,
    ProbeFailedError,
    ReferenceInvalidError,
    RequiredEvidenceMissingError,
)
from server.services import quality_probe_runtime as runtime
from server.services.quality_probe_inputs import snapshot_probe_inputs
from tests.integration.server.services.test_quality_probe_runtime import sha, tool
from tests.unit.server.services.test_quality_probe_inputs import bound_request, catalog

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "r2" / "quality_probes"
VMAF_BINARY = Path(os.environ.get("M10_VMAF_BINARY", str(Path.home() / ".m10-vmaf-d1hmnn0r" / "vmaf")))
VMAF_SHA256 = "55e2eeff3ecefe8585467afc215d25ab27dcba109bc03f65e71a77ea4e634cdd"
VMAF_MODEL = FIXTURES / "vmaf_v0.6.1.json"
VMAF_MODEL_SHA256 = "5950d61fa1f861bd45d8149d80539ed9f3376cfc2495b8f0fa8e9f57cb131ee3"


def vmaf_tool() -> dict[str, object]:
    assert hashlib.sha256(VMAF_BINARY.read_bytes()).hexdigest() == VMAF_SHA256
    assert hashlib.sha256(VMAF_MODEL.read_bytes()).hexdigest() == VMAF_MODEL_SHA256
    output = subprocess.run(
        [str(VMAF_BINARY), "--version"], capture_output=True, env={"LC_ALL": "C", "TZ": "UTC"}, check=True, timeout=10
    ).stdout
    return {
        "name": "vmaf",
        "version": "3.2.1",
        "executable_digest": "sha256:" + VMAF_SHA256,
        "build_digest": sha(output),
        "model_digest": "sha256:" + VMAF_MODEL_SHA256,
    }


def config_for(recipe: str, *, parameters: dict | None = None, threshold: dict | None = None, **changes):
    from r2.quality.probes import ProbeConfig
    from tests.unit.r2.quality.test_probes import config_data, recipe_config

    if recipe == "CONTAINER_STREAM":
        data = config_data()
        data.update(config_id="container_stream", recipe=recipe, tools=[data["tools"][1]])
    else:
        data = recipe_config(recipe).model_dump(mode="json")
    names = [item["name"] for item in data["tools"]]
    real = {"ffmpeg": tool, "ffprobe": tool, "vmaf": lambda _: vmaf_tool()}
    data["tools"] = [real[name](name) for name in names]
    if data["reference_policy"] is not None:
        data["reference_policy"]["model_digest"] = "sha256:" + VMAF_MODEL_SHA256
    data["parameters"].update(parameters or {})
    data["threshold_policy"].update(threshold or {})
    data.update(changes)
    return ProbeConfig.model_validate(data)


def host() -> runtime.ProbeHost:
    return runtime.ProbeHost(
        tools={"ffmpeg": Path("/usr/bin/ffmpeg"), "ffprobe": Path("/usr/bin/ffprobe"), "vmaf": VMAF_BINARY},
        vmaf_model=VMAF_MODEL,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir(mode=0o700)
    return root


async def measure(project: Path, config, media: str, *, caption: str | None = None, reference: str | None = None):
    from tests.unit.server.services.test_quality_probe_inputs import binding

    master = project / ("master-" + media)
    shutil.copyfile(FIXTURES / media, master)
    bindings = []
    caption_digest = None
    if caption is not None:
        shutil.copyfile(FIXTURES / caption, project / caption)
        entry = binding("CAPTION", "captions", caption, (FIXTURES / caption).read_bytes())
        bindings.append(entry)
        caption_digest = entry.content_digest
    if reference is not None:
        shutil.copyfile(FIXTURES / reference, project / ("ref-" + reference))
        bindings.append(
            binding("REFERENCE", "approved-source", "ref-" + reference, (FIXTURES / reference).read_bytes())
        )
    _, request = bound_request(config, master, caption_digest=caption_digest)
    async with snapshot_probe_inputs(request, project_root=project, catalog=catalog(config, *bindings)) as inputs:
        return await runtime.QualityProbeRuntime(host()).run(request, inputs, config)


async def test_container_reports_typed_mp4_streams_and_policy_requires_audio(project: Path) -> None:
    result = await measure(project, config_for("CONTAINER_STREAM", parameters={"require_audio": True}), "av.mp4")
    facts = result.measurement.facts
    assert result.measurement.status == "PASS"
    assert facts.duration.as_fraction() == 3
    streams = facts.streams
    assert [(item.kind, item.codec) for item in streams] == [("VIDEO", "h264"), ("AUDIO", "aac")]
    assert (streams[0].width, streams[0].height, streams[0].frame_rate.as_fraction()) == (64, 64, 10)
    assert (streams[1].sample_rate, streams[1].channels) == (16000, 1)
    missing = await measure(
        project, config_for("CONTAINER_STREAM", parameters={"require_audio": True}), "video_only.mp4"
    )
    assert missing.measurement.status == "FAIL"


async def test_a_full_range_h264_master_is_measured_and_reported_as_full_range(project: Path) -> None:
    result = await measure(
        project, config_for("CONTAINER_STREAM", parameters={"require_audio": True}), "av_fullrange.mp4"
    )
    assert result.measurement.status == "PASS"
    video = result.measurement.facts.streams[0]
    assert (video.codec, video.pixel_format, video.width, video.height) == ("h264", "yuvj420p", 64, 64)
    decoded = await measure(project, config_for("DECODE"), "av_fullrange.mp4")
    assert decoded.measurement.status == "PASS"


@pytest.mark.parametrize("media", ["truncated.mp4", "mpeg4.mp4"])
async def test_truncated_or_unqualified_container_is_a_probe_failure(project: Path, media: str) -> None:
    with pytest.raises(ProbeFailedError):
        await measure(project, config_for("CONTAINER_STREAM"), media)


async def test_nested_playlist_cannot_select_another_demuxer_or_protocol(project: Path) -> None:
    playlist = project / "playlist.mp4"
    playlist.write_bytes(b"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:9/segment.ts\n")
    config = config_for("CONTAINER_STREAM")
    _, request = bound_request(config, playlist)
    async with snapshot_probe_inputs(request, project_root=project, catalog=catalog(config)) as inputs:
        with pytest.raises(ProbeFailedError):
            await runtime.QualityProbeRuntime(host()).run(request, inputs, config)


async def test_decode_is_complete_for_qualified_media(project: Path) -> None:
    result = await measure(project, config_for("DECODE"), "av.mp4")
    assert result.measurement.status == "PASS"
    assert result.measurement.facts.stream_indices == (0, 1)
    assert result.measurement.facts.complete


INTERVAL_PARAMETERS = {
    "require_audio": True,
    "black_min_duration_ms": 500,
    "freeze_min_duration_ms": 500,
    "silence_min_duration_ms": 500,
}


async def test_intervals_record_black_freeze_and_silence_with_an_eof_bound(project: Path) -> None:
    config = config_for("INTERVALS", parameters=INTERVAL_PARAMETERS, threshold={"maximum": "1500"})
    result = await measure(project, config, "intervals.mp4")
    facts = result.measurement.facts
    intervals = facts.intervals
    assert facts.measured_duration.as_fraction() == 4
    kinds = {item.kind for item in intervals}
    assert kinds == {"BLACK", "FREEZE", "SILENCE"}
    black = next(item for item in intervals if item.kind == "BLACK")
    silence = next(item for item in intervals if item.kind == "SILENCE")
    assert (black.start.as_fraction(), black.end.as_fraction()) == (0, 1)
    assert silence.start.as_fraction() == 0
    assert 1 <= silence.end.as_fraction() < 1.01
    eof = [item for item in intervals if item.ended_at_eof]
    assert eof
    assert all(item.end.as_fraction() == 4 for item in eof)
    assert result.measurement.status == "PASS"
    strict = config_for("INTERVALS", parameters=INTERVAL_PARAMETERS, threshold={"maximum": "900"})
    assert (await measure(project, strict, "intervals.mp4")).measurement.status == "FAIL"


async def test_clean_media_has_no_detected_intervals(project: Path) -> None:
    config = config_for("INTERVALS", parameters=INTERVAL_PARAMETERS, threshold={"maximum": "0"})
    result = await measure(project, config, "av.mp4")
    assert result.measurement.facts.intervals == ()
    assert result.measurement.status == "PASS"


async def test_loudness_is_finite_silent_or_unmeasurable_never_zero(project: Path) -> None:
    from tests.unit.r2.quality.test_probes import recipe_config

    finite = await measure(project, config_for("LOUDNESS"), "av.mp4")
    assert finite.measurement.facts.state == "FINITE"
    assert finite.measurement.facts.integrated_lufs == "-21.7"
    assert finite.measurement.status == "PASS"
    silent = await measure(project, config_for("LOUDNESS"), "silent.mp4")
    assert silent.measurement.facts.state == "SILENT"
    assert silent.measurement.status == "FAIL"
    policy = recipe_config("LOUDNESS").applicability_policy.model_dump(mode="json")
    inapplicable = config_for(
        "LOUDNESS",
        applicability_policy=policy | {"policy_id": "silent-ok", "mode": "SILENT_AUDIO_INAPPLICABLE"},
    )
    assert (await measure(project, inapplicable, "silent.mp4")).measurement.status == "INAPPLICABLE"
    absent = await measure(project, config_for("LOUDNESS"), "video_only.mp4")
    assert absent.measurement.facts.state == "UNMEASURABLE"
    assert absent.measurement.status == "INDETERMINATE"


async def test_caption_timing_coverage_and_overlap_without_caption_text(project: Path) -> None:
    good = await measure(project, config_for("CAPTIONS", threshold={"minimum": "0.6"}), "av.mp4", caption="good.srt")
    facts = good.measurement.facts
    assert facts.cue_count == 2
    assert facts.union_coverage.as_fraction() == 2
    assert good.measurement.status == "PASS"
    assert b"first" not in good.model_dump_json().encode()
    overlap = await measure(project, config_for("CAPTIONS"), "av.mp4", caption="overlap.srt")
    assert overlap.measurement.facts.overlap_count == 1
    assert overlap.measurement.status == "FAIL"
    vtt = config_for("CAPTIONS", parameters={"caption_format": "WEBVTT"}, threshold={"minimum": "0.6"})
    assert (await measure(project, vtt, "av.mp4", caption="good.vtt")).measurement.status == "PASS"


@pytest.mark.parametrize("caption", ["malformed.srt", "out_of_duration.srt", "reversed.srt", "invalid_utf8.srt"])
async def test_invalid_caption_bytes_are_a_probe_failure(project: Path, caption: str) -> None:
    with pytest.raises(ProbeFailedError):
        await measure(project, config_for("CAPTIONS"), "av.mp4", caption=caption)


async def test_vmaf_same_reference_is_reproducible_and_changed_reference_differs(project: Path) -> None:
    from r2.quality.probes import measurement_digest

    config = config_for("REFERENCE_VMAF", threshold={"minimum": "95", "maximum": "100"})
    first = await measure(project, config, "reference.mp4", reference="reference.mp4")
    second = await measure(project, config, "reference.mp4", reference="reference.mp4")
    changed = await measure(project, config, "reference.mp4", reference="reference_changed.mp4")
    assert measurement_digest(first.measurement) == measurement_digest(second.measurement)
    facts = first.measurement.facts
    assert facts.span == "FIRST_5_FRAMES"
    assert [frame.index for frame in facts.frames] == [0, 1, 2, 3, 4]
    assert first.measurement.status == "PASS"
    assert changed.measurement.facts.mean != facts.mean
    assert changed.measurement.status == "FAIL"
    assert first.resources.scratch_sizes[0] == first.resources.scratch_sizes[1] == 64 * 64 * 3 // 2 * 5


@pytest.mark.parametrize(
    "reference", ["reference_fps5.mp4", "reference_small.mp4", "reference_short.mp4", "truncated.mp4"]
)
async def test_incomparable_or_insufficient_reference_is_reference_invalid(project: Path, reference: str) -> None:
    with pytest.raises(ReferenceInvalidError):
        await measure(project, config_for("REFERENCE_VMAF"), "reference.mp4", reference=reference)


async def test_vmaf_without_a_qualified_model_or_binding_fails_by_cause(project: Path) -> None:
    config = config_for("REFERENCE_VMAF")
    with pytest.raises(ReferenceInvalidError):
        await measure(project, config, "reference.mp4")
    master = project / "master.mp4"
    shutil.copyfile(FIXTURES / "reference.mp4", master)
    from tests.unit.server.services.test_quality_probe_inputs import binding

    shutil.copyfile(FIXTURES / "reference.mp4", project / "ref.mp4")
    entry = binding("REFERENCE", "approved-source", "ref.mp4", (FIXTURES / "reference.mp4").read_bytes())
    _, request = bound_request(config, master)
    foreign_model = project / "model.json"
    foreign_model.write_bytes(b"{}")
    wrong = runtime.ProbeHost(tools=host().tools, vmaf_model=foreign_model)
    async with snapshot_probe_inputs(request, project_root=project, catalog=catalog(config, entry)) as inputs:
        with pytest.raises(RequiredEvidenceMissingError):
            await runtime.QualityProbeRuntime(wrong).run(request, inputs, config)


async def test_tool_output_ceiling_is_an_operational_envelope_failure(project: Path) -> None:
    with pytest.raises(OperationalEnvelopeExceededError):
        await measure(project, config_for("CONTAINER_STREAM", max_output_bytes=128), "av.mp4")


def test_full_video_vmaf_demand_is_not_expressible() -> None:
    from pydantic import ValidationError

    from r2.quality.probes import ProbeParameters

    with pytest.raises(ValidationError):
        ProbeParameters(frame_count=10)


async def test_container_and_decode_agree_with_the_existing_host_validator_on_identical_bytes(project: Path) -> None:
    """Existing format validation is unconfined and broader: it accepts any demuxer, reads r_frame_rate and
    counts decode error lines. The probe forces the MP4 demuxer, reads avg_frame_rate and refuses
    unqualified codecs; on qualified constant-rate fixtures both report the same facts."""
    from server.services.format_validation import decode_errors, media_facts

    for media in ("av.mp4", "video_only.mp4", "intervals.mp4"):
        existing = await media_facts(FIXTURES / media, ffprobe="/usr/bin/ffprobe")
        probe = (await measure(project, config_for("CONTAINER_STREAM"), media)).measurement.facts
        video = probe.streams[0]
        assert (existing.width, existing.height, existing.codec) == (video.width, video.height, video.codec)
        assert existing.fps == video.frame_rate.as_fraction()
        assert existing.duration == probe.duration.as_fraction()
        assert existing.audio == tuple(item.codec for item in probe.streams if item.kind == "AUDIO")
        decoded = (await measure(project, config_for("DECODE"), media)).measurement.facts
        assert (await decode_errors(FIXTURES / media, ffmpeg="/usr/bin/ffmpeg") == 0) == decoded.complete
    assert await decode_errors(FIXTURES / "truncated.mp4", ffmpeg="/usr/bin/ffmpeg") > 0
    with pytest.raises(ProbeFailedError):
        await measure(project, config_for("DECODE"), "truncated.mp4")
    assert (await media_facts(FIXTURES / "mpeg4.mp4", ffprobe="/usr/bin/ffprobe")).codec == "mpeg4"
    with pytest.raises(ProbeFailedError):
        await measure(project, config_for("CONTAINER_STREAM"), "mpeg4.mp4")


async def test_decode_refuses_media_missing_a_required_stream(project: Path) -> None:
    with pytest.raises(ProbeFailedError):
        await measure(project, config_for("DECODE", parameters={"require_audio": True}), "video_only.mp4")
