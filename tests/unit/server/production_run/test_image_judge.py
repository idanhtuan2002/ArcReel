"""The ranking judge keeps the earlier storyboard unless a later one wins in both candidate orders."""

from __future__ import annotations

import io

import httpx
import pytest
from PIL import Image

from server.production_run.image_judge import choose, judge_prompt_digest, judge_view, letter, qualify_judge


@pytest.mark.parametrize(
    ("text", "expected"), [("A", "A"), (" b.", "B"), ("**A**", "A"), ("Answer", None), ("C", None)]
)
def test_only_a_bare_letter_counts_as_an_answer(text, expected):
    assert letter(text) == expected


def _judge(preferred: bytes | None, *, broken: bool = False):
    """A judge that names ``preferred`` wherever it is shown, or always answers A (position bias)."""

    async def compare(line, first, second):
        if broken:
            raise httpx.ConnectError("down")
        if preferred is None:
            return "A"
        return "A" if first == preferred else "B" if second == preferred else None

    return compare


async def test_a_later_candidate_preferred_in_both_orders_is_chosen():
    choice = await choose(_judge(b"second"), "line", [b"first", b"second"])

    assert choice.index == 1
    assert choice.rounds == [{"between": [0, 1], "answers": ["B", "A"], "later_wins": True}]


async def test_a_position_biased_or_failing_judge_keeps_the_first_candidate():
    assert (await choose(_judge(None), "line", [b"first", b"second"])).index == 0
    assert (await choose(_judge(b"x", broken=True), "line", [b"first", b"second"])).index == 0


async def test_three_candidates_meet_as_a_ladder():
    choice = await choose(_judge(b"third"), "line", [b"first", b"second", b"third"])

    assert choice.index == 2
    assert [r["between"] for r in choice.rounds] == [[0, 1], [0, 2]]


def test_the_judge_sees_a_384_pixel_wide_jpeg():
    picture = io.BytesIO()
    Image.new("RGB", (576, 1024), (10, 120, 200)).save(picture, format="PNG")

    with Image.open(io.BytesIO(judge_view(picture.getvalue()))) as seen:
        assert (seen.format, seen.size) == ("JPEG", (384, 683))


def test_the_prompt_digest_is_stable():
    assert judge_prompt_digest() == judge_prompt_digest()
    assert judge_prompt_digest().startswith("sha256:")


def _pairs(count: int) -> list[dict]:
    return [
        {"pair_id": f"p{i}", "line": f"line {i}", "own": f"own{i}".encode(), "other": f"other{i}".encode()}
        for i in range(count)
    ]


async def test_a_judge_that_finds_each_segments_own_storyboard_in_both_orders_qualifies():
    async def compare(line, first, second):
        return "A" if first.startswith(b"own") else "B"

    report = await qualify_judge(compare, _pairs(30))

    assert (report["pairs"], report["wrong"], report["qualified"]) == (30, {"own_first": 0, "own_second": 0}, True)


async def test_a_position_biased_judge_or_too_few_pairs_does_not_qualify():
    async def always_a(line, first, second):
        return "A"

    async def right(line, first, second):
        return "A" if first.startswith(b"own") else "B"

    biased = await qualify_judge(always_a, _pairs(30))
    small = await qualify_judge(right, _pairs(29))

    assert biased["wrong"] == {"own_first": 0, "own_second": 30}
    assert biased["qualified"] is False
    assert small["qualified"] is False


async def test_three_wrong_picks_in_thirty_still_qualify_but_four_do_not():
    def judge(misses: int):
        async def compare(line, first, second):
            index = int(line.split()[1])
            own_first = first.startswith(b"own")
            if index < misses and own_first:
                return "B"
            return "A" if own_first else "B"

        return compare

    assert (await qualify_judge(judge(3), _pairs(30)))["qualified"] is True
    assert (await qualify_judge(judge(4), _pairs(30)))["qualified"] is False
