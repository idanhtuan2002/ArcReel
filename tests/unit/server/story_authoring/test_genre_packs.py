"""Genre packs are data the run picks by genre; humanize targets scenes with much machine voice (ADR-0119)."""

from __future__ import annotations

from server.story_authoring.checks import Finding, Severity
from server.story_authoring.driver import humanize_targets
from server.story_authoring.genre_packs import (
    PACKS,
    craft_rules,
    fatigue_findings,
    genre_menu,
    pack_for,
    planning_block,
)
from server.story_authoring.prompts.planning import seed_prompt


def test_the_brief_genre_wins_then_the_seed_genre_and_unknown_genres_get_no_pack():
    assert pack_for("Trinh thám kinh điển", "tâm lý").pack_id == "mystery"
    assert pack_for("truyện ngắn", "Kinh dị tâm linh").pack_id == "horror"
    assert pack_for("truyện ngắn", "xyz") is None
    assert planning_block(None) == ""
    assert craft_rules(None) == ()


def test_every_pack_has_guidance_and_fatigue_phrases_and_unique_ids():
    assert len({p.pack_id for p in PACKS}) == len(PACKS)
    for pack in PACKS:
        assert pack.planning
        assert pack.craft
        assert pack.fatigue
        assert pack.label in planning_block(pack)
        assert "tối đa 2 lần" in craft_rules(pack)[-1]


def test_a_worn_genre_phrase_used_three_times_in_a_chapter_is_recorded_in_its_first_scene():
    pack = pack_for("kinh dị")
    scenes = [("s1", "Lạnh sống lưng. Cô lùi lại."), ("s2", "Lạnh sống lưng lần nữa, rồi lạnh sống lưng.")]

    [finding] = fatigue_findings(pack, scenes)

    assert (finding.code, finding.node_id, finding.severity) == ("GENRE_FATIGUE", "s1", Severity.STYLISTIC)


def test_humanize_targets_only_scenes_with_three_quoted_machine_voice_findings():
    def f(code: str, node: str, quote: str = "x") -> Finding:
        return Finding(code, Severity.STYLISTIC, node, "m", quote)

    findings = [
        f("STOCK_PHRASE", "a"),
        f("ANTI_AI:report", "a"),
        f("GENRE_FATIGUE", "a"),
        f("STOCK_PHRASE", "b"),
        f("ANTI_AI:report", "b"),
        f("UNIFORM_PARAGRAPHS", "b", quote=""),
        f("CRAFT:hook", "b"),
    ]

    assert {x.node_id for x in humanize_targets(findings)} == {"a"}
    assert len(humanize_targets(findings)) == 3


def test_an_alias_counts_only_as_a_whole_word():
    assert pack_for("chuyện mai sau") is None
    horror = pack_for("chuyện ma làng")
    assert horror is not None
    assert horror.pack_id == "horror"


def test_a_seed_whose_brief_names_no_pack_chooses_one_from_the_menu_and_a_named_pack_is_kept():
    open_genre = seed_prompt(idea="Một người con về làng bán căn nhà của cha.", genre="truyện ngắn")
    assert genre_menu() in open_genre
    assert all(pack.label in open_genre for pack in PACKS)
    named = seed_prompt(idea="Một vụ mất tích.", genre="Trinh thám")
    assert "- genre: Trinh thám." in named
    assert genre_menu() not in named


def test_a_specific_genre_takes_its_own_pack_over_a_general_one():
    from server.story_authoring.film_looks import film_look

    cases = {
        "Võ hiệp": "wuxia",
        "tiên hiệp": "xianxia",
        "Ngược luyến": "angst",
        "Tổng tài – hào môn": "ceo",
        "Báo thù – vả mặt": "revenge",
        "Xuyên không": "rebirth",
        "Hệ thống – game": "system",
        "Mạt thế": "apocalypse",
        "Truyện ngủ ngon": "bedtime",
        "Cổ tích": "kids",
        "Chuyện có thật – đời thường": "storytime",
        "Tâm lý – gia đình": "family",
        "Ngôn tình": "romance",
        "Kinh dị": "horror",
    }
    for genre, pack_id in cases.items():
        pack = pack_for(genre)
        assert pack is not None, genre
        assert pack.pack_id == pack_id, genre
    # Every pack has a film look on a known style template.
    assert all(film_look(pack.pack_id) is not None for pack in PACKS)
