from __future__ import annotations

import pytest

from server.story_authoring.genre_packs import PACKS
from server.story_authoring.idea_profile import (
    ANGLES,
    AUDIENCES,
    DEFAULT_BOOK_CHAPTERS,
    TONES,
    ProfileDraft,
    ProfileRefused,
    ProjectProfile,
    profile_seed,
    settle_profile,
)

IDEA = "Một cô giáo trẻ về điểm trường vùng cao và phát hiện lớp học của mình có một học sinh không ai nhìn thấy."


def _draft(**changes: object) -> ProfileDraft:
    values: dict[str, object] = {
        "title": "Học sinh thứ mười ba",
        "idea": IDEA,
        "genre": "Kinh dị",
        "tone": "hồi hộp",
        "audience": "phổ thông",
        "chapters": 18,
    }
    return ProfileDraft.model_validate({**values, **changes})


def test_one_command_id_always_seeds_the_same_genre_angle_and_tone_and_a_given_pack_wins():
    seed = profile_seed("cmd-1")
    assert seed == profile_seed("cmd-1")
    assert seed.genre_pack in {pack.pack_id for pack in PACKS}
    assert seed.angle in ANGLES
    assert seed.tone in TONES
    assert profile_seed("cmd-1", genre_pack="mystery").genre_pack == "mystery"
    seeds = {profile_seed(f"cmd-{n}").genre_pack for n in range(200)}
    assert len(seeds) == len(PACKS)


def test_a_drawn_profile_inside_its_closed_sets_is_kept_as_drawn():
    profile = settle_profile(_draft(genre="kinh dị"), seed=profile_seed("cmd-1"))
    assert (profile.genre_pack, profile.tone, profile.audience, profile.book_chapters) == (
        "horror",
        "hồi hộp",
        "phổ thông",
        18,
    )
    assert profile.defaulted == ()
    assert ProjectProfile.model_validate_json(profile.model_dump_json()) == profile


def test_values_outside_their_closed_sets_fall_back_and_are_named():
    seed = profile_seed("cmd-2")
    profile = settle_profile(_draft(genre="cyberpunk noir", tone="u uất", audience="trẻ em", chapters=500), seed=seed)
    assert profile.genre_pack == seed.genre_pack
    assert profile.tone == seed.tone
    assert profile.audience == AUDIENCES[0]
    assert profile.book_chapters == DEFAULT_BOOK_CHAPTERS
    assert profile.defaulted == ("genre_pack", "tone", "audience", "book_chapters")


def test_a_showrunners_genre_and_length_win_over_the_drawn_ones():
    profile = settle_profile(_draft(), seed=profile_seed("cmd-3"), genre_pack="romance", book_chapters=6)
    assert (profile.genre_pack, profile.book_chapters, profile.defaulted) == ("romance", 6, ())


def test_an_idea_too_short_refuses_and_a_long_one_is_cut_at_a_sentence():
    with pytest.raises(ProfileRefused) as refused:
        settle_profile(_draft(idea="  Ma.  "), seed=profile_seed("cmd-4"))
    assert refused.value.code == "IDEA_EMPTY"
    long_idea = " ".join(["Một câu đủ dài để làm ý tưởng cho truyện."] * 60)
    profile = settle_profile(_draft(idea=long_idea), seed=profile_seed("cmd-4"))
    assert len(profile.idea) <= 1200
    assert profile.idea.endswith(".")


def test_a_drawn_idea_starts_only_a_new_story_and_stays_out_of_earlier_command_digests():
    from pydantic import ValidationError

    from r2.contracts.automation import RunCommand

    base = {
        "user_id": "u",
        "project_name": "p",
        "command_id": "c",
        "action": "START",
        "expected_version": 0,
        "expected_input_digest": "sha256:" + "0" * 64,
        "policy_digest": "sha256:" + "0" * 64,
    }
    assert "idea_mode" not in RunCommand.model_validate({**base, "idea": "i"}).model_dump(mode="json")
    auto = RunCommand.model_validate({**base, "idea_mode": "auto", "book_chapters": 12})
    assert auto.model_dump(mode="json")["idea_mode"] == "auto"
    with pytest.raises(ValidationError):
        RunCommand.model_validate(base)
    with pytest.raises(ValidationError):
        RunCommand.model_validate({**base, "idea_mode": "auto", "idea": "i"})
    with pytest.raises(ValidationError):
        RunCommand.model_validate({**base, "idea_mode": "auto", "story_source": "continue"})
    with pytest.raises(ValidationError):
        RunCommand.model_validate(
            {**base, "action": "PAUSE", "expected_version": 1, "run_id": "r", "idea_mode": "auto"}
        )


def test_a_repeat_is_the_same_title_or_an_overlapping_idea_and_the_safety_rule_names_minors():
    from server.story_authoring.idea_draw import DRAW_SAFETY, AvoidedIdea, draw_prompt, near_duplicate

    profile = settle_profile(_draft(), seed=profile_seed("cmd-5"))
    same_title = AvoidedIdea(title="Học sinh thứ  MƯỜI ba", idea="Một chuyện khác hẳn về biển cả và người lái tàu.")
    same_idea = AvoidedIdea(title="Khác", idea=IDEA)
    unrelated = AvoidedIdea(title="Chuyến đò cuối", idea="Một lái đò già chở người khách cuối cùng trong đêm lũ.")
    assert near_duplicate(profile, [unrelated, same_title]) == same_title
    assert near_duplicate(profile, [same_idea]) == same_idea
    assert near_duplicate(profile, [unrelated, AvoidedIdea(title="Truyện 10/11", idea="")]) is None
    assert all("dưới 18 tuổi" in rule for rule in DRAW_SAFETY.values())
    prompt = draw_prompt(profile.seed, avoid=[unrelated], safety="strict")
    assert "Chuyến đò cuối: Một lái đò già" in prompt
    assert DRAW_SAFETY["strict"] in prompt


def test_a_stored_profile_outside_its_closed_sets_is_refused():
    from pydantic import ValidationError

    profile = settle_profile(_draft(), seed=profile_seed("cmd-6"))
    with pytest.raises(ValidationError):
        ProjectProfile.model_validate({**profile.model_dump(), "genre_pack": "cyberpunk"})
