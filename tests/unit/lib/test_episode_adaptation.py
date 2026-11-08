"""An episode is adapted for the screen and accepted only when its mechanical checks pass (ADR-0114)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.episode_adaptation import (
    AdaptationError,
    EpisodeAdaptationDraft,
    adaptation_mode,
    adaptation_state,
    check_adaptation,
    read_inputs,
    render_script,
    script_source_relpath,
)
from lib.episode_adaptation_runner import adapt_episode
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult

SOURCE = (
    "Sáng sớm, Lan mở cửa tiệm thuốc của cha. "
    "Một người lạ đội nón lá đứng chờ dưới hiên, tay cầm phong thư niêm sáp đỏ. "
    "Người ấy nói cha cô đã nợ một món nợ cũ và hôm nay phải trả. "
    "Lan không tin, cô lục tủ tìm sổ sách của cha. "
    "Trong sổ có một trang bị xé, chỉ còn lại tên Minh viết vội. "
    "Khi cô ngẩng lên, người lạ đã biến mất, phong thư nằm trên quầy."
)


def _project(mode: str = "narration", **extra) -> dict:
    return {
        "content_mode": mode,
        "source_language": "vi",
        "characters": {"Lan": {"description": "cô gái"}},
        "episode_adaptation": "screen",
        "episodes": [{"episode": 1, "title": "Phong thư", "hook": "Một món nợ cũ"}],
        **extra,
    }


def _write(tmp_path: Path, text: str = SOURCE) -> Path:
    (tmp_path / "source").mkdir(exist_ok=True)
    (tmp_path / "source" / "episode_1.txt").write_text(text, encoding="utf-8")
    return tmp_path


def _narration(**changes) -> dict:
    draft = {
        "logline": "Lan phải trả món nợ cũ của cha mà cô không biết.",
        "conflict": "Một người lạ đòi nợ, sổ sách của cha bị xé.",
        "cast": ["Lan"],
        "cliffhanger": "Minh là ai?",
        "scenes": [
            {
                "heading": "",
                "purpose": "người lạ đòi nợ",
                "source_excerpt": "Sáng sớm, Lan mở cửa tiệm thuốc của cha.",
                "lines": [
                    {"kind": "narration", "text": "Một người lạ đến đòi nợ."},
                    {"kind": "narration", "text": "Hắn nói cha Lan còn nợ, hôm nay phải trả."},
                ],
            },
            {
                "heading": "",
                "purpose": "manh mối Minh",
                "source_excerpt": "Khi cô ngẩng lên, người lạ đã biến mất, phong thư nằm trên quầy.",
                "lines": [
                    {"kind": "narration", "text": "Trong sổ của cha chỉ còn một cái tên: Minh."},
                    {"kind": "narration", "text": "Lan ngẩng lên, người lạ đã biến mất."},
                ],
            },
        ],
    }
    draft.update(changes)
    return draft


def _drama() -> dict:
    return {
        "logline": "Lan bị đòi một món nợ cũ.",
        "conflict": "Người lạ đòi nợ.",
        "cast": ["Lan", "Người lạ"],
        "cliffhanger": "Minh là ai?",
        "scenes": [
            {
                "heading": "Nội · Tiệm thuốc | Sáng sớm",
                "purpose": "đòi nợ",
                "source_excerpt": "Sáng sớm, Lan mở cửa tiệm thuốc của cha.",
                "lines": [
                    {"kind": "dialogue", "speaker": "Người lạ", "manner": "lạnh", "text": "Cha cô còn nợ."},
                    {"kind": "action", "text": "Lan khựng lại, tay vẫn đặt trên then cửa."},
                    {"kind": "dialogue", "speaker": "Lan", "manner": "gắt", "text": "Ông là ai mà nói vậy?"},
                    {"kind": "action", "text": "Người lạ đặt phong thư niêm sáp đỏ lên quầy, không nói thêm."},
                ],
            },
            {
                "heading": "Nội · Tiệm thuốc | Sáng",
                "purpose": "manh mối",
                "source_excerpt": "Khi cô ngẩng lên, người lạ đã biến mất, phong thư nằm trên quầy.",
                "lines": [
                    {"kind": "action", "text": "Lan lục tủ, lật cuốn sổ của cha, một trang bị xé ngang."},
                    {"kind": "dialogue", "speaker": "Lan", "manner": "thì thầm", "text": "Minh... là ai?"},
                ],
            },
        ],
    }


def test_settings_decide_whether_the_script_reads_the_adaptation():
    assert adaptation_mode(_project()) == "screen"
    assert adaptation_mode(_project(episode_adaptation=None)) == "verbatim"
    assert adaptation_mode({"content_mode": "ad", "episode_adaptation": "screen"}) == "verbatim"
    assert script_source_relpath(_project(), 3) == "adaptations/episode_3.txt"
    assert script_source_relpath(_project(episode_adaptation="verbatim"), 3) == "source/episode_3.txt"


def test_a_faithful_narration_draft_passes_and_renders_for_one_narrator(tmp_path: Path):
    inputs = read_inputs(_write(tmp_path), _project(), 1)
    draft = EpisodeAdaptationDraft.model_validate(_narration())
    assert check_adaptation(draft, inputs) == []
    script = render_script(draft, "narration")
    assert script.startswith("Một người lạ đến đòi nợ.")
    assert "##" not in script


def test_a_drama_draft_renders_as_a_scene_headed_screenplay(tmp_path: Path):
    inputs = read_inputs(_write(tmp_path), _project("drama"), 1)
    draft = EpisodeAdaptationDraft.model_validate(_drama())
    assert check_adaptation(draft, inputs) == []
    script = render_script(draft, "drama")
    assert script.startswith("## S01 | Nội · Tiệm thuốc | Sáng sớm")
    assert "Người lạ: (lạnh) Cha cô còn nợ." in script


@pytest.mark.parametrize(
    ("change", "needle"),
    [
        ({"scene": 0, "source_excerpt": "Lan bay lên trời và trở thành tiên nữ."}, "not in the episode source"),
        ({"swap": True}, "source order"),
        ({"scene": 1, "source_excerpt": "Lan không tin, cô lục tủ tìm sổ sách của cha."}, "end of the episode"),
        ({"cast": ["Lan", "Hùng"]}, "'Hùng'"),
        ({"line": {"kind": "dialogue", "speaker": "Minh", "text": "Trả nợ đi."}}, "speaker 'Minh'"),
        (
            {"hook": "Một buổi sáng sớm đầy sương mù, khi cả phố còn ngủ say, Lan lặng lẽ mở cửa tiệm thuốc."},
            "hook",
        ),
        ({"line": {"kind": "action", "text": "Lan quay đi."}}, "only narration lines"),
        ({"long": True}, "spoken length"),
        ({"hook": "陌生人来讨债。"}, "CJK"),
    ],
)
def test_each_failed_check_is_named_for_the_retry(tmp_path: Path, change: dict, needle: str):
    inputs = read_inputs(_write(tmp_path), _project(), 1)
    draft = _narration()
    if "scene" in change:
        draft["scenes"][change["scene"]]["source_excerpt"] = change["source_excerpt"]
    if change.get("swap"):
        draft["scenes"].reverse()
    if "cast" in change:
        draft["cast"] = change["cast"]
    if "line" in change:
        draft["scenes"][0]["lines"].append(change["line"])
    if "hook" in change:
        draft["scenes"][0]["lines"][0]["text"] = change["hook"]
    if change.get("long"):
        draft["scenes"][1]["lines"].append({"kind": "narration", "text": " ".join(["kể tiếp"] * 40)})
    problems = check_adaptation(EpisodeAdaptationDraft.model_validate(draft), inputs)
    assert any(needle in problem for problem in problems), problems


def test_drama_has_no_narrator_and_needs_its_scenes(tmp_path: Path):
    inputs = read_inputs(_write(tmp_path), _project("drama"), 1)
    draft = _drama()
    draft["scenes"] = draft["scenes"][:1]
    draft["scenes"][0]["lines"].append({"kind": "narration", "text": "Lan sợ hãi."})
    draft["scenes"][0]["heading"] = ""
    problems = check_adaptation(EpisodeAdaptationDraft.model_validate(draft), inputs)
    assert any("2-8 scenes" in p for p in problems)
    assert any("no narrator" in p for p in problems)
    assert any("heading" in p for p in problems)


def test_a_target_duration_bounds_the_spoken_length(tmp_path: Path):
    inputs = read_inputs(_write(tmp_path), _project(episode_target_duration=60), 1)
    assert inputs.target_seconds == 60
    problems = check_adaptation(EpisodeAdaptationDraft.model_validate(_narration()), inputs)
    assert any("between 48 and 72" in p for p in problems)


class _Model:
    def __init__(self, *answers: dict | str) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def __call__(self, request: TextGenerationRequest) -> TextGenerationResult:
        self.prompts.append(request.prompt)
        answer = self.answers.pop(0)
        text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return TextGenerationResult(text=text, provider="p", model="m")


async def test_a_failed_draft_is_asked_again_with_its_reasons_then_written(tmp_path: Path):
    project_path = _write(tmp_path)
    project = _project()
    bad = _narration(cast=["Lan", "Hùng"])
    model = _Model("not json", bad, _narration())
    assert adaptation_state(project_path, project, 1) == "missing"
    result = await adapt_episode(project_path, project, 1, generate=model)
    assert result["attempts"] == 3
    assert "not valid JSON" in model.prompts[1]
    assert "'Hùng'" in model.prompts[2]
    assert (project_path / "adaptations" / "episode_1.txt").read_text(encoding="utf-8").startswith("Một người lạ")
    record = json.loads((project_path / "adaptations" / "episode_1.json").read_text(encoding="utf-8"))
    assert record["source_relpath"] == "source/episode_1.txt"
    assert [len(a["problems"]) > 0 for a in record["attempts"]] == [True, True, False]
    assert adaptation_state(project_path, project, 1) == "current"
    (project_path / "source" / "episode_1.txt").write_text(SOURCE + " Lan đóng cửa tiệm.", encoding="utf-8")
    assert adaptation_state(project_path, project, 1) == "stale"


async def test_an_adaptation_that_never_passes_fails_without_writing(tmp_path: Path):
    project_path = _write(tmp_path)
    bad = _narration(cast=["Lan", "Hùng"])
    with pytest.raises(AdaptationError, match="after 3 attempts"):
        await adapt_episode(project_path, _project(), 1, generate=_Model(bad, bad, bad))
    assert not (project_path / "adaptations").exists()


async def test_the_prompt_carries_the_episode_plan_and_its_neighbours(tmp_path: Path):
    project_path = _write(tmp_path)
    (project_path / "source" / "episode_2.txt").write_text("Minh bước vào tiệm.", encoding="utf-8")
    project = _project(
        episodes=[
            {"episode": 1, "title": "Phong thư", "hook": "Một món nợ cũ"},
            {"episode": 2, "title": "Minh", "hook": "Người tên Minh xuất hiện"},
        ]
    )
    model = _Model(_narration())
    await adapt_episode(project_path, project, 1, generate=model)
    assert "Người tên Minh xuất hiện" in model.prompts[0]
    second = read_inputs(project_path, project, 2)
    assert second.previous_tail.endswith("phong thư nằm trên quầy.")
