"""Same-fixture Kalinga parity: the exact pinned donor functions and the M10-A seams measure identical inputs.

Donor sources come only from the digest-checked fixture and run inside this test; no product path imports them.
Rows and winning rules are frozen in `R2_M10_A7_KALINGA_BASELINE.json`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import shutil
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from r2.quality.errors import (
    DispositionUnauthorizedError,
    ProbeFailedError,
    RequiredEvidenceMissingError,
)
from r2.quality.probes import measurement_digest
from server.services import quality_probe_runtime as runtime
from server.services.quality_probe_inputs import snapshot_probe_inputs
from tests.integration.server.services.test_quality_probe_recipes import FIXTURES, config_for, host, measure, project
from tests.unit.r2.contracts.test_quality import NOW
from tests.unit.r2.quality.test_dispositions import disposition, rules, subject
from tests.unit.r2.quality.test_runs import admitted, close, human_slot, profile, requirement, technical_slot
from tests.unit.server.services.test_quality_probe_inputs import binding, bound_request, catalog

__all__ = ["project"]

ROOT = Path(__file__).resolve().parents[4]
KALINGA = ROOT / "tests" / "fixtures" / "r2" / "m10_kalinga"
BASELINE = json.loads((ROOT / "docs" / "r2" / "evidence" / "R2_M10_A7_KALINGA_BASELINE.json").read_text("utf-8"))
TEMPLATE = {"duration_range": [1, 10], "virality_min_overall": 40, "virality_min_hook": 35}
OVERHEAD_MS = 1500


def _fixture_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _fixture_digest(path: Path) -> str:
    return hashlib.sha256(_fixture_bytes(path)).hexdigest()


@pytest.fixture(scope="module")
def donor() -> dict[str, Any]:
    for relative, digest in BASELINE["fixtures_sha256"].items():
        assert _fixture_digest(ROOT / relative) == digest, relative
    pinned = json.loads((KALINGA / "donor_functions.json").read_text("utf-8"))
    assert pinned["commit_sha"] == BASELINE["donor"]["commit_sha"]
    assert pinned["files"] == BASELINE["donor"]["blob_sha256"]
    namespace: dict[str, Any] = {"json": json, "re": re, "Path": Path, "subprocess": subprocess}
    for function in pinned["functions"]:
        assert hashlib.sha256(function["source"].encode("utf-8")).hexdigest() == function["sha256"]
        exec(compile(function["source"], function["path"], "exec"), namespace)
    expression = pinned["run_ok_expression"]
    assert hashlib.sha256(expression["source"].encode("utf-8")).hexdigest() == expression["sha256"]

    def run_ok(qc: list[str], virality: dict[str, Any], seo: list[str]) -> bool:
        scope = {"qc": qc, "vir": virality, "seo": seo}
        exec(compile(expression["source"], expression["path"], "exec"), {}, scope)
        return bool(scope["ok"])

    namespace["run_ok"] = run_ok
    return namespace


def folder(tmp_path: Path, media: str | None = None, *, words: list[list[dict[str, Any]]] | None = None) -> Path:
    target = tmp_path / "donor"
    target.mkdir(exist_ok=True)
    if media is not None:
        shutil.copyfile(FIXTURES / media, target / "short.mp4")
    if words is not None:
        (target / "audio.json").write_text(
            json.dumps({"segments": [{"words": item} for item in words]}), encoding="utf-8"
        )
    return target


async def measure_caption(project: Path, config, media: str, caption: Path):
    master = project / ("master-" + media)
    shutil.copyfile(FIXTURES / media, master)
    shutil.copyfile(caption, project / caption.name)
    entry = binding("CAPTION", "captions", caption.name, _fixture_bytes(caption))
    _, request = bound_request(config, master, caption_digest=entry.content_digest)
    async with snapshot_probe_inputs(request, project_root=project, catalog=catalog(config, entry)) as inputs:
        return await runtime.QualityProbeRuntime(host()).run(request, inputs, config)


def audio_config():
    return config_for("CONTAINER_STREAM", parameters={"require_audio": True})


def loudness_config(**changes):
    return config_for("LOUDNESS", threshold={"minimum": "-35", "maximum": "-8"}, **changes)


def caption_config():
    return config_for("CAPTIONS", threshold={"minimum": "0.6"})


async def test_missing_master_is_refused_before_any_probe(donor, project: Path, tmp_path: Path) -> None:
    assert donor["tech_qc"](folder(tmp_path), TEMPLATE) == ["short.mp4 missing"]
    config = audio_config()
    master = project / "master-av.mp4"
    shutil.copyfile(FIXTURES / "av.mp4", master)
    _, request = bound_request(config, master)
    master.unlink()
    probed = []
    with pytest.raises(RequiredEvidenceMissingError):
        async with snapshot_probe_inputs(request, project_root=project, catalog=catalog(config)) as inputs:
            probed.append(await runtime.QualityProbeRuntime(host()).run(request, inputs, config))
    assert probed == []


async def test_audio_stream_requirement_matches_the_donor(donor, project: Path, tmp_path: Path) -> None:
    assert donor["tech_qc"](folder(tmp_path, "av.mp4"), TEMPLATE) == []
    assert (await measure(project, audio_config(), "av.mp4")).measurement.status == "PASS"
    assert donor["tech_qc"](folder(tmp_path, "video_only.mp4"), TEMPLATE) == ["no audio stream"]
    assert (await measure(project, audio_config(), "video_only.mp4")).measurement.status == "FAIL"


@pytest.mark.parametrize("media", ["av.mp4", "intervals.mp4"])
async def test_sane_loudness_passes_in_both(donor, project: Path, tmp_path: Path, media: str) -> None:
    assert donor["tech_qc"](folder(tmp_path, media), TEMPLATE) == []
    result = await measure(project, loudness_config(), media)
    assert (result.measurement.facts.state, result.measurement.status) == ("FINITE", "PASS")


async def test_silent_audio_fails_in_both_and_inapplicability_is_explicit(donor, project: Path, tmp_path: Path) -> None:
    from tests.unit.r2.quality.test_probes import recipe_config

    issues = donor["tech_qc"](folder(tmp_path, "silent.mp4"), TEMPLATE)
    assert len(issues) == 1
    assert issues[0].startswith("audio very quiet")
    silent = await measure(project, loudness_config(), "silent.mp4")
    assert (silent.measurement.facts.state, silent.measurement.status) == ("SILENT", "FAIL")
    policy = recipe_config("LOUDNESS").applicability_policy.model_dump(mode="json")
    explicit = loudness_config(
        applicability_policy=policy | {"policy_id": "silent-ok", "mode": "SILENT_AUDIO_INAPPLICABLE"}
    )
    assert (await measure(project, explicit, "silent.mp4")).measurement.status == "INAPPLICABLE"


async def test_caption_timing_present_passes_in_both(donor, project: Path, tmp_path: Path) -> None:
    assert donor["tech_qc"](folder(tmp_path, "av.mp4", words=WORDS), TEMPLATE) == []
    result = await measure(project, caption_config(), "av.mp4", caption="good.srt")
    assert result.measurement.status == "PASS"


async def test_sparse_caption_timing_passes_the_donor_but_fails_coverage(donor, project: Path, tmp_path: Path) -> None:
    sparse = [[], [{"word": "x", "start": 0.0, "end": 0.1}]]
    assert donor["tech_qc"](folder(tmp_path, "av.mp4", words=sparse), TEMPLATE) == []
    result = await measure_caption(project, caption_config(), "av.mp4", KALINGA / "sparse.srt")
    assert result.measurement.status == "FAIL"


async def test_caption_without_any_timing_is_detected_by_both(donor, project: Path, tmp_path: Path) -> None:
    issues = donor["tech_qc"](folder(tmp_path, "av.mp4", words=[[]]), TEMPLATE)
    assert len(issues) == 1
    assert issues[0].startswith("no word timings")
    empty = tmp_path / "empty.srt"
    empty.write_bytes(b"")
    try:
        result = await measure_caption(project, caption_config(), "av.mp4", empty)
    except ProbeFailedError:
        return
    assert result.measurement.status == "FAIL"


async def test_missing_caption_evidence_is_skipped_by_the_donor_but_refused(
    donor, project: Path, tmp_path: Path
) -> None:
    assert donor["tech_qc"](folder(tmp_path, "av.mp4"), TEMPLATE) == []
    config = caption_config()
    master = project / "master-av.mp4"
    shutil.copyfile(FIXTURES / "av.mp4", master)
    _, request = bound_request(config, master)
    with pytest.raises(RequiredEvidenceMissingError):
        async with snapshot_probe_inputs(request, project_root=project, catalog=catalog(config)) as inputs:
            await runtime.QualityProbeRuntime(host()).run(request, inputs, config)


def review_profile():
    return profile(
        requirement("technical-required", [technical_slot()]),
        requirement("review-required", [human_slot("human")]),
    )


def test_advisory_or_missing_gates_never_pass_or_become_ready(donor, tmp_path: Path) -> None:
    virality = donor["virality_gate"](folder(tmp_path, "av.mp4"), TEMPLATE)
    assert virality["status"] == "unknown"
    assert donor["run_ok"]([], virality, []) is True

    def crashing(_path: Path) -> bool:
        raise RuntimeError("check crashed")

    assert donor["_safe_validate"](crashing, tmp_path / "short.mp4") is True
    revision = review_profile()
    with pytest.raises(RequiredEvidenceMissingError):
        close(revision, admitted(revision, "TECHNICAL", "technical-required", "technical"))
    run = close(
        revision,
        admitted(revision, "TECHNICAL", "technical-required", "technical"),
        admitted(revision, "NARRATIVE", "review-required", "human", "INDETERMINATE"),
    )
    assert ("review-required", "human", "INDETERMINATE") in rules().unmet_slots(revision, run)
    with pytest.raises(DispositionUnauthorizedError):
        rules().evaluate_decision(revision, run, subject(run, "PASS"), now=NOW)
    projected = rules().project_readiness(
        disposition(run, "PASS"), revision, run, run_state="CURRENT", run_is_head=True, now=NOW
    )
    assert projected.state == "NOT_READY"
    assert "REQUIREMENTS_UNMET" in projected.reasons


WORDS = [[{"word": "first", "start": 0.0, "end": 1.0}], [{"word": "second", "start": 1.5, "end": 2.5}]]


async def test_truncated_or_unqualified_media_is_a_typed_probe_failure(donor, project: Path, tmp_path: Path) -> None:
    for _ in range(2):
        with pytest.raises(ValueError, match="could not convert string to float"):
            donor["tech_qc"](folder(tmp_path, "truncated.mp4"), TEMPLATE)
        assert donor["tech_qc"](folder(tmp_path, "mpeg4.mp4"), TEMPLATE) == ["no audio stream"]
    for media in ("truncated.mp4", "mpeg4.mp4"):
        donor_folder = folder(tmp_path, media)
        donor_ms, m10_ms = [], []
        for _ in range(3):
            started = time.perf_counter()
            with contextlib.suppress(ValueError):
                donor["tech_qc"](donor_folder, TEMPLATE)
            donor_ms.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            with pytest.raises(ProbeFailedError) as failure:
                await measure(project, audio_config(), media)
            m10_ms.append((time.perf_counter() - started) * 1000)
            resources = runtime.failure_resources(failure.value)
            assert resources is not None
            assert resources.group_cleanup_verified
            assert (resources.memory_max_bytes, resources.swap_max_bytes) == (
                runtime.MEMORY_MAX_BYTES,
                runtime.SWAP_MAX_BYTES,
            )
            assert resources.peak_memory_bytes is not None
            assert resources.peak_memory_bytes <= resources.memory_max_bytes
            assert resources.wall_elapsed_ms <= audio_config().max_runtime_ms
            assert resources.stdout_bytes + resources.stderr_bytes <= audio_config().max_output_bytes
            assert resources.peak_tasks is not None
            assert resources.peak_tasks <= resources.tasks_max == runtime.TASKS_MAX
            assert resources.manager_result == "EXIT_CODE"
            assert resources.exit_code != 0
            assert (resources.oom_killed, resources.deadline_exceeded, resources.output_exceeded) == (
                False,
                False,
                False,
            )
        print(
            f"PERF FAILURE {media} donor_median_ms={statistics.median(donor_ms):.0f} m10_median_ms={statistics.median(m10_ms):.0f}"
        )
        assert statistics.median(m10_ms) <= statistics.median(donor_ms) + OVERHEAD_MS


async def run_case(project: Path, config, caption: str | None):
    return await measure(project, config, "av.mp4", caption=caption)


CASES = (("CONTAINER_STREAM", None), ("LOUDNESS", None), ("CAPTIONS", "good.srt"))


def case_config(recipe: str):
    return {"CONTAINER_STREAM": audio_config, "LOUDNESS": loudness_config, "CAPTIONS": caption_config}[recipe]()


@pytest.mark.parametrize(("recipe", "caption"), CASES)
async def test_measurements_are_digest_deterministic(
    donor, project: Path, tmp_path: Path, recipe: str, caption: str | None
) -> None:
    config = case_config(recipe)
    first = await run_case(project, config, caption)
    second = await run_case(project, config, caption)
    assert measurement_digest(first.measurement) == measurement_digest(second.measurement)
    donor_folder = folder(tmp_path, "silent.mp4", words=WORDS)
    assert donor["tech_qc"](donor_folder, TEMPLATE) == donor["tech_qc"](donor_folder, TEMPLATE)


@pytest.mark.parametrize(("recipe", "caption"), CASES)
async def test_bounded_probes_stay_within_the_frozen_performance_rule(
    donor, project: Path, tmp_path: Path, recipe: str, caption: str | None
) -> None:
    config = case_config(recipe)
    donor_folder = folder(tmp_path, "av.mp4", words=WORDS if caption else None)
    donor_ms, m10_ms = [], []
    for _ in range(3):
        started = time.perf_counter()
        donor["tech_qc"](donor_folder, TEMPLATE)
        donor_ms.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        result = await run_case(project, config, caption)
        m10_ms.append((time.perf_counter() - started) * 1000)
        resources = result.resources
        assert resources.manager_result == "SUCCESS"
        assert resources.group_cleanup_verified
        assert resources.wall_elapsed_ms <= config.max_runtime_ms
        assert resources.stdout_bytes + resources.stderr_bytes <= config.max_output_bytes
    print(
        f"PERF {recipe} donor_median_ms={statistics.median(donor_ms):.0f} m10_median_ms={statistics.median(m10_ms):.0f}"
    )
    assert statistics.median(m10_ms) <= statistics.median(donor_ms) + OVERHEAD_MS
