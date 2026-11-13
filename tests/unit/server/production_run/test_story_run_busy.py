from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.production_run.composition import story_run_busy


@dataclass(frozen=True)
class _Ref:
    run_id: str


class _Stories:
    def __init__(self, runs: list[dict[str, Any]], adoptable: tuple[_Ref, object, tuple[str, ...]] | None) -> None:
        self._runs, self._adoptable = runs, adoptable

    async def list_runs(self, *, user_id: str, project_name: str) -> list[dict[str, Any]]:
        return self._runs

    async def adoptable(self, *, user_id: str, project_name: str, matches) -> object:
        return self._adoptable


async def _busy(runs: list[dict[str, Any]], adoptable=None) -> bool:
    return await story_run_busy(_Stories(runs, adoptable), "u", "p")


async def test_a_story_stopped_by_ended_automatic_runs_waits_for_the_run_that_takes_it_over():
    runs = [{"run_id": "story-1", "phase": "MODEL_UNAVAILABLE"}, {"run_id": "story-0", "phase": "COMMITTED"}]
    assert not await _busy(runs, (_Ref("story-1"), None, ("production-run:r1", "production-run:r2")))


async def test_a_story_a_showrunner_started_or_one_still_writing_keeps_the_autopilot_waiting():
    stopped = [{"run_id": "story-1", "phase": "BLOCKED_QUALITY"}]
    assert await _busy(stopped, (_Ref("story-1"), None, ("user:admin",)))
    assert await _busy(stopped, (_Ref("story-1"), None, ()))
    assert await _busy([{"run_id": "story-1", "phase": "RUNNING"}], None)
    two = [{"run_id": "story-2", "phase": "BLOCKED_BUDGET"}, {"run_id": "story-1", "phase": "BLOCKED_QUALITY"}]
    assert await _busy(two, (_Ref("story-2"), None, ("production-run:r1",)))


async def test_ended_stories_are_not_busy():
    assert not await _busy([{"run_id": "story-1", "phase": "COMMITTED"}, {"run_id": "s0", "phase": "DISCARDED"}])
