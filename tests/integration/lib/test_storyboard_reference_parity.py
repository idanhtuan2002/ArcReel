"""The references a storyboard is generated with are the references its currency is planned with (ADR-0149)."""

from __future__ import annotations

import json
from pathlib import Path

from lib.artifact_planner import TargetStatePlanner
from server.services import generation_tasks


def _project(tmp_path: Path) -> tuple[Path, dict, dict]:
    root = tmp_path / "demo"
    for folder in ("characters/derivatives/Lan", "scenes", "props", "storyboards"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    for path in (
        "characters/Lan.png",
        "characters/derivatives/Lan/cuoi.png",
        "characters/Minh.png",
        "scenes/Cho.png",
        "props/Ao.png",
        "storyboards/scene_E1S01.png",
    ):
        (root / path).write_bytes(path.encode())
    project = {
        "title": "demo",
        "content_mode": "narration",
        "generation_mode": "storyboard",
        "characters": {
            "Lan": {
                "description": "d",
                "character_sheet": "characters/Lan.png",
                "derivatives": {
                    "áo cưới": {"description": "c", "character_sheet": "characters/derivatives/Lan/cuoi.png"}
                },
            },
            "Minh": {"description": "d", "character_sheet": "characters/Minh.png"},
        },
        "scenes": {"Chợ": {"description": "d", "scene_sheet": "scenes/Cho.png"}},
        "props": {"Áo": {"description": "d", "prop_sheet": "props/Ao.png"}},
    }
    (root / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    item = {
        "segment_id": "E1S02",
        "characters_in_segment": ["Lan/áo cưới", "Minh"],
        "scenes": ["Chợ"],
        "props": ["Áo"],
    }
    return root, project, item


def _shape(references) -> list[tuple[str, str | None, str | None, str]]:
    return [(r.role, r.logical_type, r.logical_id, Path(r.path).name) for r in references]


def test_execution_and_planner_assemble_the_same_references_in_the_same_order(tmp_path: Path, monkeypatch):
    root, project, item = _project(tmp_path)
    monkeypatch.setattr(generation_tasks, "artifact_input_is_usable", lambda **_kwargs: True)
    monkeypatch.setattr(generation_tasks, "build_previous_storyboard_reference", lambda path: path)
    executed: list = []
    generation_tasks._collect_reference_images(
        project,
        root,
        item,
        char_field="characters_in_segment",
        scene_field="scenes",
        prop_field="props",
        previous_storyboard_path=root / "storyboards" / "scene_E1S01.png",
        previous_storyboard_id="E1S01",
        visual_references=executed,
        artifact_episode=1,
        currency_resolver=object(),
    )

    planner = TargetStatePlanner(root)
    previous = planner._visual_reference(
        path=root / "storyboards" / "scene_E1S01.png",
        role="previous_storyboard",
        logical_type="storyboard",
        logical_id="E1S01",
    )
    planned = planner._storyboard_references(
        {**item, "products_in_shot": []},
        char_field="characters_in_segment",
        scene_field="scenes",
        prop_field="props",
        previous=previous,
    )

    assert planned is not None
    assert (
        _shape(executed)
        == _shape(planned)
        == [
            ("asset_sheet", "character", "Lan/áo cưới", "cuoi.png"),
            ("asset_sheet", "character", "Minh", "Minh.png"),
            ("previous_storyboard", "storyboard", "E1S01", "scene_E1S01.png"),
            ("asset_sheet", "scene", "Chợ", "Cho.png"),
            ("asset_sheet", "prop", "Áo", "Ao.png"),
        ]
    )
