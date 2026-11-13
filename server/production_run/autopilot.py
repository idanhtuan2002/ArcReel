"""ADR-0124: start each enabled project's next run without a click, under its standing autopilot delegation.

A story project writes its book part after part; a film project films its linked story, syncing the story's new
parts first. A project's autopilot waits while the project has an active run and halts when its own last run did
not succeed; the Showrunner resolves that run (or turns autopilot off and on again) and the next scan continues.
The database is the recovery path: a start's command is derived from the delegation and its run count, so a
scan repeated after a crash replays the same run.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.autopilot import AutopilotRepository
from lib.db.repositories.production_runs import ProductionRunRepository
from lib.project_kinds import linked_story
from r2.contracts.automation import RunCommand, RunSnapshot, RunStatus
from r2.contracts.autopilot import AutopilotDelegation, autopilot_command_id, autopilot_command_prefix
from server.production_run.alerts import AlertGate, Alerts
from server.story_authoring.idea_profile import PROFILE_SETTING

logger = logging.getLogger(__name__)

_EPISODE = "episode:"
_PART = re.compile(r":p([0-9]+)$")


class StartsDelegatedRuns(Protocol):
    async def start_delegated(self, *, delegation: AutopilotDelegation, command: RunCommand) -> RunSnapshot: ...

    async def input_digest(self, *, user_id: str, project_name: str) -> str: ...

    async def has_story(self, project_name: str) -> bool: ...


@dataclass(frozen=True)
class BookParts:
    done: int
    total: int


@dataclass(frozen=True)
class AutopilotState:
    """What the project's autopilot does next: ``waiting`` for its active run, ``halted`` on its last run,
    ``finished`` (nothing left to write or film), or ``ready`` to start."""

    state: Literal["off", "waiting", "halted", "finished", "ready"]
    run_id: str | None = None
    reason: str | None = None


def _prefix(delegation: AutopilotDelegation) -> str:
    return autopilot_command_prefix(delegation)


def _episode(target: str) -> int | None:
    if not target.startswith(_EPISODE):
        return None
    value = target.removeprefix(_EPISODE)
    return int(value) if value.isdigit() else None


class AutopilotPlanner:
    """Decides a project's next autopilot command from durable state only."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        service: StartsDelegatedRuns,
        *,
        load_project: Callable[[str], dict[str, Any]],
        book_parts: Callable[[str, str], Awaitable[BookParts | None]],
        unplanned_source: Callable[[str], bool],
        sync_story: Callable[[str, str], Awaitable[list[str]]],
        max_targets: Callable[[AutopilotDelegation], Awaitable[int]],
        story_busy: Callable[[str, str, str | None], Awaitable[bool]] | None = None,
    ) -> None:
        self._sessions = sessions
        self._service = service
        self._load_project = load_project
        self._book_parts = book_parts
        self._unplanned_source = unplanned_source
        self._sync_story = sync_story
        self._max_targets = max_targets
        self._story_busy = story_busy

    async def book_parts(self, user_id: str, project_name: str) -> BookParts | None:
        return await self._book_parts(user_id, project_name)

    async def sync_story(self, user_id: str, project_name: str) -> list[str]:
        return await self._sync_story(user_id, project_name)

    async def _runs(
        self, delegation: AutopilotDelegation
    ) -> tuple[bool, list[tuple[str, RunSnapshot]], list[RunSnapshot]]:
        async with self._sessions() as session:
            repository = ProductionRunRepository(session)
            active = await repository.has_active(user_id=delegation.user_id, project_name=delegation.project_name)
            own = await repository.started_by(
                user_id=delegation.user_id, project_name=delegation.project_name, command_prefix=_prefix(delegation)
            )
            every = await repository.list_for_project(user_id=delegation.user_id, project_name=delegation.project_name)
        return active, own, every

    async def state(
        self, delegation: AutopilotDelegation, *, preview: bool = False
    ) -> tuple[AutopilotState, RunCommand | None]:
        """``preview`` (a reader's view) writes nothing: a film's story is synced only before a start."""
        if delegation.state != "ENABLED":
            return AutopilotState("off"), None
        active, own, every = await self._runs(delegation)
        if active:
            running = next((run for run in every if run.status not in _TERMINAL), None)
            if running is not None and running.status in _STOPPED:
                # A blocked or paused run waits for the Showrunner, not for time: the autopilot is halted on it.
                return AutopilotState("halted", running.run_id, running.reason or running.status.value), None
            return AutopilotState("waiting", running.run_id if running else None), None
        if own and own[-1][1].status is not RunStatus.SUCCEEDED:
            last = own[-1][1]
            return AutopilotState("halted", last.run_id, last.reason or last.status.value), None
        if (
            delegation.kind == "story"
            and self._story_busy is not None
            and await self._story_busy(
                delegation.user_id, delegation.project_name, delegation.story.idea if delegation.story else None
            )
        ):
            # Another story run of the project is unfinished (ADR-0124 §3).
            return AutopilotState("waiting", None, "STORY_RUN_UNFINISHED"), None
        try:
            command = (
                await self._story_command(delegation, own)
                if delegation.kind == "story"
                else await self._film_command(delegation, len(own), every, preview=preview)
            )
        except AutopilotHalted as halt:
            return AutopilotState("halted", None, str(halt)), None
        if command is None:
            return AutopilotState("finished"), None
        return AutopilotState("ready"), command

    async def _base(self, delegation: AutopilotDelegation, ordinal: int, part: int | None = None) -> dict[str, Any]:
        return {
            "user_id": delegation.user_id,
            "project_name": delegation.project_name,
            "command_id": autopilot_command_id(delegation, ordinal, part=part),
            "action": "START",
            "expected_version": 0,
            "expected_input_digest": await self._service.input_digest(
                user_id=delegation.user_id, project_name=delegation.project_name
            ),
            "policy_digest": delegation.policy_digest,
            "mode": delegation.mode,
        }

    async def _story_command(
        self, delegation: AutopilotDelegation, own: list[tuple[str, RunSnapshot]]
    ) -> RunCommand | None:
        assert delegation.story is not None
        parts = await self._book_parts(delegation.user_id, delegation.project_name)
        done = 0 if parts is None else parts.done
        if own:
            # The last part this delegation wrote must show in the book before the next is written; otherwise every
            # scan would pay for the same part again.
            match = _PART.search(own[-1][0])
            if match is None or done < int(match.group(1)):
                raise AutopilotHalted("PART_NOT_RECORDED")
        if parts is None:
            if await self._service.has_story(delegation.project_name):
                # The project holds a story that is not a book: autopilot does not write another one over it.
                raise AutopilotHalted("STORY_WITHOUT_BOOK")
            base = await self._base(delegation, len(own) + 1, part=1)
            story = delegation.story
            idea: dict[str, object] = {"idea": story.idea} if story.idea is not None else {"idea_mode": "auto"}
            chapters = story.book_chapters
            if story.idea is None:
                # An idea drawn for this project earlier (an autopilot turned off and on again before part 1 was
                # committed) is written again rather than replaced by a new one.
                project = await asyncio.to_thread(self._load_project, delegation.project_name)
                drawn = project.get(PROFILE_SETTING)
                if isinstance(drawn, dict) and isinstance(drawn.get("idea"), str) and drawn["idea"].strip():
                    idea = {"idea": _drawn_idea(drawn)}
                    if chapters is None and isinstance(drawn.get("book_chapters"), int):
                        chapters = drawn["book_chapters"]
            return RunCommand.model_validate({**base, **idea, "book_chapters": chapters, "end_stage": "HANDOFF"})
        if parts.done >= parts.total:
            return None
        base = await self._base(delegation, len(own) + 1, part=parts.done + 1)
        return RunCommand.model_validate(
            {**base, "story_source": "continue", "idea": delegation.story.direction, "end_stage": "HANDOFF"}
        )

    async def _film_command(
        self, delegation: AutopilotDelegation, started: int, every: list[RunSnapshot], *, preview: bool
    ) -> RunCommand | None:
        assert delegation.film is not None
        project = await asyncio.to_thread(self._load_project, delegation.project_name)
        if linked_story(project) is not None and not preview:
            conflicts = await self._sync_story(delegation.user_id, delegation.project_name)
            if conflicts:
                raise AutopilotHalted("STORY_SYNC_CONFLICT")
            project = await asyncio.to_thread(self._load_project, delegation.project_name)
        if not await self._service.has_story(delegation.project_name):
            return None
        filmed = {
            number
            for run in every
            if run.status is RunStatus.SUCCEEDED
            for output in run.completed_targets
            if (number := _episode(output.target)) is not None
        }
        episodes = project.get("episodes")
        planned = sorted(
            {
                entry["episode"]
                for entry in (episodes if isinstance(episodes, list) else [])
                if isinstance(entry, dict) and isinstance(entry.get("episode"), int)
            }
        )
        limit = min(delegation.film.episodes_per_run, await self._max_targets(delegation))
        pending = [number for number in planned if number not in filmed][:limit]
        if not pending:
            if planned and not await asyncio.to_thread(self._unplanned_source, delegation.project_name):
                return None
            pending = [max([0, *planned, *filmed]) + 1]
        base = await self._base(delegation, started + 1)
        return RunCommand.model_validate(
            {**base, "story_source": "project", "targets": tuple(f"{_EPISODE}{n}" for n in pending)}
        )


_TERMINAL = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.FAILED_QUALITY, RunStatus.CANCELLED}
#: Unfinished runs that only a Showrunner's action moves on.
_STOPPED = {
    RunStatus.PAUSED,
    RunStatus.BLOCKED_CONFIGURATION,
    RunStatus.BLOCKED_RESOURCE,
    RunStatus.BLOCKED_BUDGET,
    RunStatus.BLOCKED_UNKNOWN,
    RunStatus.BLOCKED_INPUT_CHANGED,
}


def _drawn_idea(drawn: dict[str, Any]) -> str:
    """The brief idea of a profile drawn earlier, with its tone and readers as the drawn run wrote them."""
    text = str(drawn["idea"]).strip()
    tone, audience = drawn.get("tone"), drawn.get("audience")
    if isinstance(tone, str) and isinstance(audience, str):
        text += f"\n\nGiọng điệu: {tone}. Độc giả: {audience}."
    return text[:4000]


class AutopilotHalted(Exception):
    """The project's autopilot cannot continue until the Showrunner acts."""


def _refusal_text(error: Exception) -> str:
    code = getattr(error, "code", None) or str(error) or type(error).__name__
    reasons = getattr(error, "reasons", ())
    return f"{code}: {', '.join(reasons)}" if reasons else str(code)


class AutopilotScheduler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        service: StartsDelegatedRuns,
        planner: AutopilotPlanner,
        *,
        interval_seconds: float = 60.0,
        page_size: int = 64,
        alerts: Alerts | None = None,
    ) -> None:
        self._sessions = sessions
        self._service = service
        self._planner = planner
        self._interval_seconds = interval_seconds
        self._page_size = page_size
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        #: Why each project's last start was refused (policy or input moved, preflight blocked), until one starts.
        self._refusals: dict[tuple[str, str], str] = {}
        self._alerts = AlertGate(alerts)

    @property
    def planner(self) -> AutopilotPlanner:
        return self._planner

    def refusal(self, user_id: str, project_name: str) -> str | None:
        return self._refusals.get((user_id, project_name))

    async def step(self, delegation: AutopilotDelegation) -> RunSnapshot | None:
        """Start the project's next run if it is ready; returns the run started (or replayed)."""
        state, command = await self._planner.state(delegation)
        if state.state != "ready":
            # A ready project keeps its last alert: a start refused again on the next scan is not a new state.
            await self._alerts.observe(
                user_id=delegation.user_id,
                project_name=delegation.project_name,
                event="halted" if state.state == "halted" else "finished" if state.state == "finished" else None,
                run_id=state.run_id,
                reason=state.reason,
            )
        if state.state != "ready" or command is None:
            return None
        return await self._service.start_delegated(delegation=delegation, command=command)

    async def scan_once(self) -> int:
        """Visit every enabled project once; returns how many runs were started."""
        started = 0
        after: tuple[str, str] | None = None
        while True:
            async with self._sessions() as session:
                page = await AutopilotRepository(session).enabled(limit=self._page_size, after=after)
            for delegation in page:
                key = (delegation.user_id, delegation.project_name)
                try:
                    if await self.step(delegation) is not None:
                        started += 1
                    self._refusals.pop(key, None)
                except Exception as error:
                    # Retried by a later scan; the project's autopilot shows why until a start succeeds.
                    self._refusals[key] = _refusal_text(error)
                    await self._alerts.observe(
                        user_id=delegation.user_id,
                        project_name=delegation.project_name,
                        event="refused",
                        reason=self._refusals[key],
                    )
                    logger.info("autopilot of %s did not start: %r", delegation.project_name, error)
            if len(page) < self._page_size:
                return started
            after = (page[-1].user_id, page[-1].project_name)

    def wake(self) -> None:
        self._wake_event.set()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="autopilot-scan")

    async def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._wake_event.clear()
            try:
                await self.scan_once()
            except Exception:
                logger.exception("autopilot scan failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake_event.wait(), timeout=self._interval_seconds)


__all__ = [
    "AutopilotHalted",
    "AutopilotPlanner",
    "AutopilotScheduler",
    "AutopilotState",
    "BookParts",
    "StartsDelegatedRuns",
]
