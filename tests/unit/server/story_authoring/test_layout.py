from __future__ import annotations

from server.story_authoring.layout import natural_paragraphs, same_text, sentences

SCENE = (
    "Minh đứng lặng giữa phòng. Gió lùa qua khe cửa, lạnh buốt. Anh nhìn bức tranh treo ngược. Lan bước vào, tay "
    "cầm cây nến. “Anh còn thức à?” Lan hỏi. Minh gật đầu. “Em nghe thấy tiếng gì đó. Ở dưới bếp.” Cô nói khẽ rồi "
    "quay đi. Ông Tư đã nói: “Đừng mở cửa sau nửa đêm.” Minh nhớ lời ấy. Anh thở dài. Đêm còn dài lắm."
)


def test_a_quotation_is_never_split_and_a_stop_inside_it_ends_the_sentence():
    assert sentences("Anh nói: “Đi thôi. Nhanh lên!” Rồi anh chạy. — Chờ đã! Lan gọi.") == [
        "Anh nói: “Đi thôi. Nhanh lên!”",
        "Rồi anh chạy.",
        "— Chờ đã!",
        "Lan gọi.",
    ]


def test_dialogue_lines_start_paragraphs_and_narration_keeps_one_to_three_sentences():
    out = natural_paragraphs(SCENE)
    paragraphs = out.split("\n\n")
    assert same_text(SCENE, out)
    assert natural_paragraphs(out) == out
    assert "“Anh còn thức à?” Lan hỏi." in paragraphs
    assert any(p.startswith("“Em nghe thấy tiếng gì đó. Ở dưới bếp.”") for p in paragraphs)
    for paragraph in paragraphs:
        assert 1 <= len(sentences(paragraph)) <= 3


def test_a_wall_of_blocks_is_laid_out_again_with_no_word_lost():
    wall = "\n\n".join([SCENE, SCENE])
    out = natural_paragraphs(wall)
    assert same_text(wall, out)
    assert len(out.split("\n\n")) > 2
