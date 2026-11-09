"""Story translation keeps paragraphs and names, retries failed batches and skips unchanged files (ADR-0120)."""

from __future__ import annotations

import json
import re

import pytest

from lib.story_translation import TranslationError, batches, check_batch, protected_terms, translate_story
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult

PROJECT = {"characters": {"Minh": {}, "Lan": {}}, "scenes": {"Căn nhà cũ": {}}, "source_language": "vi"}
STORY = "Minh về Căn nhà cũ.\n\nLan đứng chờ ở cổng.\n\nHai anh em im lặng."


def _source_paragraphs(prompt: str) -> list[str]:
    return json.loads(prompt.split("SOURCE PARAGRAPHS:\n", 1)[1])


def _translator(*, broken_first: bool = False):
    calls: list[str] = []

    async def generate(request: TextGenerationRequest) -> TextGenerationResult:
        calls.append(request.prompt)
        source = _source_paragraphs(request.prompt)
        if broken_first and len(calls) == 1:
            out = ["Only one paragraph."]
        else:
            out = [re.sub(r"về|đứng chờ ở cổng|im lặng", "x", p) + " (en)" for p in source]
        return TextGenerationResult(text=json.dumps({"paragraphs": out}), provider="p", model="m")

    return generate, calls


def test_batches_keep_paragraph_order_and_bound_their_size():
    assert batches(["a" * 3000, "b" * 2000, "c" * 100], size=4000) == [["a" * 3000], ["b" * 2000, "c" * 100]]


def test_a_batch_must_keep_count_names_length_and_script():
    terms = protected_terms(PROJECT)
    assert terms == ["Minh", "Lan"]  # characters only: scene and prop names are translated
    source = ["Minh về Căn nhà cũ.", "Lan đứng chờ."]

    assert check_batch(source, ["Minh comes home to the old house.", "Lan waits."], target="en", terms=terms) == []
    assert "exactly 2" in check_batch(source, ["x"], target="en", terms=terms)[0]
    problems = check_batch(source, ["He comes to the old house.", "蘭 waits, Lan."], target="en", terms=terms)
    assert any("Minh" in p for p in problems)
    assert any("Chinese, Japanese or Korean" in p for p in problems)


def test_a_name_that_is_also_a_word_is_protected_only_where_it_names_someone():
    terms = ["Hoa"]
    assert check_batch(["Vườn hoa nở rộ."], ["The flower garden is in bloom."], target="en", terms=terms) == []
    assert check_batch(["Hoa cười."], ["She laughs."], target="en", terms=terms)


def test_lengths_are_judged_per_script_and_cjk_names_are_exempt_from_the_script_rule():
    vi = ["Ông lái đò chèo chậm qua khúc sông rộng trong buổi sớm mờ sương."]
    assert check_batch(vi, ["老船夫在晨雾中慢慢划过宽阔的河面。"], target="zh", terms=[]) == []
    assert check_batch(["李明回家了。"], ["Li Ming came home at last, tired."], target="en", terms=[]) == []
    assert check_batch(["李明回家了。"], ["李明 came home."], target="en", terms=["李明"]) == []


async def test_a_story_is_translated_retried_with_reasons_and_skipped_when_unchanged(tmp_path):
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "truyen.txt").write_text(STORY, encoding="utf-8")
    generate, calls = _translator(broken_first=True)

    result = await translate_story(tmp_path, PROJECT, "en", generate=generate)

    assert result["files"] == [{"source": "source/truyen.txt", "skipped": False, "calls": 2}]
    assert "exactly 3" in calls[1]  # the retry names the failed check
    text = (tmp_path / "translations" / "en" / "truyen.txt.md").read_text(encoding="utf-8")
    assert text.count("\n\n") == 2
    assert "Căn nhà cũ" in text
    record = json.loads((tmp_path / "translations" / "en" / "truyen.txt.json").read_text(encoding="utf-8"))
    assert (record["target_language"], record["source_relpath"]) == ("en", "source/truyen.txt")
    assert (tmp_path / "source" / "truyen.txt").read_text(encoding="utf-8") == STORY

    again = await translate_story(tmp_path, PROJECT, "en", generate=generate)
    assert again["files"] == [{"source": "source/truyen.txt", "skipped": True}]
    assert len(calls) == 2


async def test_a_batch_that_never_passes_fails_and_the_story_language_is_refused(tmp_path):
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "truyen.txt").write_text(STORY, encoding="utf-8")

    async def broken(request: TextGenerationRequest) -> TextGenerationResult:
        return TextGenerationResult(text='{"paragraphs": ["x"]}', provider="p", model="m")

    with pytest.raises(TranslationError, match="after 3 attempts"):
        await translate_story(tmp_path, PROJECT, "en", generate=broken)
    with pytest.raises(TranslationError, match="already written"):
        await translate_story(tmp_path, PROJECT, "vi", generate=broken)
    with pytest.raises(TranslationError, match="no story text"):
        await translate_story(tmp_path / "empty", PROJECT, "en", generate=broken)


def test_a_vietnamese_batch_with_a_stray_han_character_is_judged_as_vietnamese():
    source = ["Lão đạo sĩ viết chữ 道 lên tấm bảng gỗ trước cổng chùa, rồi lặng lẽ bỏ đi trong sương sớm."]
    assert (
        check_batch(source, ["老道士在寺门前的木板上写了一个道字，然后在晨雾中悄然离去。"], target="zh", terms=[]) == []
    )


def test_a_cjk_name_must_be_kept_as_written():
    assert check_batch(["李明走进房间。"], ["Lý Minh bước vào phòng."], target="vi", terms=["李明"])
