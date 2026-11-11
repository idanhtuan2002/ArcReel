from __future__ import annotations

from r2.contracts.automation import RunPolicy
from server.production_run.story_adapter import fits_run, story_limits, whole_story
from server.story_authoring.contracts import StoryLimits


def _policy() -> RunPolicy:
    return RunPolicy(
        profile_id="p",
        profile_digest="sha256:" + "a" * 64,
        routes=(),
        currency="LOCAL",
        max_cost_minor_units=0,
        max_model_calls=1500,
        max_tasks=50,
        max_runtime_seconds=64800,
        route_digests=("sha256:" + "b" * 64,),
    )


def _drafted(calls: int) -> StoryLimits:
    return StoryLimits(
        generate_calls_max=calls,
        count_calls_max=calls,
        input_tokens_max=10**9,
        output_tokens_max=10**8,
        wall_clock_max_seconds=calls * 120,
    )


def test_a_film_run_cuts_its_story_to_half_the_caps():
    film = story_limits(_policy(), _drafted(900))
    assert (film.generate_calls_max, film.wall_clock_max_seconds) == (375, 32400)


def test_a_story_only_run_keeps_the_whole_bound_and_takes_its_time_from_the_run():
    part = _drafted(603)
    assert fits_run(_policy(), part, spent_calls=4)
    alone = whole_story(_policy(), part, spent_seconds=250)
    assert (alone.generate_calls_max, alone.wall_clock_max_seconds) == (603, 64550)
    assert not fits_run(_policy(), _drafted(749), spent_calls=4)
