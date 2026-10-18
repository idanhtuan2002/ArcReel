from __future__ import annotations

import asyncio

import pytest

from server.story_authoring.prompts.drafting import (
    CRAFT_RULES,
    HARD_RULES,
    paragraph_bounds,
    render_context,
    scene_draft_prompt,
    target_syllables_for,
)
from server.story_authoring.prompts.outline import deterministic_outline_problems, outline_prompt
from server.story_authoring.prompts.packaging import unverified_selling_points
from server.story_authoring.prompts.planning import chapter_plan_prompt, entity_key, resolve_name, seed_prompt
from server.story_authoring.prompts.schemas import (
    ChapterPlan,
    OutlineChapter,
    Packaging,
    PlannedScene,
    SellingPoint,
    ShortOutline,
    StoryBibleOut,
    StorySeed,
    TitleCandidate,
)


def _outline(**overrides) -> ShortOutline:
    fields = {
        "story_arc": "Minh trở về bán nhà và tìm lại cha qua cuốn sổ.",
        "opening": "Minh về làng.",
        "confrontation": "Cuốn sổ hé lộ món nợ.",
        "resolution": "Minh giữ lại căn nhà.",
        "chapters": [
            OutlineChapter(core_task=t, threads_advanced="chính", turning_point="b")
            for t in ("Trở về", "Đọc sổ", "Quyết định")
        ],
        "ending": "Minh ở lại làng.",
        "final_image": "Cánh cổng mở.",
    }
    fields.update(overrides)
    return ShortOutline(**fields)


def _scene(**overrides) -> PlannedScene:
    fields = {
        "summary": "Minh mở cửa nhà cũ",
        "location": "Căn nhà cũ",
        "pov": "Minh",
        "characters": ["Minh", "Lan"],
        "beats": ["mở cửa", "gặp Lan"],
        "emotional_turn": "ngại ngùng sang ấm áp",
        "plot_function": "mở đầu",
        "dialogue_required": True,
    }
    fields.update(overrides)
    return PlannedScene(**fields)


def _plan(**overrides) -> ChapterPlan:
    fields = {
        "chapter_goal": "Minh về nhà",
        "reader_expectation": "Vì sao Minh bỏ đi",
        "withheld_cards": ["món nợ của cha"],
        "required_changes_by_end": ["Minh tìm thấy cuốn sổ"],
        "do_not": ["kể lại quá khứ dài dòng"],
        "scenes": [_scene(), _scene(summary="Bữa cơm"), _scene(summary="Ngăn tủ")],
    }
    fields.update(overrides)
    return ChapterPlan(**fields)


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Nguyễn Văn Minh", "nguyen-van-minh"),
        ("Đặng Thị Lan", "dang-thi-lan"),
        ("Căn nhà cũ", "can-nha-cu"),
        ("!!!", "entity"),
    ],
)
def test_entity_keys_are_folded_ascii(name, key):
    assert entity_key(name) == key


def test_entity_keys_are_made_unique():
    assert entity_key("Minh", taken={"minh", "minh-2"}) == "minh-3"


def test_names_resolve_exactly_without_diacritics_or_by_a_unique_word():
    known = {"Minh": "minh", "Lan": "lan", "Bà Tư": "ba-tu"}
    assert resolve_name("Minh", known) == "minh"
    assert resolve_name("minh", known) == "minh"
    assert resolve_name("Ba Tu", known) == "ba-tu"
    assert resolve_name("bà Tư hàng xóm", known) == "ba-tu"
    assert resolve_name("Hùng", known) is None


def test_ambiguous_word_matches_do_not_resolve():
    assert resolve_name("Anh", {"Anh Minh": "a", "Anh Tuấn": "b"}) is None


def test_a_sound_outline_has_no_deterministic_problem():
    assert deterministic_outline_problems(_outline()) == []


def test_outline_problems_are_named():
    same = [OutlineChapter(core_task="Trở về", threads_advanced="c", turning_point="b")] * 3
    problems = deterministic_outline_problems(_outline(chapters=same, ending=" "))
    assert "hai chương có cùng nhiệm vụ cốt lõi" in problems
    assert "thiếu kết thúc hoặc phần khép lại" in problems


def test_schemas_bound_list_sizes_for_the_grammar():
    schema = ShortOutline.model_json_schema()
    assert (schema["properties"]["chapters"]["minItems"], schema["properties"]["chapters"]["maxItems"]) == (3, 3)
    assert ChapterPlan.model_json_schema()["properties"]["scenes"]["maxItems"] == 5


def test_seed_and_outline_prompts_carry_the_idea_and_the_ending_rule():
    seed_text = seed_prompt(idea="Minh về làng sau 10 năm.", genre="tâm lý – gia đình")
    assert "Minh về làng sau 10 năm." in seed_text
    assert "giữ nguyên tên, tuổi, mốc thời gian" in seed_text
    seed = StorySeed.model_validate(
        {
            "working_title": "Căn nhà cũ",
            "premise": "p",
            "genre": "g",
            "tone": "t",
            "pov": "ngôi thứ ba",
            "central_conflict": "c",
            "ending_direction": "e",
            "characters": [
                {
                    "name": "Minh",
                    "role": "r",
                    "relation_to_protagonist": "chính là nhân vật chính",
                    "description": "d",
                    "goal": "g",
                },
                {"name": "Lan", "role": "r", "relation_to_protagonist": "em gái", "description": "d", "goal": "g"},
            ],
            "locations": [{"name": "Căn nhà cũ", "description": "d"}],
        }
    )
    assert "Chương 3 phải giải quyết xung đột trung tâm" in outline_prompt(seed)


def test_only_the_last_chapter_plan_carries_the_ending():
    kwargs = {
        "outline": _outline(),
        "bible": StoryBibleOut(
            logline="l", core_promise="c", world_rules=["w"], major_conflicts=["m"], forbidden_contradictions=["f"]
        ),
        "character_names": ["Minh", "Lan"],
        "location_names": ["Căn nhà cũ"],
        "previous_plans": [],
    }
    assert "Minh ở lại làng." not in chapter_plan_prompt(chapter_number=1, **kwargs)
    assert "Minh giữ lại căn nhà." not in chapter_plan_prompt(chapter_number=2, **kwargs)
    assert "Minh ở lại làng." in chapter_plan_prompt(chapter_number=3, **kwargs)
    assert "pov và characters chỉ được chọn trong: Minh, Lan" in chapter_plan_prompt(chapter_number=2, **kwargs)


def _pack():
    from server.story_authoring.narrative import (
        build_genesis_delta,
        build_plan_proposal,
        compile_scene_context,
        genesis_canon_version_id,
        provisional_canon_view,
        provisional_plan,
        provisional_readers,
        scene_contract,
        scene_refs,
    )
    from tests.integration.server.story_authoring.test_narrative import BIBLE, IDENTITY, NOW, OUTLINE

    async def build():
        delta = build_genesis_delta(IDENTITY, BIBLE, created_by="r", created_at=NOW)
        version = genesis_canon_version_id(delta)
        proposal = build_plan_proposal(IDENTITY, OUTLINE, canon_version_id=version, created_by="r", created_at=NOW)
        plan = provisional_plan(proposal, approval_ref="a", committed_by="a", committed_at=NOW)
        readers = provisional_readers(
            IDENTITY, BIBLE, canon_view=provisional_canon_view(delta), plan=plan, acceptances=[]
        )
        scene = scene_refs(OUTLINE)[0]
        return await compile_scene_context(
            readers,
            IDENTITY,
            scene,
            contract=scene_contract(proposal, scene),
            canon_version_id=version,
            plan_version=1,
            recent_decision_ids=[],
        )

    return asyncio.run(build())


def test_the_context_renders_decoded_facts_beats_and_style():
    text = render_context(_pack(), {"char-minh": "Minh", "char-lan": "Lan", "loc-nha-cu": "Căn nhà cũ"})
    assert "- Lan: Em gái Minh, ở lại làng chăm mẹ." in text
    assert "- mở cửa" in text
    assert "- Ngôi thứ ba, giọng trầm." in text
    assert "\\u" not in text


def test_paragraph_bounds_and_scene_targets():
    assert paragraph_bounds(800) == (6, 13)
    assert paragraph_bounds(300) == (4, 6)
    assert target_syllables_for([_scene()] * 3) == 1000
    assert target_syllables_for([_scene()] * 5) == 600


def test_the_final_scene_must_close_the_story_and_carry_the_rules():
    text = scene_draft_prompt(
        context="[Sự thật đã khóa]\n- Minh: con trai",
        scene=_scene(),
        plan=_plan(),
        chapter_number=3,
        scene_number=3,
        is_last_scene_of_chapter=True,
        is_final_scene=True,
        target_syllables=800,
        revision_note="Cho Lan nói nhiều hơn.",
    )
    assert "khép lại xung đột trung tâm" in text
    assert "Minh tìm thấy cuốn sổ" in text
    assert "Giữ kín, chưa hé lộ: món nợ của cha." in text
    assert "Cho Lan nói nhiều hơn." in text
    assert "móc nối" not in text
    assert all(rule in text for rule in (*HARD_RULES, *CRAFT_RULES))


def test_selling_points_need_a_verbatim_quote():
    packaging = Packaging(
        titles=[TitleCandidate(title=t, kind="k") for t in ("A", "B", "C")],
        blurbs=["b1", "b2"],
        selling_points=[
            SellingPoint(point="thật", evidence_quote="Minh  mở cửa."),
            SellingPoint(point="bịa", evidence_quote="Một câu không có."),
            SellingPoint(point="thật 2", evidence_quote="Lan cười."),
        ],
        tags=["a", "b", "c", "d", "e"],
    )
    assert unverified_selling_points(packaging, "Minh mở cửa. Lan cười.") == ["bịa"]
