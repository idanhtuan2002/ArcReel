"""A story that already exists is read before it is continued or rewritten (ADR-0115)."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.story_authoring.handoff import _choose_filename
from server.story_authoring.prompts.prior import CanonLock, attest, prior_context, split_prior
from server.story_authoring.service import StoryActionRefused, brief_idea
from server.story_authoring.variant_profiles import PROFILES


def _lock(*names: str) -> CanonLock:
    return CanonLock.model_validate(
        {
            "title_hint": "Căn nhà",
            "genre": "đời thường",
            "tone": "trầm",
            "pov": "ngôi ba",
            "characters": [
                {"name": n, "role": "r", "relation_to_protagonist": "x", "description": "d", "current_state": "s"}
                for n in names
            ],
            "places": [{"name": "Bến Đò", "description": "d"}, {"name": "Lâu đài", "description": "d"}],
            "chapter_events": ["e"],
            "open_threads": [],
            "ending_state": "kết",
            "style_notes": "câu ngắn",
        }
    )


def test_a_long_text_is_read_in_chunks_cut_at_paragraphs():
    paragraphs = [f"Câu số {i}. " * 60 for i in range(12)]
    chunks = split_prior("\n\n".join(paragraphs), size=2000)
    assert len(chunks) > 1
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert "".join(chunks).replace("\n", "").replace(" ", "") == "".join(paragraphs).replace(" ", "")


def test_the_canon_lock_keeps_only_what_the_text_names():
    text = "Minh và Lan đi qua Bến Đò."
    attested = attest(_lock("Minh", "Lan", "Tuấn"), text)
    assert [c.name for c in attested.characters] == ["Minh", "Lan"]
    assert [p.name for p in attested.places] == ["Bến Đò"]
    with pytest.raises(ValueError, match="no character"):
        attest(_lock("Tuấn"), text)


def test_the_context_says_what_kind_of_part_this_is():
    continuation = prior_context(_lock("Minh"), mode="continuation", direction="Minh đi tìm người lạ.", part=3)
    assert "PHẦN 3" in continuation
    assert "Minh đi tìm người lạ." in continuation
    variant = prior_context(_lock("Minh"), mode="variant", direction="Kể ở ngôi thứ nhất.", part=2)
    assert "PHIÊN BẢN KHÁC" in variant
    assert "YÊU CẦU BIẾN THỂ" in variant


def test_a_variant_idea_comes_from_its_profile_its_text_or_both():
    assert brief_idea(None, "first-person") == PROFILES["first-person"].instruction
    assert brief_idea("Thêm mưa.", "first-person").endswith("Thêm mưa.")
    with pytest.raises(StoryActionRefused, match="VARIANT_PROFILE_UNKNOWN"):
        brief_idea(None, "nope")
    with pytest.raises(StoryActionRefused, match="IDEA_REQUIRED"):
        brief_idea(None, None)


def test_a_continuation_is_named_to_follow_every_story_file(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("a-truyen.txt", "zz-cuoi.txt", "episode_1.txt"):
        (source / name).write_text("x", encoding="utf-8")
    name = _choose_filename("Phần hai", "sha256:" + "0" * 64, source, "y", after=True)
    stems = sorted([*(p.stem for p in source.iterdir() if not p.name.startswith("episode_")), Path(name).stem])
    assert stems[-1] == Path(name).stem
    assert name.startswith("zz-cuoi~")
    assert _choose_filename("Phần hai", "sha256:" + "0" * 64, tmp_path / "empty", "y", after=True).endswith(".md")
