"""A trailer cut from a finished film (ADR-0164)."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.text_backends.base import TextGenerationRequest, TextGenerationResult
from lib.trailer import Episode, TrailerError, TrailerPlan, cut_trailer, plan_problems, plan_trailer, probe, story_lines

SRT_1 = """1
00:00:00,000 --> 00:00:04,000
Ông Bảy lau mái chèo.

2
00:00:04,500 --> 00:00:09,000
Cô Hòa hỏi: chuyến đò cuối đi đâu?

3
00:00:09,500 --> 00:00:14,000
Ông không trả lời.
"""
SRT_2 = """1
00:00:00,000 --> 00:00:05,000
Nước sông dâng lên trong đêm.

2
00:00:05,500 --> 00:00:10,000
Ông Bảy kể bí mật của bến đò.

3
00:00:10,500 --> 00:00:14,000
Bình minh, con đò cập bến.
"""


def _episodes(root: Path = Path("x")) -> list[Episode]:
    return [
        Episode(1, root / "episode_1.mp4", 15.0, SRT_1, has_end_card=True),
        Episode(2, root / "episode_2.mp4", 15.0, SRT_2, has_end_card=False),
    ]


def test_lines_are_numbered_with_their_place_in_the_story():
    lines, total = story_lines(_episodes())
    assert total == 30.0
    assert [line.id for line in lines] == ["E1L1", "E1L2", "E1L3", "E2L1", "E2L2", "E2L3"]
    assert lines[4].story_at == 20.5
    assert lines[1].text == "Cô Hòa hỏi: chuyến đò cuối đi đâu?"


def test_a_plan_is_refused_for_spoilers_order_unknown_ids_and_the_next_episode_card():
    episodes = _episodes()
    lines, total = story_lines(episodes)
    good = TrailerPlan(hook="E1L2", beats=["E1L1", "E2L1"], cards=["Một đêm"], end_card="Xem trọn bộ")
    assert plan_problems(good, lines, episodes, total) == []
    spoiler = TrailerPlan(hook="E1L2", beats=["E1L1", "E2L3"], end_card="Xem")
    assert any("gives away the ending" in p for p in plan_problems(spoiler, lines, episodes, total))
    unordered = TrailerPlan(hook="E1L2", beats=["E2L1", "E1L1"], end_card="Xem")
    assert "the beats are not in story order" in plan_problems(unordered, lines, episodes, total)
    unknown = TrailerPlan(hook="E9L1", beats=["E1L1", "E2L1"], end_card="Xem")
    assert plan_problems(unknown, lines, episodes, total)[0].startswith("unknown line ids")
    under_card = TrailerPlan(hook="E1L3", beats=["E1L1", "E2L1"], end_card="Xem")
    assert any("next-episode card" in p for p in plan_problems(under_card, lines, episodes, total))


def test_a_refused_plan_is_sent_back_with_its_problems_and_three_refusals_fail():
    answers = [
        {"hook": "E1L2", "beats": ["E1L1", "E2L3"], "cards": [], "end_card": "Xem trọn bộ"},
        {"hook": "E1L2", "beats": ["E1L1", "E2L1"], "cards": [], "end_card": "Xem trọn bộ"},
    ]
    prompts: list[str] = []

    async def generate(request: TextGenerationRequest) -> TextGenerationResult:
        prompts.append(request.prompt)
        return TextGenerationResult(text=json.dumps(answers.pop(0)), model="m", provider="p")

    plan = asyncio.run(plan_trailer("Chuyến đò cuối", _episodes(), generate))
    assert plan.beats == ["E1L1", "E2L1"]
    assert "gives away the ending" in prompts[1]

    async def always_bad(_request: TextGenerationRequest) -> TextGenerationResult:
        return TextGenerationResult(text="not json", model="m", provider="p")

    with pytest.raises(TrailerError, match="NO_PASSING_PLAN"):
        asyncio.run(plan_trailer("Chuyến đò cuối", _episodes(), always_bad))


def _film(path: Path, seconds: int, tone: int) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=size=144x256:rate=24:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )  # fmt: skip


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_the_cut_joins_whole_lines_cards_and_the_end_card(tmp_path: Path):
    _film(tmp_path / "episode_1.mp4", 15, 440)
    _film(tmp_path / "episode_2.mp4", 15, 660)
    plan = TrailerPlan(hook="E1L2", beats=["E1L1", "E2L1"], cards=["Một đêm"], end_card="Xem trọn bộ")
    output = tmp_path / "out" / "trailer.mp4"
    cuts = asyncio.run(cut_trailer(plan, _episodes(tmp_path), title="Chuyến đò cuối", output=output))
    assert [c.get("line") or c.get("card") for c in cuts] == [
        "E1L2",
        "Một đêm",
        "E1L1",
        "E2L1",
        "Chuyến đò cuối — Xem trọn bộ",
    ]
    assert cuts[0]["start"] == 4.5
    width, height, _fps, duration = asyncio.run(probe(output))
    assert (width, height) == (144, 256)
    expected = (9.2 - 4.5) + 1.6 + 4.2 + 5.2 + 2.8
    assert abs(duration - expected) < 0.4
