"""Native episode renderer against the installed FFmpeg with generated real media."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.presentation_renderer import (
    RenderContract,
    RenderCue,
    RenderInput,
    RenderRefused,
    RenderUnit,
    render_presentations,
    sha256_file,
)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required")
CONTRACT = RenderContract(width=576, height=1024, fps=24, min_seconds=1, max_seconds=60)


def _media(path: Path, *inputs: str, seconds: float) -> Path:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", *inputs, "-t", str(seconds), str(path)], check=True
    )
    return path


@pytest.fixture
def clips(tmp_path: Path) -> dict[str, Path]:
    return {
        "video": _media(tmp_path / "unit.mp4", "-f", "lavfi", "-i", "testsrc=size=832x480:rate=16", seconds=3),
        "voice": _media(tmp_path / "voice.wav", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=24000", seconds=2),
        "long_voice": _media(tmp_path / "long.wav", "-f", "lavfi", "-i", "sine=frequency=440", seconds=4),
        "silence": _media(tmp_path / "silence.wav", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", seconds=2),
    }


def _unit(clips, *, narration: str | None = "voice", cue: bool = True, start: int = 500_000, length: int = 2_000_000):
    return RenderUnit(
        unit_id="u",
        video_path=clips["video"],
        video_start_us=0,
        duration_us=3_000_000,
        video_audio=False,
        video_gain=1.0,
        narration_path=clips[narration] if narration else None,
        narration_start_us=start,
        narration_duration_us=length,
        cues=(RenderCue(500_000, 2_500_000, "Lan về làng."),) if cue else (),
    )


def test_renderer_preserves_exact_input_media(clips, tmp_path: Path):
    source_hashes_before = {name: sha256_file(path) for name, path in clips.items()}
    episode = RenderInput(episode=1, units=(_unit(clips), _unit(clips, narration=None)))

    receipt = render_presentations(episode=episode, output_dir=tmp_path / "out", contract=CONTRACT)

    source_hashes_after = {name: sha256_file(path) for name, path in clips.items()}
    assert source_hashes_after == source_hashes_before
    assert receipt.final_sha256 == sha256_file(receipt.final_path)
    assert abs(receipt.duration_seconds - 6.0) <= 0.12
    probe = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,width,height",
                "-of",
                "json",
                str(receipt.final_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert {s["codec_name"] for s in probe["streams"]} == {"h264", "aac"}
    assert {(s.get("width"), s.get("height")) for s in probe["streams"] if s.get("width")} == {(576, 1024)}
    assert "00:00:00,500 --> 00:00:02,500\nLan về làng." in receipt.subtitle_path.read_text(encoding="utf-8")
    assert "00:00:03,500 --> 00:00:05,500" in receipt.subtitle_path.read_text(encoding="utf-8")
    manifest = json.loads(receipt.manifest_path.read_text(encoding="utf-8"))
    assert manifest["units"][0]["video"]["sha256"] == source_hashes_before["video"]
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "episode_1.manifest.json",
        "episode_1.mp4",
        "episode_1.srt",
    ]


@pytest.mark.parametrize(
    ("unit", "code"),
    [
        ({"narration": "long_voice", "length": 4_000_000}, "NARRATION_EXCEEDS_UNIT"),
        ({"start": 1_500_000}, "NARRATION_EXCEEDS_UNIT"),
        ({"narration": None}, "NARRATION_MISSING"),
        ({"cue": False}, "SUBTITLES_MISSING"),
    ],
)
def test_a_film_missing_or_overrunning_its_speech_is_refused_before_rendering(clips, tmp_path: Path, unit, code):
    with pytest.raises(RenderRefused) as refused:
        render_presentations(
            episode=RenderInput(episode=1, units=(_unit(clips, **unit),)),
            output_dir=tmp_path / "out",
            contract=CONTRACT,
        )
    assert refused.value.code == code
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_silent_narration_never_produces_a_final(clips, tmp_path: Path):
    with pytest.raises(RenderRefused) as refused:
        render_presentations(
            episode=RenderInput(episode=1, units=(_unit(clips, narration="silence"),)),
            output_dir=tmp_path / "out",
            contract=CONTRACT,
        )
    assert refused.value.code == "NARRATION_INAUDIBLE"
    assert list((tmp_path / "out").iterdir()) == []


def test_a_duration_outside_the_contract_is_refused(clips, tmp_path: Path):
    contract = RenderContract(width=576, height=1024, fps=24, min_seconds=30, max_seconds=60)
    with pytest.raises(RenderRefused, match="DURATION_OUTSIDE_CONTRACT"):
        render_presentations(
            episode=RenderInput(episode=1, units=(_unit(clips),)), output_dir=tmp_path / "out", contract=contract
        )


def test_the_final_is_mastered_to_the_contract_loudness(clips, tmp_path: Path):
    quiet = _media(
        tmp_path / "quiet.wav",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=300:sample_rate=24000",
        "-af",
        "volume=-30dB",
        seconds=2,
    )
    unit = _unit({**clips, "voice": quiet})
    episode = RenderInput(episode=1, units=(unit, unit, unit))

    receipt = render_presentations(episode=episode, output_dir=tmp_path / "out", contract=CONTRACT)

    loudness = json.loads(receipt.manifest_path.read_text(encoding="utf-8"))["loudness"]
    assert loudness["input_lufs"] < -35
    assert abs(loudness["output_lufs"] - CONTRACT.loudness_lufs) <= 1.0
    assert loudness["output_true_peak_db"] <= CONTRACT.true_peak_db + 0.5
    assert abs(receipt.duration_seconds - 9.0) <= 0.12


def test_a_contract_without_a_loudness_target_keeps_the_mix(clips, tmp_path: Path):
    contract = RenderContract(width=576, height=1024, fps=24, min_seconds=1, max_seconds=60, loudness_lufs=None)

    receipt = render_presentations(
        episode=RenderInput(episode=1, units=(_unit(clips),)), output_dir=tmp_path / "out", contract=contract
    )

    assert json.loads(receipt.manifest_path.read_text(encoding="utf-8"))["loudness"] is None


def _frame_md5(path: Path, index: int) -> str:
    return subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"select=eq(n\\,{index})",
            "-frames:v",
            "1",
            "-f",
            "md5",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_a_held_picture_gets_its_camera_move_and_a_moving_clip_keeps_its_own(clips, tmp_path: Path):
    still = _media(
        tmp_path / "still.mp4",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=576x1024:rate=24",
        "-vf",
        "trim=end_frame=1,loop=loop=-1:size=1",
        seconds=3,
    )
    held = RenderUnit(**{**_unit(clips).__dict__, "unit_id": "held", "video_path": still, "motion": "push_in"})
    moving = RenderUnit(**{**_unit(clips).__dict__, "unit_id": "moving", "motion": "pan_left"})

    receipt = render_presentations(
        episode=RenderInput(episode=1, units=(held, moving)), output_dir=tmp_path / "out", contract=CONTRACT
    )

    units = json.loads(receipt.manifest_path.read_text(encoding="utf-8"))["units"]
    assert [unit["motion"] for unit in units] == ["push_in", None]
    assert _frame_md5(receipt.final_path, 0) != _frame_md5(receipt.final_path, 60)
    assert abs(receipt.duration_seconds - 6.0) <= 0.12


def test_the_film_grade_is_applied_and_recorded(clips, tmp_path: Path):
    plain = render_presentations(
        episode=RenderInput(episode=1, units=(_unit(clips),)), output_dir=tmp_path / "plain", contract=CONTRACT
    )
    graded = render_presentations(
        episode=RenderInput(episode=1, units=(_unit(clips),), grade="cinematic_warm", grade_intensity=0.7),
        output_dir=tmp_path / "graded",
        contract=CONTRACT,
    )

    manifest = json.loads(graded.manifest_path.read_text(encoding="utf-8"))
    assert manifest["grade"] == {"name": "cinematic_warm", "intensity": 0.7}
    assert _frame_md5(graded.final_path, 10) != _frame_md5(plain.final_path, 10)
    assert abs(graded.duration_seconds - 3.0) <= 0.12


@pytest.mark.parametrize(
    ("episode_fields", "unit_fields", "code"),
    [({"grade": "sepia"}, {}, "UNKNOWN_GRADE"), ({}, {"motion": "whip_pan"}, "UNKNOWN_MOTION")],
)
def test_an_unknown_grade_or_move_is_refused(clips, tmp_path: Path, episode_fields, unit_fields, code):
    unit = RenderUnit(**{**_unit(clips).__dict__, **unit_fields})
    with pytest.raises(RenderRefused) as refused:
        render_presentations(
            episode=RenderInput(episode=1, units=(unit,), **episode_fields),
            output_dir=tmp_path / "o",
            contract=CONTRACT,
        )
    assert refused.value.code == code
