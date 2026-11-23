"""Vietnamese narration: DramaClaw's Chinese rewrite translated line by line, names restored, format kept."""

from __future__ import annotations

from assembly.connector.rewriter import _parse, build_prompt


def test_the_prompt_lists_the_vietnamese_names_and_the_dialogue_shape() -> None:
    prompt = build_prompt(["姑娘轻声说：“是爷爷留下的。”"], ["Vy", "ông Khang"], ["line 1 contains Chinese"])
    assert "Vy, ông Khang" in prompt
    assert "：“câu nói”" in prompt
    assert "exactly 1 lines" in prompt
    assert "line 1 contains Chinese" in prompt


def test_answers_are_read_even_with_text_around_the_json() -> None:
    assert _parse('Đây:\n{"paragraphs": ["Mưa rơi.", "Vy khẽ nói：“Của ông cháu.”"]}') == [
        "Mưa rơi.",
        "Vy khẽ nói：“Của ông cháu.”",
    ]


def test_the_dialogue_colon_does_not_count_as_leftover_chinese(monkeypatch) -> None:
    import httpx

    from assembly.connector import rewriter

    class Answer:
        status_code = 200

        def raise_for_status(self) -> None: ...

        def json(self) -> dict:
            return {"choices": [{"message": {"content": '{"paragraphs": ["Vy khẽ hỏi：“Bác ơi？”"]}'}}]}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Answer())
    out = rewriter.translate_lines(["女孩轻声问：“师傅？”"], ["Vy"], newapi_url="http://x", token="t")
    assert out == ["Vy khẽ hỏi：“Bác ơi?”"]
