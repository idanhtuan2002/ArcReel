"""The source preview finds chapter headings and warns before a run reads the story (ADR-0118)."""

from __future__ import annotations

from lib.episode_ledger import SourceDoc
from lib.source_preview import preview_source, preview_sources


def test_vietnamese_english_chinese_and_markdown_headings_are_chapters():
    text = "Chương 1: Về làng\nMinh về.\n\nCHAPTER 2\nLan đợi.\n\n## Hồi ba\nĐêm.\n\n第4章 归来\n..."
    preview = preview_source(SourceDoc(rel_path="source/a.txt", text=text))

    assert preview.chapters == 4
    assert preview.headings == ("Chương 1: Về làng", "CHAPTER 2", "## Hồi ba", "第4章 归来")
    assert preview.warnings == ("CJK_TEXT",)


def test_a_file_without_headings_is_one_chapter_and_long_or_empty_files_warn():
    plain, empty, long = preview_sources(
        [
            SourceDoc(rel_path="source/a.txt", text="Minh về làng.\n\nLan đợi."),
            SourceDoc(rel_path="source/b.txt", text="  "),
            SourceDoc(rel_path="source/c.txt", text="Chương 1\n" + "chữ " * 12_000),
        ]
    )

    assert (plain.chapters, plain.warnings) == (1, ("NO_CHAPTER_HEADINGS",))
    assert (empty.chapters, empty.warnings) == (0, ("EMPTY",))
    assert long.warnings == ("LONG_CHAPTER",)


def test_prose_that_starts_with_a_heading_word_is_not_a_chapter():
    text = "Chương 1\nHồi đó, tôi còn nhỏ lắm.\n\nPhần lớn dân làng đã đi.\n\nChương hai\nMinh về."
    preview = preview_source(SourceDoc(rel_path="source/a.txt", text=text))

    assert preview.headings == ("Chương 1", "Chương hai")
