from __future__ import annotations

from r2.contracts.automation import RunPolicy
from server.production_run.story_adapter import STORY_ONLY_SHARE, STORY_SHARE, story_limits
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


def test_a_story_only_run_gets_most_of_the_caps_and_a_film_run_half():
    drafted = StoryLimits(
        generate_calls_max=900,
        count_calls_max=900,
        input_tokens_max=10**9,
        output_tokens_max=10**8,
        wall_clock_max_seconds=900 * 120,
    )
    film = story_limits(_policy(), drafted)
    alone = story_limits(_policy(), drafted, share=STORY_ONLY_SHARE)
    assert (film.generate_calls_max, film.wall_clock_max_seconds) == (375, 32400)
    assert (alone.generate_calls_max, alone.wall_clock_max_seconds) == (675, 58320)
    assert STORY_SHARE < STORY_ONLY_SHARE < 1
    small = drafted.model_copy(update={"generate_calls_max": 300, "wall_clock_max_seconds": 1000})
    assert story_limits(_policy(), small, share=STORY_ONLY_SHARE).generate_calls_max == 300
