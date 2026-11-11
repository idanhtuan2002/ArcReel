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
        {**character, "gender": "nam", "address": "anh", "voice": "nói ngắn", "flaw": "nóng nảy"},
        {**character, "name": "Lan", "gender": "nữ", "address": "cô", "voice": "nói nhỏ", "flaw": "cả nể"},
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


def test_a_seed_without_one_protagonist_a_conflict_of_its_own_or_distinct_voices_is_drawn_again():
    from server.story_authoring.cast_checks import seed_problems
    from server.story_authoring.prompts.schemas import SeedLocation, StorySeed

    lead = MINH.model_copy(update={"voice": "nói ngắn, ít cảm thán"})
    sister = LAN.model_copy(update={"voice": "nói nhỏ, hay hỏi lại"})
    seed = StorySeed(
        working_title="t",
        premise="Minh về làng bán căn nhà của cha",
        genre="g",
        tone="t",
        pov="p",
        central_conflict="Lan muốn giữ nhà để thờ cha, Minh cần tiền trả nợ",
        ending_direction="Minh giữ nhà và tự trả nợ",
        characters=[lead, sister],
        locations=[SeedLocation(name="Nhà", description="d")],
    )
    assert seed_problems(seed) == []
    restated = seed.model_copy(update={"central_conflict": "Minh về làng bán căn nhà của cha"})
    assert seed_problems(restated) == ["central_conflict phải cụ thể hơn, không chép lại premise"]
    same = seed.model_copy(update={"characters": [lead, sister.model_copy(update={"voice": "nói ngắn, ít cảm thán"})]})
    assert seed_problems(same) == ["giọng nói của Minh và Lan phải khác nhau"]
    two = seed.model_copy(
        update={"characters": [lead, sister.model_copy(update={"relation_to_protagonist": "chính là nhân vật chính"})]}
    )
    assert len(seed_problems(two)) == 1


def test_a_title_must_keep_the_packaging_rules():
    from server.story_authoring.prompts.packaging import best_title, title_problems
    from server.story_authoring.prompts.schemas import Packaging

    assert title_problems("Căn nhà cũ", ["Minh"]) == []
    assert title_problems("Học sinh thứ mười ba", ["Minh"]) == []
    assert title_problems("Minh", ["Minh"])
    assert title_problems("Ký ức", ["Minh"])
    assert title_problems("Bóng Bóng Đêm", ["Minh"])
    assert title_problems("The Ghost", ["Minh"])
    point = {"point": "p", "evidence_quote": "q"}
    packaging = Packaging.model_validate(
        {
            "titles": [
                {"title": "Ký ức", "kind": "k"},
                {"title": "Căn nhà cũ", "kind": "k"},
                {"title": "Minh", "kind": "k"},
            ],
            "blurbs": ["b1", "b2"],
            "selling_points": [point, point, point],
            "tags": ["a", "b", "c", "d", "e"],
        }
    )
    assert best_title(packaging, ["Minh"], "Tên tạm") == "Căn nhà cũ"


def test_inline_speech_counts_as_dialogue_and_a_broken_character_is_an_integrity_finding():
    from server.story_authoring.checks import SceneLengthWindow, check_scene_prose, dialogue_lines
    from server.story_authoring.repair import PATCH_SYSTEM

    assert dialogue_lines("Minh đứng dậy. “Đi thôi,” anh nói rồi mở cửa.") == 1
    assert dialogue_lines("Minh đứng dậy rồi mở cửa.") == 0
    window = SceneLengthWindow(minimum=1, maximum=10_000, hard_maximum=20_000)
    found = check_scene_prose("Minh đứng d�y rồi đi.", node_id="s", window=window, allowed_names={"Minh"})
    assert "REPLACEMENT_CHAR" in {f.code for f in found}
    assert "phủ định" in PATCH_SYSTEM


def test_a_letter_of_another_script_is_an_integrity_finding():
    from server.story_authoring.checks import SceneLengthWindow, check_scene_prose, foreign_script

    window = SceneLengthWindow(minimum=1, maximum=10_000, hard_maximum=20_000)
    text = "Minh bước trên sàn nhà gỗ скрипит dưới chân."
    found = {f.code: f for f in check_scene_prose(text, node_id="s", window=window, allowed_names={"Minh"})}
    assert found["FOREIGN_SCRIPT"].severity is Severity.HARD_INTEGRITY
    assert "скрипит" in found["FOREIGN_SCRIPT"].quote
    assert foreign_script("Đêm ấy Minh nghĩ về đứa con gái của mình.") == []
    # A character whose bible name is written in another script keeps it.
    assert foreign_script("Minh gặp Иван ở ga.", ["Иван"]) == []
    assert foreign_script("Minh gặp Иван ở ga.") != []


def test_a_scene_that_never_names_its_point_of_view_character_is_named_or_found():
    from server.story_authoring.cast_checks import name_pov, pov_findings

    unnamed = "Anh đập mạnh vào mặt bàn. Căn hộ tối om.\n\n'Anh đến rồi sao?' Lan hỏi. Anh gật đầu."
    assert {f.code for f in pov_findings([MINH, LAN], "Minh", unnamed, node_id="s")} == {"UNNAMED_POV"}
    named = name_pov([MINH, LAN], "Minh", unnamed)
    assert named.startswith("Minh đập mạnh vào mặt bàn.")
    assert named.count("Minh") == 1
    assert "'Anh đến rồi sao?'" in named
    assert pov_findings([MINH, LAN], "Minh", named, node_id="s") == ()
    # Without an address the right word is not certain: the model repairs it.
    plain = MINH.model_copy(update={"address": None})
    assert name_pov([plain], "Minh", unnamed) == unnamed


def test_narration_that_calls_someone_em_is_found_but_dialogue_and_an_em_address_are_not():
    from server.story_authoring.cast_checks import pov_findings

    drifted = "Minh dừng lại trước quán. Em bước vào, tim đập mạnh.\n\n'Em đã đợi lâu rồi,' Lan nói."
    found = pov_findings([MINH, LAN], "Minh", drifted, node_id="s")
    assert [(f.code, f.quote) for f in found] == [("NARRATION_EM", "Em bước vào, tim đập mạnh.")]
    assert pov_findings([MINH, LAN], "Minh", "Minh cười. 'Em đã đợi lâu rồi,' Lan nói.", node_id="s") == ()
    young = LAN.model_copy(update={"address": "em"})
    assert pov_findings([MINH, young], "Minh", drifted, node_id="s") == ()


def test_a_plan_declares_its_closing_hook_and_the_last_scene_is_held_to_it():
    from server.story_authoring.craft_checks import closing_hook_findings
    from server.story_authoring.prompts.schemas import ChapterPlan, bound_chapter_plan, bound_short_outline

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
    stored = {
        "chapter_goal": "g",
        "reader_expectation": "r",
        "withheld_cards": [],
        "required_changes_by_end": ["c"],
        "do_not": [],
        "scenes": [scene] * 3,
    }
    assert ChapterPlan.model_validate(stored).closing_hook is None
    bound = bound_chapter_plan(["Minh"], ["Nhà"])
    with pytest.raises(ValidationError):
        bound.model_validate(stored)
    hook = "Ai đã để lá thư dưới cửa nhà Minh đêm ấy?"
    assert bound.model_validate({**stored, "closing_hook": hook}).closing_hook == hook
    outline_chapter = {"core_task": "t", "threads_advanced": "m", "turning_point": "b"}
    outline = {
        "story_arc": "a",
        "opening": "o",
        "confrontation": "c",
        "resolution": "r",
        "chapters": [outline_chapter] * 3,
        "ending": "e",
        "final_image": "f",
    }
    with pytest.raises(ValidationError):
        bound_short_outline().model_validate(outline)
    drama = {**outline_chapter, "obstacle": "o", "choice": "c", "ending_question": "q"}
    assert bound_short_outline().model_validate({**outline, "chapters": [drama] * 3}).chapters[0].choice == "c"

    ending = "Minh đóng cửa.\n\nAnh nhìn lá thư. Ai đã để lá thư dưới cửa nhà Minh đêm ấy?"
    assert closing_hook_findings(hook, ending, node_id="s") == ()
    reworded = "Minh đóng cửa.\n\nAi đã để lá thư dưới cửa nhà anh đêm ấy?"
    assert closing_hook_findings(hook, reworded, node_id="s") == ()
    [missed] = closing_hook_findings(hook, "Minh đóng cửa.\n\nAnh ngủ một giấc dài.", node_id="s")
    assert (missed.code, missed.severity, missed.quote) == ("CLOSING_HOOK", Severity.STYLISTIC, "Anh ngủ một giấc dài.")


def test_the_closing_hook_and_drama_fields_reach_the_prompts():
    from server.story_authoring.prompts.drafting import scene_repair_context
    from server.story_authoring.prompts.planning import _drama
    from server.story_authoring.prompts.schemas import ChapterPlan, OutlineChapter

    chapter = OutlineChapter(
        core_task="t",
        threads_advanced="m",
        turning_point="b",
        obstacle="ông chủ nợ",
        choice="bán nhà",
        ending_question="ai gửi thư?",
    )
    assert _drama(chapter) == (
        "\nTrở ngại: ông chủ nợ\nLựa chọn của nhân vật chính: bán nhà\nCâu hỏi người đọc mang sang chương sau: ai gửi thư?"
    )
    assert _drama(OutlineChapter(core_task="t", threads_advanced="m", turning_point="b")) == ""
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
    plan = ChapterPlan.model_validate(
        {
            "chapter_goal": "g",
            "reader_expectation": "r",
            "withheld_cards": [],
            "required_changes_by_end": ["c"],
            "do_not": [],
            "scenes": [scene] * 3,
            "closing_hook": "Ai đã để lá thư dưới cửa?",
        }
    )
    context = scene_repair_context("facts", plan=plan, scene=plan.scenes[2], is_last=True, voice="", kept=[])
    assert "Câu cuối cùng của cảnh là: “Ai đã để lá thư dưới cửa?”" in context
