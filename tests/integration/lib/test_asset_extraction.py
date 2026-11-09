from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.asset_extraction import AssetExtraction, AssetExtractionError, extract_asset_inventory
from lib.project_manager import ProjectManager
from lib.source_revision import SourceScope, compute_source_revision
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult

ALL = SourceScope(kind="all")


def _project(tmp_path: Path) -> tuple[ProjectManager, str]:
    pm = ProjectManager(tmp_path / "projects")
    pm.create_project("demo")
    pm.create_project_metadata("demo", "Demo", "", "narration")
    (pm.get_project_path("demo") / "source" / "story.txt").write_text(
        "Lan về làng, mang theo chiếc vòng bạc của mẹ.", encoding="utf-8"
    )
    return pm, compute_source_revision(pm.get_project_path("demo"), pm.load_project("demo"), ALL).revision or ""


def _answer(payload: object):
    seen: list[TextGenerationRequest] = []

    async def generate(request: TextGenerationRequest) -> TextGenerationResult:
        seen.append(request)
        return TextGenerationResult(
            text=payload if isinstance(payload, str) else json.dumps(payload), provider="fake", model="fake"
        )

    return generate, seen


EXTRACTED = {
    "characters": [{"name": "Lan", "description": "Cô gái gầy, tóc dài, áo bà ba nâu.", "voice_style": "nhỏ nhẹ"}],
    "scenes": [{"name": "Làng ven sông", "description": "Đường đất, hàng tre, ánh chiều vàng."}],
    "props": [{"name": "Vòng bạc", "description": "Chiếc vòng bạc mảnh, xỉn màu."}],
}


async def test_extraction_completes_the_inventory_against_the_read_revision(tmp_path: Path):
    pm, revision = _project(tmp_path)
    generate, seen = _answer(EXTRACTED)

    completed = await extract_asset_inventory(
        pm, "demo", scope=ALL, expected_source_revision=revision, generate=generate
    )

    project = pm.load_project("demo")
    assert completed.counts == {"characters": 1, "scenes": 1, "props": 1}
    assert project["characters"]["Lan"]["voice_style"] == "nhỏ nhẹ"
    assert project["workflow"]["asset_inventory"]["source_revision"] == revision
    assert seen[0].response_schema is AssetExtraction
    assert "chiếc vòng bạc" in seen[0].prompt


async def test_registered_names_are_kept_and_never_overwritten(tmp_path: Path):
    pm, revision = _project(tmp_path)

    def register(project: dict) -> None:
        project["characters"] = {"Lan": {"description": "Bản người dùng sửa", "character_sheet": ""}}

    pm.update_project("demo", register)
    generate, _ = _answer(EXTRACTED)

    await extract_asset_inventory(pm, "demo", scope=ALL, expected_source_revision=revision, generate=generate)

    assert pm.load_project("demo")["characters"]["Lan"]["description"] == "Bản người dùng sửa"


@pytest.mark.parametrize(
    "answer",
    [
        "not json",
        {"characters": [], "scenes": [], "props": []},
        {"characters": [{"name": "Lan"}], "scenes": [], "props": []},
        {**EXTRACTED, "extra": []},
    ],
)
async def test_empty_or_malformed_extraction_never_completes(tmp_path: Path, answer):
    pm, revision = _project(tmp_path)
    generate, _ = _answer(answer)

    with pytest.raises(AssetExtractionError):
        await extract_asset_inventory(pm, "demo", scope=ALL, expected_source_revision=revision, generate=generate)

    assert "workflow" not in pm.load_project("demo")


async def test_a_moved_source_is_refused_before_any_model_call(tmp_path: Path):
    pm, revision = _project(tmp_path)
    (pm.get_project_path("demo") / "source" / "story.txt").write_text("Văn bản khác.", encoding="utf-8")
    generate, seen = _answer(EXTRACTED)

    with pytest.raises(AssetExtractionError, match="changed"):
        await extract_asset_inventory(pm, "demo", scope=ALL, expected_source_revision=revision, generate=generate)

    assert seen == []


async def test_a_character_the_source_never_names_is_not_registered(tmp_path: Path):
    pm, revision = _project(tmp_path)
    invented = {**EXTRACTED, "characters": [*EXTRACTED["characters"], {"name": "Hùng", "description": "Chàng trai."}]}
    generate, _ = _answer(invented)

    completed = await extract_asset_inventory(
        pm, "demo", scope=ALL, expected_source_revision=revision, generate=generate
    )

    assert completed.counts["characters"] == 1
    assert set(pm.load_project("demo")["characters"]) == {"Lan"}
