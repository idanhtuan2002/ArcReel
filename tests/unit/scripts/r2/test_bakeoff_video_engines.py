from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.r2.bakeoff_video_engines import engine_key, estimate, load_plan


def _plan(tmp_path: Path, **extra) -> Path:
    (tmp_path / "frame.png").write_bytes(b"png")
    plan = {
        "aspect_ratio": "9:16",
        "shots": [{"id": "closeup", "prompt": "Lan cười.", "start_image": "frame.png", "duration": 5}],
        "engines": [
            {"provider": "gemini-aistudio", "model": "veo-3.1-lite-generate-preview", "resolution": "720p"},
            {"provider": "ark", "model": "doubao-seedance-2-0-mini-260615"},
        ],
        **extra,
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def test_a_plan_resolves_its_start_images_and_estimates_each_engine(tmp_path: Path) -> None:
    plan = load_plan(_plan(tmp_path))

    assert plan["shots"][0]["start_image_path"] == tmp_path / "frame.png"
    rows = {row["engine"]: row for row in estimate(plan)}
    assert set(rows) == {
        "gemini-aistudio__veo-3.1-lite-generate-preview__720p",
        "ark__doubao-seedance-2-0-mini-260615",
    }
    assert all(row["estimate"] >= 0 for row in rows.values())


def test_a_plan_with_a_missing_frame_or_duplicate_ids_is_refused(tmp_path: Path) -> None:
    path = _plan(tmp_path)
    (tmp_path / "frame.png").unlink()
    with pytest.raises(SystemExit, match="start image missing"):
        load_plan(path)
    path = _plan(
        tmp_path,
        shots=[
            {"id": "a", "prompt": "x", "start_image": "frame.png"},
            {"id": "a", "prompt": "y", "start_image": "frame.png"},
        ],
    )
    with pytest.raises(SystemExit, match="unique ids"):
        load_plan(path)


def test_the_engine_key_names_provider_model_and_resolution() -> None:
    assert engine_key({"provider": "kling", "model": "kling-v3"}) == "kling__kling-v3"
    assert engine_key({"provider": "kling", "model": "kling-v3", "resolution": "1080p"}) == "kling__kling-v3__1080p"
