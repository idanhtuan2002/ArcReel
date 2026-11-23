"""Drama script planning plans the episode's character identities first (ADR-0168)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.identity_planning import IDENTITY_DEFAULTS_FIELD
from lib.project_manager import ProjectManager
from lib.text_backends.base import TextGenerationResult
from server import text_generation as mod
from tests.fakes import FakeConfigResolver

EPISODE_TEXT = "Lan mặc áo cưới đỏ bước ra bến sông. Lan: Anh đến rồi à?"


def _project(root: Path) -> ProjectManager:
    project_path = root / "demo"
    (project_path / "source").mkdir(parents=True)
    (project_path / "source" / "episode_1.txt").write_text(EPISODE_TEXT, encoding="utf-8")
    project = {
        "title": "demo",
        "content_mode": "drama",
        "generation_mode": "storyboard",
        "style": "",
        "characters": {"Lan": {"description": "Cô gái 20 tuổi\náo dài xanh", "character_sheet": ""}},
        "scenes": {},
        "props": {},
        "episodes": [{"episode": 1, "title": "Bến sông", "script_file": "scripts/episode_1.json"}],
    }
    (project_path / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    return ProjectManager(str(root))


class _Route:
    """Answers DramaClaw's planner by its schema, then the script request."""

    def __init__(self) -> None:
        self.script_prompts: list[str] = []

    async def generate(self, request: Any, **_kwargs: Any) -> TextGenerationResult:
        schema = request.response_schema
        if isinstance(schema, dict):
            props = set(schema.get("properties", {}))
            if props == {"character_names"}:
                body: dict[str, Any] = {"character_names": ["Lan"]}
            elif props == {"defaults"}:
                body = {"defaults": [{"character_name": "Lan", "visual_state": "áo cưới", "reason": "đám cưới"}]}
            elif props == {"requirements"}:
                body = {"requirements": []}
            else:
                body = {
                    "appearance_details": "áo dài cưới đỏ thêu phượng vàng, khăn vấn đỏ, hoa tai vàng, tóc búi cao",
                    "face_description": "",
                    "age_group": "",
                    "body_type": "",
                }
            return TextGenerationResult(text=json.dumps(body, ensure_ascii=False), provider="fake", model="fake")
        self.script_prompts.append(request.prompt)
        scene = {
            "scene_id": "E1S01",
            "duration_seconds": 4,
            "segment_break": False,
            "characters_in_scene": ["Lan"],
            "scenes": [],
            "props": [],
            "scene_description": "Lan bước ra bến sông.",
            "utterances": [{"kind": "dialogue", "speaker": "Lan", "text": "Anh đến rồi à?"}],
            "source_text": EPISODE_TEXT,
        }
        return TextGenerationResult(
            text=json.dumps({"title": "Bến sông", "scenes": [scene]}, ensure_ascii=False), provider="fake", model="fake"
        )


async def test_the_episode_gets_its_identities_and_shots_name_the_default_look(tmp_path: Path, monkeypatch) -> None:
    projects = _project(tmp_path)
    route = _Route()

    async def create(_task_type: Any, **_kwargs: Any) -> _Route:
        return route

    monkeypatch.setattr(mod.TextGenerator, "create", create)

    await mod.generate_drama_script_plan(
        mod.TextGenerationRequest(episode=1, source="source/episode_1.txt"),
        project_name="demo",
        projects=projects,
        config_resolver=FakeConfigResolver(supported_durations=(4, 6, 8), default_duration=4),
    )

    project = projects.load_project("demo")
    lan = project["characters"]["Lan"]
    assert lan["derivatives"]["áo cưới"]["description"].startswith("Outfit, hair and accessories become:")
    assert project["episodes"][0][IDENTITY_DEFAULTS_FIELD] == {"Lan": "áo cưới"}
    assert "Lan → Lan/áo cưới" in route.script_prompts[0]
    plan = json.loads((tmp_path / "demo/drafts/episode_1/script_plan_normalized_script.json").read_text("utf-8"))
    assert plan["scenes"][0]["characters_in_scene"] == ["Lan/áo cưới"]
    assert plan["scenes"][0]["utterances"][0]["speaker"] == "Lan"
