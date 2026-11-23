"""DramaClaw's identity planner, run through ArcReel's text route and project.json (ADR-0168)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lib.identity_planning import (
    IDENTITY_DEFAULTS_FIELD,
    IDENTITY_FIELD,
    IdentityPlanningError,
    apply_identity_plan,
    derivative_description,
    plan_episode_identities,
)
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult

EPISODE_TEXT = (
    "Lan mặc áo dài lụa xanh ra bến sông đón Minh.\n\n"
    "Đêm ấy Lan nhớ lại năm lên sáu, cô bé tóc tết hai bím chạy theo cha trên đê."
)
LAN_WEDDING = "áo dài cưới đỏ thêu phượng vàng, khăn vấn đỏ, hoa tai vàng, tóc búi cao"
LAN_CHILD = "áo bà ba hoa nhí, quần lửng nâu, tóc tết hai bím buộc nơ đỏ, chân đất"
LAN_CHILD_FACE = "gương mặt bầu bĩnh của bé gái sáu tuổi, mắt to tròn, má phúng phính"


def _project(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    project_path = tmp_path / "demo"
    (project_path / "source").mkdir(parents=True)
    (project_path / "source" / "episode_1.txt").write_text(EPISODE_TEXT, encoding="utf-8")
    project: dict[str, Any] = {
        "content_mode": "drama",
        "characters": {
            "Lan": {
                "description": "Cô gái 20 tuổi, mắt đen dài\náo dài lụa xanh #2A7F7A",
                "character_sheet": "characters/Lan.png",
                "derivatives": {
                    "áo cưới": {"description": "now wears a red wedding ao dai", "character_sheet": "characters/d.png"}
                },
            },
            "Minh": {"description": "Chàng trai 22 tuổi\náo sơ mi trắng", "character_sheet": "characters/Minh.png"},
        },
        "episodes": [{"episode": 1, "title": "Bến sông"}],
    }
    return project_path, project


class FakeRoute:
    """The project's text route, answering each planner request by the schema it asks for."""

    def __init__(self, cast: list[str], defaults: list[dict[str, str]], others: list[dict[str, str]]) -> None:
        self.cast = cast
        self.defaults = defaults
        self.others = others
        self.requests: list[TextGenerationRequest] = []

    def _answer(self, schema: dict[str, Any], prompt: str) -> dict[str, Any]:
        props = set(schema.get("properties", {}))
        if props == {"character_names"}:
            return {"character_names": self.cast}
        if props == {"defaults"}:
            return {"defaults": self.defaults}
        if props == {"requirements"}:
            return {"requirements": self.others}
        if "appearance_details" in props:
            if "幼年" in prompt or "child" in prompt:
                return {
                    "appearance_details": LAN_CHILD,
                    "face_description": LAN_CHILD_FACE,
                    "age_group": "child",
                    "body_type": "dáng bé gái nhỏ nhắn",
                }
            return {"appearance_details": LAN_WEDDING, "face_description": "", "age_group": "", "body_type": ""}
        raise AssertionError(f"unexpected schema {sorted(props)}")

    async def __call__(self, request: TextGenerationRequest) -> TextGenerationResult:
        self.requests.append(request)
        assert isinstance(request.response_schema, dict)
        body = self._answer(request.response_schema, request.prompt)
        return TextGenerationResult(text=json.dumps(body, ensure_ascii=False), provider="fake", model="fake-text")


async def test_an_episode_gets_default_and_flashback_identities_as_derivatives(tmp_path: Path) -> None:
    project_path, project = _project(tmp_path)
    route = FakeRoute(
        cast=["Lan", "Minh"],
        defaults=[
            {"character_name": "Lan", "visual_state": "áo cưới", "age_group": "", "reason": "đám cưới"},
            {"character_name": "Minh", "visual_state": "thường ngày", "age_group": "", "reason": "đón Lan"},
        ],
        others=[{"character_name": "Lan", "visual_state": "幼年", "age_group": "child", "reason": "hồi tưởng"}],
    )

    plan = await plan_episode_identities(project_path, project, 1, generate=route)

    assert plan.defaults == {"Lan": "áo cưới", "Minh": "thường ngày"}
    assert sorted(plan.used) == ["Lan/áo cưới", "Lan/幼年", "Minh/thường ngày"]
    # The existing derivative is reused, not created again; only new identities are written.
    assert sorted(plan.identities["Lan"]) == ["幼年"]
    assert plan.identities["Lan"]["幼年"]["face_prompt"] == LAN_CHILD_FACE
    assert plan.identities["Lan"]["幼年"]["age_group"] == "child"
    assert all(r.response_schema for r in route.requests)

    apply_identity_plan(project, plan)

    lan = project["characters"]["Lan"]["derivatives"]
    assert lan["áo cưới"]["character_sheet"] == "characters/d.png"
    assert lan["áo cưới"]["description"] == "now wears a red wedding ao dai"
    assert lan["幼年"]["character_sheet"] == ""
    assert lan["幼年"]["description"] == derivative_description(plan.identities["Lan"]["幼年"])
    assert LAN_CHILD_FACE in lan["幼年"]["description"]
    assert lan["幼年"][IDENTITY_FIELD]["source"] == "identity_planner"
    assert project["characters"]["Minh"]["derivatives"]["thường ngày"]["description"].startswith(
        "Outfit, hair and accessories become:"
    )
    assert project["episodes"][0][IDENTITY_DEFAULTS_FIELD] == {"Lan": "áo cưới", "Minh": "thường ngày"}


async def test_a_character_without_a_default_identity_stops_the_plan(tmp_path: Path) -> None:
    project_path, project = _project(tmp_path)
    route = FakeRoute(
        cast=["Lan", "Minh"],
        defaults=[{"character_name": "Lan", "visual_state": "áo cưới", "age_group": "", "reason": "đám cưới"}],
        others=[],
    )

    with pytest.raises(IdentityPlanningError, match="Minh"):
        await plan_episode_identities(project_path, project, 1, generate=route)


async def test_an_episode_without_text_is_not_planned(tmp_path: Path) -> None:
    project_path, project = _project(tmp_path)
    (project_path / "source" / "episode_1.txt").unlink()

    with pytest.raises(IdentityPlanningError, match="no text"):
        await plan_episode_identities(project_path, project, 1, generate=FakeRoute([], [], []))
