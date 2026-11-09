"""Genre packs are data the run picks by genre; humanize targets scenes with much machine voice (ADR-0119)."""

from __future__ import annotations

from server.story_authoring.checks import Finding, Severity
from server.story_authoring.driver import humanize_targets
from server.story_authoring.genre_packs import PACKS, craft_rules, fatigue_findings, pack_for, planning_block


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
