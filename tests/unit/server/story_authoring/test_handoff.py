"""The hand-off source file name: an ASCII slug of the title, bounded, never a path."""

from __future__ import annotations

import pytest

from server.story_authoring.handoff import slug_filename


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Căn nhà cũ", "can-nha-cu.md"),
        ("Đêm Đông ở Đà Lạt", "dem-dong-o-da-lat.md"),
        ("../../etc/passwd", "etc-passwd.md"),
        ("a\\b\x00c\nd", "a-b-c-d.md"),
        ("", "story.md"),
        ("???", "story.md"),
    ],
)
def test_a_title_becomes_an_ascii_slug(title, expected):
    assert slug_filename(title) == expected


def test_the_name_is_bounded_and_keeps_its_suffix():
    name = slug_filename("Chuyện dài " * 30, suffix="-0123abcd.md")
    assert len(name) <= 80
    assert name.endswith("-0123abcd.md")
    assert not name.startswith("-")


def test_narration_source_keeps_the_title_and_scene_text_without_markdown_layout():
    from server.story_authoring.driver import render_markdown
    from server.story_authoring.handoff import narration_source

    markdown = render_markdown(
        title="Căn nhà cũ",
        blurb="Minh về làng.",
        chapters=[["Cảnh một.", "Cảnh hai."], ["Cảnh ba."]],
    )

    assert narration_source(markdown) == "Căn nhà cũ\n\nCảnh một.\n\nCảnh hai.\n\nCảnh ba.\n"
