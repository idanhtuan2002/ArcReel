"""Same-fixture differential parity of M8-E format projection against pinned OpenMontage (spec §11).

The donor's ``VideoCompose`` reframes with ``metadata.compose_target`` ``fit="pad"`` / ``"cover"``.
R2's ``PAD`` / ``COVER_CENTER`` plans render the same lavfi fixture to the same three targets. Each
case is measured on both sides: dimensions, codec, duration, mid-frame PSNR between the two outputs,
audio presence, byte-determinism over two runs, wall time and output size. Thresholds were fixed
before measuring: PSNR >= 30 dB, duration within one frame, R2 median time <= 3x donor, R2 output
<= 2x donor bytes. The donor runs unmodified in its own clone and environment.

    uv run python scripts/r2/check_m8e_format_parity.py --donor-clone ~/.cache/r2-donors/openmontage \\
        --work /tmp/m8e-parity --head <sha> --report docs/r2/evidence/R2_M8_E_FORMAT_PARITY.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

from r2.advanced_creative.digests import digest_canonical
from r2.advanced_creative.format_render import ADAPTER_VERSION, materialize, pixel_geometry, render_argv
from r2.advanced_creative.formats import ReframeKind, build_plan, reframe_decision
from r2.contracts.advanced_creative import OutputProfile, OverlayConstraintSet
from scripts.r2.verify_donor_parity import clone_file_hashes

DONOR_URL = "https://github.com/calesthio/OpenMontage"
DONOR_COMMIT = "08e2151fa02de28a5d6a312b3d575692bf147ad7"
SELECTED = ("tools/video/video_compose.py", "tests/tools/test_video_compose_vertical.py")
DONOR_TESTS = ("tests/tools/test_video_compose_vertical.py",)
TARGETS = ((1920, 1080), (1080, 1920), (1080, 1080))
DONOR_ENV = [
    "uv",
    "run",
    "--no-project",
    "--python",
    "3.12",
    "--with",
    "pytest",
    "--with",
    "pyyaml",
    "--with",
    "pydantic>=2",
    "--with",
    "jsonschema",
    "--with",
    "python-dotenv",
    "--with",
    "pillow",
    "--with",
    "numpy",
    "--with",
    "requests",
    "--",
]
IMPLEMENTATION = ("r2/advanced_creative/format_render.py", "r2/advanced_creative/formats.py")
HARNESS = "scripts/r2/check_m8e_format_parity.py"
PSNR_MIN = 30.0
TIME_FACTOR = 3.0
SIZE_FACTOR = 2.0
RUNS = 3

_DONOR_RUNNER = """
import json, sys
from tools.video.video_compose import VideoCompose
src, out, w, h, fit = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
r = VideoCompose().execute({"operation": "compose", "output_path": out, "edit_decisions": {
    "version": "1.0", "render_runtime": "ffmpeg",
    "cuts": [{"id": "c1", "source": src, "in_seconds": 0, "out_seconds": 2}],
    "metadata": {"compose_target": {"width": w, "height": h, "fit": fit}}}})
print(json.dumps({"success": bool(r.success), "error": r.error}))
"""


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)


def probe(path: Path) -> dict:
    result = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    return json.loads(result.stdout or "{}")


def facts(path: Path) -> dict:
    data = probe(path)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    return {
        "width": video["width"],
        "height": video["height"],
        "codec": video["codec_name"],
        "fps": str(Fraction(video["r_frame_rate"])),
        "duration": float(data["format"]["duration"]),
        "audio": [s["codec_name"] for s in data["streams"] if s["codec_type"] == "audio"],
        "bytes": path.stat().st_size,
    }


def mid_frame_psnr(a: Path, b: Path) -> float:
    result = run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "info",
            "-ss",
            "1",
            "-i",
            str(a),
            "-ss",
            "1",
            "-i",
            str(b),
            "-frames:v",
            "1",
            "-lavfi",
            "[0:v][1:v]psnr",
            "-f",
            "null",
            "-",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"psnr exited {result.returncode}")
    marker = "average:"
    line = next((part for part in result.stderr.split() if part.startswith(marker)), None)
    if line is None:
        raise RuntimeError("psnr not reported: " + result.stderr[-400:])
    value = line.removeprefix(marker)
    return 99.0 if value == "inf" else float(value)


def decode_errors(path: Path) -> int:
    result = run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-f", "null", "-"])
    return len([line for line in result.stderr.splitlines() if line.strip()]) + (0 if result.returncode == 0 else 1)


def donor_crop_x(width: int, height: int) -> int:
    """The donor's cover crop of a 1280x720 source: scale to fill, then centre-crop (in source pixels)."""
    scale = max(Fraction(width, 1280), Fraction(height, 720))
    kept = Fraction(width) / scale
    return int((1280 - kept) / 2)


def make_fixture(path: Path) -> None:
    run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=1280x720:d=2:r=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "1",
            "-g",
            "30",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ]
    ).check_returncode()


def donor_render(clone: Path, source: Path, out: Path, width: int, height: int, fit: str) -> tuple[bool, float, str]:
    started = time.perf_counter()
    result = run(
        [*DONOR_ENV, "python", "-c", _DONOR_RUNNER, str(source), str(out), str(width), str(height), fit], cwd=clone
    )
    elapsed = time.perf_counter() - started
    last = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    try:
        verdict = json.loads(last)
    except ValueError:
        verdict = {}
    ok = result.returncode == 0 and verdict.get("success") is True
    return ok and out.exists(), elapsed, str(verdict.get("error") or result.stderr[-200:])


def r2_plan(width: int, height: int, kind: ReframeKind, source_digest: str):
    from datetime import UTC, datetime

    profile = OutputProfile(
        profile_ref=f"parity-{width}x{height}",
        platform="parity",
        surface="parity",
        width=width,
        height=height,
        fps=Fraction(30),
        duration_limit_seconds=None,
        container="mp4",
        video_codec="h264",
        audio_codec="aac",
        source_refs=("parity-fixture",),
        effective_at=datetime(2026, 10, 14, tzinfo=UTC),
    )
    overlay = OverlayConstraintSet(
        constraint_ref="parity-none",
        platform="parity",
        surface="parity",
        locale="und",
        ui_variant="none",
        regions=(),
        source_refs=("parity-fixture",),
        effective_at=datetime(2026, 10, 14, tzinfo=UTC),
    )
    decision = reframe_decision(
        decision_id="r", kind=kind, source_size=(1280, 720), profile=profile, focal=None, rationale="parity fixture"
    )
    return build_plan(
        plan_id=f"parity-{width}x{height}-{kind}",
        source_master_id="fixture",
        source_master_digest=source_digest,
        profile=profile,
        overlay=overlay,
        decisions=(decision,),
    )


def r2_render(plan, source: Path, out: Path) -> tuple[bool, float, str]:
    argv = materialize(
        render_argv(plan, source_width=1280, source_height=720, has_audio=True), source=str(source), output=str(out)
    )
    started = time.perf_counter()
    result = run(argv)
    return result.returncode == 0 and out.exists(), time.perf_counter() - started, result.stderr[-200:]


def disposition(ok: bool, improved: bool = False) -> str:
    """PARITY or IMPROVED when the measurement meets its threshold; EXCLUDED (which blocks) otherwise."""
    return "IMPROVED" if improved and ok else ("PARITY" if ok else "EXCLUDED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--donor-clone", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    clone, work = args.donor_clone.expanduser(), args.work
    work.mkdir(parents=True, exist_ok=True)
    head = run(["git", "rev-parse", "HEAD"], cwd=clone).stdout.strip()
    if head != DONOR_COMMIT:
        raise SystemExit(f"donor clone is at {head}, not the pinned {DONOR_COMMIT}")
    if run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=clone).stdout.strip():
        raise SystemExit("the donor clone has modified tracked files; the run would not be the pinned donor")
    repo = Path(__file__).resolve().parents[2]
    r2_head = run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    if r2_head != args.head:
        raise SystemExit(f"R2 HEAD is {r2_head}, not --head {args.head}")
    dirty = run(["git", "status", "--porcelain", "--", *IMPLEMENTATION, HARNESS], cwd=repo).stdout.strip()
    if dirty:
        raise SystemExit("the executed R2 implementation or harness differs from HEAD")

    commands: list[dict] = [
        {
            "command": "executed R2 files at HEAD",
            "head": args.head,
            "digests": {path: sha256_file(repo / path) for path in (*IMPLEMENTATION, HARNESS)},
        }
    ]
    donor_tests = run([*DONOR_ENV, "python", "-m", "pytest", *DONOR_TESTS, "-q", "-p", "no:cacheprovider"], cwd=clone)
    donor_tests_tail = (
        donor_tests.stdout.strip().splitlines()[-1] if donor_tests.stdout.strip() else donor_tests.stderr[-200:]
    )
    commands.append(
        {"command": "donor pytest " + " ".join(DONOR_TESTS), "exit": donor_tests.returncode, "result": donor_tests_tail}
    )

    source = work / "fixture.mp4"
    make_fixture(source)
    source_digest = sha256_file(source)
    # Failure safety and observability: both sides refuse a missing source, produce no output, and say why.
    missing = work / "missing.mp4"
    donor_ok, _t, donor_error = donor_render(clone, missing, work / "donor-missing.mp4", 1080, 1080, "pad")
    r2_ok, _t, r2_error = r2_render(
        r2_plan(1080, 1080, ReframeKind.PAD, source_digest), missing, work / "r2-missing.mp4"
    )
    failure_safe = not donor_ok and not r2_ok and not (work / "r2-missing.mp4").exists()
    observable = bool(donor_error.strip()) and "No such file" in r2_error
    rows: list[dict] = []
    measures: dict[str, dict] = {}
    unknowns: list[str] = []
    for index, (fit, kind) in enumerate((("pad", ReframeKind.PAD), ("cover", ReframeKind.COVER_CENTER))):
        for target_index, (width, height) in enumerate(TARGETS):
            case = f"{fit}-{width}x{height}"
            behavior = f"F{index * len(TARGETS) + target_index + 1:02d}"
            plan = r2_plan(width, height, kind, source_digest)
            donor_times, r2_times, donor_hashes, r2_hashes = [], [], [], []
            donor_ok = r2_ok = True
            for attempt in range(RUNS):
                donor_out, r2_out = work / f"donor-{case}-{attempt}.mp4", work / f"r2-{case}-{attempt}.mp4"
                for stale in (donor_out, r2_out):
                    stale.unlink(missing_ok=True)
                ok, elapsed, _error = donor_render(clone, source, donor_out, width, height, fit)
                donor_ok &= ok
                donor_times.append(elapsed)
                ok, elapsed, _error = r2_render(plan, source, r2_out)
                r2_ok &= ok
                r2_times.append(elapsed)
                if donor_out.exists():
                    donor_hashes.append(sha256_file(donor_out))
                if r2_out.exists():
                    r2_hashes.append(sha256_file(r2_out))
            if not (donor_ok and r2_ok):
                unknowns.append(f"{case}: donor ok={donor_ok}, r2 ok={r2_ok}")
                continue
            donor_facts, r2_facts = facts(work / f"donor-{case}-0.mp4"), facts(work / f"r2-{case}-0.mp4")
            psnr = mid_frame_psnr(work / f"donor-{case}-0.mp4", work / f"r2-{case}-0.mp4")
            # The donor's own frame timing defines the comparison window; one frame of 30 fps tolerance.
            same_shape = (
                (donor_facts["width"], donor_facts["height"], donor_facts["codec"])
                == (r2_facts["width"], r2_facts["height"], r2_facts["codec"])
                == (width, height, "h264")
            )
            duration_ok = abs(donor_facts["duration"] - r2_facts["duration"]) <= 1 / 30 + 1e-6
            fps_ok = donor_facts["fps"] == r2_facts["fps"] == "30"
            decode_ok = decode_errors(work / f"donor-{case}-0.mp4") == 0 == decode_errors(work / f"r2-{case}-0.mp4")
            geometry = pixel_geometry(plan, source_width=1280, source_height=720)
            geometry_ok = kind is ReframeKind.PAD or abs(geometry.crop_x - donor_crop_x(width, height)) <= 2
            r2_deterministic = len(set(r2_hashes)) == 1
            donor_deterministic = len(set(donor_hashes)) == 1
            audio_kept = r2_facts["audio"] == ["aac"]
            time_ok = statistics.median(r2_times) <= TIME_FACTOR * statistics.median(donor_times)
            size_ok = r2_facts["bytes"] <= SIZE_FACTOR * donor_facts["bytes"]
            measures[case] = {
                "donor": donor_facts,
                "r2": r2_facts,
                "psnr_db": round(psnr, 2),
                "donor_median_s": round(statistics.median(donor_times), 3),
                "r2_median_s": round(statistics.median(r2_times), 3),
                "donor_deterministic": donor_deterministic,
                "r2_deterministic": r2_deterministic,
                "r2_sha256": r2_hashes[0],
                "fps_ok": fps_ok,
                "decode_ok": decode_ok,
                "r2_crop_x": geometry.crop_x,
                "donor_crop_x": donor_crop_x(width, height) if kind is ReframeKind.COVER_CENTER else None,
            }
            rows.append(
                {
                    "behavior_id": behavior,
                    "donor_test_refs": list(DONOR_TESTS) if fit == "cover" or width < height else [],
                    "fixture_refs": [f"fixture:{source_digest}", f"case:{case}"],
                    "intentional_difference": None,
                    "functionality": disposition(same_shape and fps_ok),
                    "correctness": disposition(psnr >= PSNR_MIN and duration_ok and decode_ok and geometry_ok),
                    "determinism": disposition(r2_deterministic, improved=not donor_deterministic),
                    "failure_safety": disposition(failure_safe),
                    "data_integrity": disposition(audio_kept, improved=donor_facts["audio"] != ["aac"]),
                    "observability": disposition(observable),
                    "performance": disposition(time_ok),
                    "resources": disposition(size_ok),
                    "evidence_refs": [f"measure:{case}"],
                }
            )

    rows.append(
        {
            "behavior_id": "F07",
            "donor_test_refs": [],
            "fixture_refs": ["case:missing-source"],
            "intentional_difference": None,
            **dict.fromkeys(
                (
                    "functionality",
                    "correctness",
                    "determinism",
                    "failure_safety",
                    "data_integrity",
                    "observability",
                    "performance",
                    "resources",
                ),
                disposition(failure_safe and observable),
            ),
            "evidence_refs": ["measure:missing-source"],
        }
    )
    if not (failure_safe and observable):
        unknowns.append("missing-source: a side did not refuse cleanly with a reason")
    measures["missing-source"] = {
        "donor_refused": not donor_ok,
        "r2_refused": not r2_ok,
        "donor_reason": donor_error.strip()[:160],
        "r2_reason_names_missing_file": "No such file" in r2_error,
    }

    file_hashes = clone_file_hashes(clone, DONOR_COMMIT, SELECTED)
    if donor_tests.returncode != 0:
        unknowns.append("donor tests did not pass unmodified")
    report = {
        "contract_version": "1",
        "donor": {
            "repository_url": DONOR_URL,
            "commit_sha": DONOR_COMMIT,
            "selected_paths": list(SELECTED),
            "reachable_surface_digest": digest_canonical({path: file_hashes[path] for path in SELECTED}),
            "runtime_identity": run(["ffmpeg", "-version"]).stdout.splitlines()[0] + f"; r2 {ADAPTER_VERSION}",
            "behavior_inventory_digest": digest_canonical(sorted(row["behavior_id"] for row in rows)),
            "donor_test_inventory_digest": digest_canonical(list(DONOR_TESTS)),
            "fixture_set_digest": digest_canonical({"fixture": source_digest, "targets": [list(t) for t in TARGETS]}),
        },
        "integrated_head": args.head,
        "rows": rows,
        "commands": commands,
        "required_skips": [],
        "material_unknowns": unknowns,
        "reviewer": "pending independent review",
        "verdict": "BLOCKED",
    }
    from r2.advanced_creative.parity import evaluate_parity
    from r2.contracts.advanced_creative import DonorParityReport

    report["verdict"] = evaluate_parity(DonorParityReport.model_validate(report), args.head).value
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.report.parent / (args.report.stem + "_MEASURES.json")).write_text(
        json.dumps(measures, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"verdict": report["verdict"], "unknowns": unknowns, "rows": len(rows)}))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
