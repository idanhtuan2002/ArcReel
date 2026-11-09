"""The book's plan, hook ledger and memory are computed in code (ADR-0116)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.story_authoring.book import (
    BookMemory,
    BookOutline,
    BookPart,
    BookPlan,
    BookRow,
    BookSpec,
    ChapterDigest,
    ChapterRole,
    add_rows,
    attest_digest,
    bound_rows,
    due_hooks,
    fold,
    initial_memory,
    memory_block,
    merged_seed,
    next_hook_ids,
    part_outline,
    plan_problems,
)
from server.story_authoring.contracts import StoryLimits, StoryModelSelection
from server.story_authoring.driver import StoryBrief, entity_keys, part_length_findings, render_markdown
from server.story_authoring.prompts.schemas import StorySeed


def _row(role: ChapterRole, *, plants: list[str] | None = None, payoffs: list[str] | None = None) -> BookRow:
    return BookRow(
        core_task="làm việc",
        threads_advanced="mạch",
        turning_point="bước ngoặt",
        role=role,
        plants=plants or [],
        payoffs=payoffs or [],
    )


def _seed() -> StorySeed:
    return StorySeed.model_validate(
        {
            "working_title": "Căn nhà cũ",
            "premise": "p",
            "genre": "g",
            "tone": "t",
            "pov": "ngôi thứ ba",
            "central_conflict": "c",
            "ending_direction": "e",
            "characters": [
                {"name": n, "role": "r", "relation_to_protagonist": "x", "description": "d", "goal": "g"}
                for n in ("Minh", "Lan")
            ],
            "locations": [{"name": "Căn nhà cũ", "description": "d"}],
        }
    )


def _outline(volumes: int = 1) -> BookOutline:
    return BookOutline.model_validate(
        {
            "logline": "l",
            "story_arc": "arc",
            "central_question": "q",
            "ending": "Minh ở lại.",
            "final_image": "ngọn đèn",
            "volumes": [
                {
                    "title": f"Quyển {v}",
                    "objective": f"mục tiêu {v}",
                    "key_results": ["a", "b", "c"],
                    "turning_point": "tp",
                    "new_characters": (
                        [{"name": "Tuấn", "role": "r", "relation_to_protagonist": "x", "description": "d", "goal": "g"}]
                        if v == 2
                        else []
                    ),
                    "new_locations": [],
                }
                for v in range(1, volumes + 1)
            ],
        }
    )


def test_parts_split_the_remainder_over_the_first_parts_and_volumes_follow_the_budget_rule():
    spec = BookSpec(chapters=13, part_chapters=5)
    assert spec.parts() == ((1, 5), (6, 4), (10, 4))
    assert BookSpec(chapters=30).volumes() == ((1, 15), (16, 30))
    assert len(BookSpec(chapters=120).volumes()) == 5
    assert BookSpec(chapters=6).volumes() == ((1, 6),)
    part = BookPart(spec=spec, part=3)
    assert (part.first_chapter, part.chapters, part.is_last) == (10, 4, True)


def test_a_book_spec_refuses_a_short_story_and_unbounded_parts():
    with pytest.raises(ValidationError):
        BookSpec(chapters=5)
    with pytest.raises(ValidationError):
        BookSpec(chapters=30, part_chapters=7)


def test_hook_ids_are_assigned_in_code_and_a_payoff_closes_the_hook():
    rows, hooks = add_rows((), (), [_row(ChapterRole.SETUP, plants=["lá thư"])], first=1, total=6)
    assert [h.hook_id for h in hooks] == ["h1"]
    assert next_hook_ids(hooks, 2) == ["h2", "h3"]
    rows, hooks = add_rows(rows, hooks, [_row(ChapterRole.PAYOFF, payoffs=["h1"])], first=2, total=6)
    assert hooks[0].paid == 2
    assert rows[1].payoffs == ("h1",)


def test_plan_problems_catch_role_runs_a_weak_ending_and_unpaid_or_premature_hooks():
    rows, hooks = add_rows(
        (),
        (),
        [
            _row(ChapterRole.ADVANCE, plants=["lá thư"], payoffs=["h1"]),
            _row(ChapterRole.ADVANCE),
            _row(ChapterRole.ADVANCE),
            _row(ChapterRole.BREATH),
            _row(ChapterRole.TURN),
            _row(ChapterRole.BREATH),
        ],
        first=1,
        total=6,
    )
    problems = plan_problems(rows, hooks, total=6)
    assert any("cùng vai trò 'advance'" in p for p in problems)
    assert any("chương cuối 6" in p for p in problems)
    assert any("h1" in p and "giải muộn nhất" in p for p in problems)
    assert any("chương 1 giải h1" in p for p in problems)


def test_a_clean_plan_has_no_problems():
    rows, hooks = add_rows(
        (),
        (),
        [
            _row(ChapterRole.SETUP, plants=["lá thư"]),
            _row(ChapterRole.ADVANCE),
            _row(ChapterRole.TURN, payoffs=["h1"]),
            _row(ChapterRole.BREATH),
            _row(ChapterRole.ADVANCE),
            _row(ChapterRole.CLIMAX),
        ],
        first=1,
        total=6,
    )
    assert plan_problems(rows, hooks, total=6) == []


def test_bound_rows_fix_the_count_and_the_payoff_ids():
    model = bound_rows(2, ["h1"])
    schema = model.model_json_schema()
    assert (schema["properties"]["rows"]["minItems"], schema["properties"]["rows"]["maxItems"]) == (2, 2)
    with pytest.raises(ValidationError):
        model.model_validate({"rows": [_row(ChapterRole.SETUP, payoffs=["h9"]).model_dump()] * 2})
    no_hooks = bound_rows(1, [])
    with pytest.raises(ValidationError):
        no_hooks.model_validate({"rows": [_row(ChapterRole.SETUP, payoffs=["h1"]).model_dump()]})


def test_volume_characters_join_the_cast_after_the_seed_so_keys_stay_stable():
    seed = _seed()
    merged = merged_seed(seed, _outline(volumes=2))
    assert [c.name for c in merged.characters] == ["Minh", "Lan", "Tuấn"]
    before, _ = entity_keys(seed)
    after, _ = entity_keys(merged)
    assert {n: after[n] for n in before} == before
    assert merged_seed(merged, _outline(volumes=2)) == merged


def _plan(total: int = 6) -> BookPlan:
    rows, hooks = add_rows(
        (),
        (),
        [_row(ChapterRole.SETUP, plants=["lá thư"]), _row(ChapterRole.ADVANCE)]
        + [_row(r) for r in (ChapterRole.TURN, ChapterRole.BREATH, ChapterRole.ADVANCE)]
        + [_row(ChapterRole.CLIMAX, payoffs=["h1"])],
        first=1,
        total=total,
    )
    return BookPlan(outline=_outline().model_dump(), rows=rows, hooks=hooks)


def test_a_part_outline_ends_on_its_turning_point_and_the_last_part_on_the_book_ending():
    plan = _plan()
    spec = BookSpec(chapters=6, part_chapters=3)
    first = part_outline(plan, BookPart(spec=spec, part=1))
    last = part_outline(plan, BookPart(spec=spec, part=2))
    assert len(first.chapters) == 3
    assert first.ending == "bước ngoặt"
    assert last.ending == "Minh ở lại."


def _digest(summary: str, *, names: tuple[str, ...] = ("Minh",), hooks=(), threads=()) -> ChapterDigest:
    return ChapterDigest.model_validate(
        {
            "summary": summary,
            "events": ["e"],
            "characters": [{"name": n, "state": f"{n} mệt"} for n in names],
            "hooks": list(hooks),
            "new_threads": list(threads),
            "time_place": "đêm, căn nhà",
        }
    )


def test_a_digest_keeps_only_characters_the_chapter_names():
    digest = _digest("s", names=("Minh", "Tuấn"))
    kept = attest_digest(digest, "Minh mở cửa. Không ai ở đó.")
    assert [c.name for c in kept.characters] == ["Minh"]


def test_the_memory_folds_digests_into_bounded_windows_and_tracks_hooks():
    plan = _plan()
    memory = initial_memory(plan)
    digests = [
        (c, _digest(f"chương {c}", hooks=[{"hook": "h1", "op": "touched"}] if c == 2 else [], threads=["ai gõ cửa?"]))
        for c in range(1, 11)
    ]
    folded = fold(memory, digests, part=1, part_summary="phần 1", tail="x" * 2000)
    assert [c for c, _ in folded.chapter_summaries] == [3, 4, 5, 6, 7, 8, 9, 10]
    assert folded.part_summaries == ((1, "phần 1"),)
    assert len(folded.tail) == 1500
    h1 = next(h for h in folded.hooks if h.hook_id == "h1")
    assert (h1.status, h1.last_touched) == ("touched", 2)
    assert [h.hook_id for h in folded.hooks if h.hook_id.startswith("u")] == [f"u{i}" for i in range(1, 11)]
    assert folded.character_state("Minh") == "Minh mệt"
    again = fold(folded, [(11, _digest("chương 11"))], part=2, part_summary="", tail="")
    assert again.part_summaries == folded.part_summaries
    assert again.tail == folded.tail


def test_a_hook_is_due_when_its_payoff_chapter_comes_or_it_falls_silent():
    plan = _plan()
    memory = initial_memory(plan)
    assert [h.hook_id for h in due_hooks(memory, plan, 6)] == ["h1"]
    assert due_hooks(memory, plan, 3) == []
    silent = BookMemory(hooks=memory.hooks)
    assert [h.hook_id for h in due_hooks(silent, plan, 10)] == ["h1"]
    block = memory_block(memory, plan, chapter=6)
    assert "h1: lá thư" in block


def test_a_part_length_is_judged_against_its_own_target():
    chapter = ["một hai ba bốn năm"] * 2  # ten syllables
    assert part_length_findings([chapter], 10) == ()
    assert part_length_findings([chapter], 14)[0].severity.value == "STYLISTIC"
    finding = part_length_findings([chapter], 100)[0]
    assert (finding.code, finding.severity.value) == ("STORY_LENGTH", "HARD_STRUCTURAL")


def test_a_part_numbers_its_chapters_across_the_book():
    text = render_markdown(title="Sách — Phần 2", blurb="b", chapters=[["a"], ["b"]], first_chapter=4)
    assert "## Chương 4" in text
    assert "## Chương 5" in text
    assert "## Chương 1" not in text


def test_a_brief_without_a_book_keeps_its_digest_and_a_part_takes_its_chapter_count():
    selection = StoryModelSelection.create(
        provider_id="custom-ollama", endpoint="ollama-chat", base_url="http://o:1", model_id="m", has_credential=False
    )
    limits = StoryLimits(input_tokens_max=1, output_tokens_max=1, wall_clock_max_seconds=1)
    brief = StoryBrief(idea="i", genre="g", selection=selection, limits=limits)
    assert "book" not in brief.model_dump(mode="json")
    assert brief.chapters == 3
    part = brief.model_copy(update={"book": BookPart(spec=BookSpec(chapters=13, part_chapters=5), part=2)})
    assert part.chapters == 4
    assert part.digest() != brief.digest()


def test_a_run_command_carries_a_book_only_from_an_idea_and_drops_it_at_its_default():
    from r2.contracts.automation import RunCommand

    base = {
        "user_id": "u",
        "project_name": "p",
        "command_id": "c",
        "action": "START",
        "expected_version": 0,
        "expected_input_digest": "sha256:" + "0" * 64,
        "policy_digest": "sha256:" + "0" * 64,
        "idea": "i",
    }
    assert "book_chapters" not in RunCommand.model_validate(base).model_dump(mode="json")
    assert RunCommand.model_validate({**base, "book_chapters": 30}).book_chapters == 30
    with pytest.raises(ValidationError):
        RunCommand.model_validate({**base, "story_source": "continue", "book_chapters": 30})


def test_a_long_book_chapter_is_planned_with_enough_scenes_for_its_length():
    from server.story_authoring.prompts.schemas import bound_chapter_plan

    scenes = bound_chapter_plan(["Minh"], ["Căn nhà cũ"], min_scenes=5).model_json_schema()["properties"]["scenes"]
    assert (scenes["minItems"], scenes["maxItems"]) == (5, 5)
