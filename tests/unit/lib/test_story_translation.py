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
    assert terms == ["Căn nhà cũ", "Minh", "Lan"]
    source = ["Minh về Căn nhà cũ.", "Lan đứng chờ."]

    assert check_batch(source, ["Minh comes home to Căn nhà cũ.", "Lan waits."], target="en", terms=terms) == []
    assert "exactly 2" in check_batch(source, ["x"], target="en", terms=terms)[0]
    problems = check_batch(source, ["Minh comes to the old house.", "蘭 waits."], target="en", terms=terms)
    assert any("Căn nhà cũ" in p for p in problems)
    assert any("Chinese, Japanese or Korean" in p for p in problems)
    assert check_batch(source, ["Minh comes home to Căn nhà cũ.", "蘭 waits, Lan."], target="zh", terms=terms) == []


async def test_a_story_is_translated_retried_with_reasons_and_skipped_when_unchanged(tmp_path):
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "truyen.txt").write_text(STORY, encoding="utf-8")
    generate, calls = _translator(broken_first=True)

    result = await translate_story(tmp_path, PROJECT, "en", generate=generate)

    assert result["files"] == [{"source": "source/truyen.txt", "skipped": False, "calls": 2}]
    assert "exactly 3" in calls[1]  # the retry names the failed check
    text = (tmp_path / "translations" / "en" / "truyen.md").read_text(encoding="utf-8")
    assert text.count("\n\n") == 2
    assert "Căn nhà cũ" in text
    record = json.loads((tmp_path / "translations" / "en" / "truyen.json").read_text(encoding="utf-8"))
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
