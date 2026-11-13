from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from server.production_run.composition import story_run_busy


@dataclass(frozen=True)
class _Ref:
    run_id: str


IDEA = "Một người con về làng bán căn nhà của cha."


def _brief(*, idea: str = IDEA, part: int | None = None, safety: str = "standard", prior: object = None):
    book = None if part is None else SimpleNamespace(part=part)
    return SimpleNamespace(idea=idea, book=book, content_safety=safety, prior=prior)


class _Stories:
    def __init__(self, runs: list[dict[str, Any]], stopped: tuple[str, Any, tuple[str, ...]] | None) -> None:
        self._runs, self._stopped = runs, stopped

    async def list_runs(self, *, user_id: str, project_name: str) -> list[dict[str, Any]]:
        del user_id, project_name
        return self._runs

    def content_safety(self, project_name: str) -> str:
        del project_name
        return "standard"

    async def adoptable(self, *, user_id: str, project_name: str, matches) -> object:
        del user_id, project_name
        if self._stopped is None:
            return None
        run_id, brief, owners = self._stopped
        return (_Ref(run_id), None, owners) if matches(brief) else None


RUNS = [{"run_id": "story-1", "phase": "MODEL_UNAVAILABLE"}, {"run_id": "story-0", "phase": "COMMITTED"}]
RUN_OWNERS = ("production-run:r1", "production-run:r2")


async def _busy(runs, stopped=None, idea: str | None = IDEA) -> bool:
    return await story_run_busy(_Stories(runs, stopped), "u", "p", idea)


async def test_a_story_the_next_autopilot_run_takes_over_does_not_keep_it_waiting():
    assert not await _busy(RUNS, ("story-1", _brief(), RUN_OWNERS))
    # A later part of a book is taken over whatever the autopilot's idea.
    assert not await _busy(RUNS, ("story-1", _brief(idea="other", part=2), RUN_OWNERS), idea=None)


async def test_a_story_the_next_run_would_not_take_over_keeps_the_autopilot_waiting():
    """ADR-0124 §3: one unfinished story per project; the next run would draft a second one beside it."""
    assert await _busy(RUNS, ("story-1", _brief(idea="another idea"), RUN_OWNERS))
    assert await _busy(RUNS, ("story-1", _brief(), RUN_OWNERS), idea=None)  # the autopilot draws its own idea
    assert await _busy(RUNS, ("story-1", _brief(safety="strict"), RUN_OWNERS))
    assert await _busy(RUNS, ("story-1", _brief(prior=object()), RUN_OWNERS))


async def test_a_story_a_showrunner_started_or_one_still_writing_keeps_the_autopilot_waiting():
    stopped = [{"run_id": "story-1", "phase": "BLOCKED_QUALITY"}]
    assert await _busy(stopped, ("story-1", _brief(), ("user:admin",)))
    assert await _busy(stopped, ("story-1", _brief(), ()))
    assert await _busy([{"run_id": "story-1", "phase": "RUNNING"}], None)
    two = [{"run_id": "story-2", "phase": "BLOCKED_BUDGET"}, {"run_id": "story-1", "phase": "BLOCKED_QUALITY"}]
    assert await _busy(two, ("story-2", _brief(), RUN_OWNERS))


async def test_ended_stories_are_not_busy():
    assert not await _busy([{"run_id": "story-1", "phase": "COMMITTED"}, {"run_id": "s0", "phase": "DISCARDED"}])
