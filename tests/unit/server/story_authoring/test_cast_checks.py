from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.story_authoring.book import bound_book_outline, bound_seed
from server.story_authoring.cast_checks import gender_findings
from server.story_authoring.checks import Severity
from server.story_authoring.prompts.schemas import SeedCharacter

MINH = SeedCharacter(
    name="Minh",
    role="chính",
    relation_to_protagonist="chính là nhân vật chính",
    description="họa sĩ nghèo",
    goal="nổi tiếng",
    gender="nam",
    address="anh",
)
LAN = SeedCharacter(
    name="Lan",
    role="phụ",
    relation_to_protagonist="hồn ma",
    description="người vợ đã mất",
    goal="siêu thoát",
    gender="nữ",
    address="cô",
)

DRIFTED = (
    "Minh quay lưng lại cửa sổ và bước đi vững chắc hơn bao giờ hết. Cô biết rằng đây là điểm khởi đầu của một kỷ "
    "nguyên mới.\n\n"
    "Minh đứng lặng khi nhận ra Lan chỉ còn là một ảo giác. Cô ấy mờ dần theo từng nhịp thở.\n\n"
    "Minh bước ra khỏi nhà trọ. Anh không quay đầu lại.\n\n"
    "Minh nói: “Cô đi đi.” Rồi Minh khóc."
)


def test_a_male_character_called_by_a_female_word_in_narration_is_a_repairable_finding():
    [finding] = gender_findings([MINH, LAN], [("scene[1,1]", DRIFTED)])
    assert (finding.code, finding.severity, finding.node_id) == (
        "CAST_GENDER",
        Severity.NARRATIVE_CRITICAL,
        "scene[1,1]",
    )
    assert finding.quote == "Cô biết rằng đây là điểm khởi đầu của một kỷ nguyên mới."
    assert finding.quote in DRIFTED
    assert "Minh là nam" in finding.message


def test_mixed_paragraphs_dialogue_and_characters_without_a_gender_are_left_alone():
    assert gender_findings([MINH, LAN], [("s", "Minh nhìn Lan. Cô cúi đầu.")]) == ()
    assert gender_findings([MINH], [("s", "Minh nói: “Cô về đi.”\n— Cô là ai?")]) == ()
    unknown = MINH.model_copy(update={"gender": None})
    assert gender_findings([unknown], [("s", DRIFTED)]) == ()
    female = LAN.model_copy(update={"name": "Hoa"})
    [finding] = gender_findings([female], [("s", "Hoa đứng dậy. Anh ta lặng lẽ đi ra.")])
    assert finding.quote == "Anh ta lặng lẽ đi ra."


def test_a_generated_seed_and_a_volumes_new_characters_state_gender_and_address_and_lock_them():
    seed = bound_seed(5, 4)
    character = {"name": "Minh", "role": "r", "relation_to_protagonist": "x", "description": "d", "goal": "g"}
    base = {
        "working_title": "t",
        "premise": "p",
        "genre": "g",
        "tone": "t",
        "pov": "p",
        "central_conflict": "c",
        "ending_direction": "e",
        "locations": [{"name": "Nhà", "description": "d"}],
    }
    with pytest.raises(ValidationError):
        seed.model_validate({**base, "characters": [character, {**character, "name": "Lan"}]})
    gendered = [
        {**character, "gender": "nam", "address": "anh"},
        {**character, "name": "Lan", "gender": "nữ", "address": "cô"},
    ]
    assert seed.model_validate({**base, "characters": gendered}).characters[0].gender == "nam"
    schema = bound_book_outline(2).model_json_schema()
    generated = schema["$defs"]["GeneratedSeedCharacter"]
    assert {"gender", "address"} <= set(generated["required"])
    assert MINH.locked_line() == "chính là nhân vật chính. giới tính nam, lời kể gọi là “anh”. họa sĩ nghèo"
    assert MINH.model_copy(update={"gender": None, "address": None}).locked_line() == (
        "chính là nhân vật chính. họa sĩ nghèo"
    )


def test_a_required_change_restating_a_ban_or_a_secret_is_a_plan_conflict():
    from server.story_authoring.cast_checks import plan_conflicts
    from server.story_authoring.prompts.schemas import ChapterPlan

    scene = {
        "summary": "s",
        "location": "Nhà",
        "pov": "Minh",
        "characters": ["Minh"],
        "beats": ["a", "b"],
        "emotional_turn": "e",
        "plot_function": "p",
        "dialogue_required": False,
    }
    plan = ChapterPlan(
        chapter_goal="g",
        reader_expectation="r",
        withheld_cards=["Lan là hồn ma của người vợ đã mất"],
        required_changes_by_end=["Minh biết Lan là hồn ma của người vợ", "Minh bán bức tranh đầu tiên"],
        do_not=["Không để Minh bán tranh quá sớm"],
        scenes=[scene, scene, scene],
    )
    problems = plan_conflicts(plan)
    assert len(problems) == 1
    assert "hồn ma" in problems[0]
    assert plan_conflicts(plan.model_copy(update={"withheld_cards": []})) == []


def test_the_seed_must_carry_the_ideas_own_names_and_places_count():
    from server.story_authoring.cast_checks import idea_names, missing_idea_names
    from server.story_authoring.prompts.schemas import SeedLocation, StorySeed

    idea = "Một cô giáo trẻ tên Lê Thị Hoa về Bản Lác. Cô gặp ông Tư, rồi Hoa đi."
    assert idea_names(idea) == ["Lê Thị Hoa", "Bản Lác", "Tư", "Hoa"]
    seed = StorySeed(
        working_title="t",
        premise="p",
        genre="g",
        tone="t",
        pov="p",
        central_conflict="c",
        ending_direction="e",
        characters=[LAN.model_copy(update={"name": "Lê Thị Hoa"}), MINH],
        locations=[SeedLocation(name="Bản Lác", description="d")],
    )
    assert missing_idea_names(idea, seed) == ["Tư"]
    assert idea_names("Minh co so thich dac biet. trong mot lan, Minh dat duoc kha nang giup anh") == ["Minh"]


def test_a_name_one_letter_from_a_characters_is_repaired_not_recorded():
    from server.story_authoring.checks import near_name

    assert near_name("Mạnh", {"Minh", "Lan"}) == "Minh"
    assert near_name("Huy", {"Minh", "Lan"}) is None
    assert near_name("Minh", {"Lê Minh"}) is None


def test_certain_cast_errors_are_fixed_without_a_model_call():
    from server.story_authoring.cast_checks import fix_gender_openings, fix_near_names

    text = (
        "Minh quay lưng lại cửa sổ. Cô biết rằng đây là khởi đầu.\n\n"
        "Minh bước ra. Cô gái trẻ không quay đầu. Cô ấy đi.\n\n"
        "Minh nhìn Lan. Cô cúi đầu.\n\n"
        "Minh nói: “Cô đi đi.”"
    )
    fixed = fix_gender_openings([MINH, LAN], text)
    assert fixed == (
        "Minh quay lưng lại cửa sổ. Anh biết rằng đây là khởi đầu.\n\n"
        "Minh bước ra. Chàng trai trẻ không quay đầu. Anh ấy đi.\n\n"
        "Minh nhìn Lan. Cô cúi đầu.\n\n"
        "Minh nói: “Cô đi đi.”"
    )
    assert gender_findings([MINH, LAN], [("s", fixed)]) == ()
    assert fix_near_names("Minh đi. Lúc ấy Mạnh quay lại, rồi Mạnh cười.", {"Minh", "Lan"}) == (
        "Minh đi. Lúc ấy Minh quay lại, rồi Minh cười."
    )
