"""Owner adapters from a run's idea to a committed manuscript handed to the video flow.

- ``BRIEF``: draft the brief from the run's idea and frozen writer route, store its exact bytes and
  greenlight that digest at Gate A under the run's automation grant.
- ``STORY``: start the greenlit story run; it passes only when the story owner offers a manifest
  (``READY_FOR_APPROVAL``). A succeeded queue task never stands in for the story phase.
- ``STORY_COMMIT``: approve the offered manifest through ``AutomaticNarrativeAuthority``. A manifest with offered
  exceptions or open findings is never approved automatically.
- ``HANDOFF``: hand the committed manuscript to the project's sources once.

The story keeps its own limits; they are cut from the run's caps, and the parent run settles the story step once
from the story's own charged usage, so story calls are never debited twice.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from lib.db.repositories.production_runs import ProductionRunRepository
from lib.db.repositories.task_repo import TaskRepository
from lib.project_manager import ProjectManager
from lib.text_backends.ollama import OllamaChatClient
from r2.contracts.automation import (
    BudgetReservation,
    DispatchIntent,
    OwnerReceipt,
    RunCommand,
    RunPolicy,
    RunScope,
    RunSnapshot,
    RunStage,
    StageOutcome,
    UsageReceipt,
)
from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError
from server.production_run.greenlight_authority import greenlight_automatically, greenlight_subject_digest
from server.production_run.narrative_authority import AutomaticNarrativeAuthority
from server.production_run.owner_support import (
    OwnerBlocked,
    Sessions,
    current_run,
    current_subject,
    outcome,
    required_receipt,
    route_for,
    start_command,
    usage_receipt,
)
from server.production_run.owner_tasks import actor_scope, sub_command
from server.production_run.ports import StepPlan
from server.services.automation_grants import RunAutomationAuthority
from server.story_authoring.artifacts import BlobStoreError, StoryBlobStore
from server.story_authoring.book import BookSpec
from server.story_authoring.commit import CANON_BASE_MOVED, CommitRefused, load_offered_manifest
from server.story_authoring.contracts import StoryLimits, StoryScope
from server.story_authoring.driver import StoryBrief, run_call_bound
from server.story_authoring.handoff import STORY_SOURCE_LANGUAGE, HandoffRefused, SourceUpload, send_to_video
from server.story_authoring.idea_draw import DRAW_ATTEMPTS, recent_ideas
from server.story_authoring.idea_profile import (
    DrawRecord,
    ProfileRefused,
    ProjectProfile,
    profile_idea,
    profile_pin,
    profile_seed,
    record_bytes,
    record_profile,
)
from server.story_authoring.runtime import BudgetUsage, RunPhase, RunState, RunStateStore
from server.story_authoring.service import (
    SECONDS_PER_CALL,
    StoryActionRefused,
    StoryAuthoringService,
    brief_idea,
    run_id_for,
)

STORY_GENRE = "truyện ngắn"
# Share of the run's caps the story may spend; the rest belongs to script, media and Quality.
STORY_SHARE = 0.5
# Part sizes a story-only run tries, largest first, so the part's whole bound fits the run's caps (ADR-0127).
PART_SIZES = (5, 4, 3)
_FINISHED_TASK = frozenset({"succeeded", "failed", "cancelled"})


def brief_bytes(brief: StoryBrief) -> bytes:
    """The exact bytes whose sha256 is ``brief.digest()``; stored so later stages read the greenlit brief itself."""
    content = brief.model_dump(mode="json", exclude={"gate_a_decision_id"})
    return json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def story_limits(policy: RunPolicy, drafted: StoryLimits, *, share: float = STORY_SHARE) -> StoryLimits:
    """The drafted story limits, cut to the story's share of the run caps; never larger than drafted."""
    calls = max(1, math.floor(policy.max_model_calls * share) // 2)
    seconds = max(1, math.floor(policy.max_runtime_seconds * share))
    values = drafted.model_dump()
    values["generate_calls_max"] = min(drafted.generate_calls_max, calls)
    values["count_calls_max"] = min(drafted.count_calls_max, calls)
    values["wall_clock_max_seconds"] = min(drafted.wall_clock_max_seconds, seconds)
    if drafted.cloud_prices is not None:
        values["max_cost_minor_units"] = min(
            drafted.max_cost_minor_units, max(1, math.floor(policy.max_cost_minor_units * share))
        )
    return StoryLimits.model_validate({**values, "cloud_prices": drafted.cloud_prices})


def fits_run(policy: RunPolicy, limits: StoryLimits, *, spent_calls: int = 0) -> bool:
    """Whether a story's whole call bound (and cost cap) fits what the run's caps leave after ``spent_calls``: a
    story-only run keeps that bound uncut, so its caps stop only a fault, never a story still converging."""
    if spent_calls + limits.generate_calls_max + limits.count_calls_max > policy.max_model_calls:
        return False
    return limits.cloud_prices is None or limits.max_cost_minor_units <= policy.max_cost_minor_units


def whole_story(policy: RunPolicy, drafted: StoryLimits, *, spent_seconds: int = 0) -> StoryLimits:
    """A story-only run's limits: the drafted bound uncut; its model time is the run's own time cap, as the bound's
    seconds per call are only an estimate of the writer's pace."""
    seconds = max(1, policy.max_runtime_seconds - spent_seconds)
    return drafted.model_copy(update={"wall_clock_max_seconds": seconds})


#: Times one story is topped up before its budget block waits for a Showrunner (ADR-0127).
TOP_UP_LIMIT = 2


def _grown(limits: StoryLimits, *, calls: int, seconds: int) -> StoryLimits:
    per_call_in, per_call_out = limits.max_input_tokens, limits.max_output_tokens
    return limits.model_copy(
        update={
            "generate_calls_max": limits.generate_calls_max + calls,
            "count_calls_max": limits.count_calls_max + calls,
            "input_tokens_max": limits.input_tokens_max + calls * per_call_in,
            "output_tokens_max": limits.output_tokens_max + calls * per_call_out,
            "wall_clock_max_seconds": limits.wall_clock_max_seconds + seconds,
        }
    )


def _since_top_up(state: RunState, receipt_ref: str) -> BudgetUsage:
    """What the story spent under the step whose receipt names a top-up: its usage less the usage at that top-up."""
    _run, _sep, tag = receipt_ref.partition("#top-up-")
    if not tag:
        return state.usage
    base = state.top_ups[int(tag) - 1].baseline
    used = state.usage
    return BudgetUsage(
        count_calls=used.count_calls - base.count_calls,
        generate_calls=used.generate_calls - base.generate_calls,
        input_tokens=used.input_tokens - base.input_tokens,
        output_tokens=used.output_tokens - base.output_tokens,
        model_milliseconds=used.model_milliseconds - base.model_milliseconds,
    )


def _blobs(projects: ProjectManager, project_name: str) -> StoryBlobStore:
    return StoryBlobStore(projects.get_project_path(project_name))


def _read_record(blobs: StoryBlobStore, digest: str) -> DrawRecord:
    try:
        return DrawRecord.model_validate_json(blobs.read_exact(digest))
    except (BlobStoreError, ValueError):
        raise OwnerBlocked("STORY_PROFILE_UNAVAILABLE") from None


def _load_brief(projects: ProjectManager, project_name: str, digest: str) -> StoryBrief:
    try:
        brief = StoryBrief.model_validate_json(_blobs(projects, project_name).read_exact(digest))
    except Exception:
        raise OwnerBlocked("STORY_BRIEF_UNAVAILABLE") from None
    if brief.digest() != digest:
        raise OwnerBlocked("STORY_BRIEF_UNAVAILABLE")
    return brief


class BriefAdapter:
    owner = "story-brief"

    def __init__(
        self,
        sessions: Sessions,
        *,
        authority: RunAutomationAuthority,
        stories: StoryAuthoringService,
        projects: ProjectManager,
        client_for: Callable[[str, str | None], OllamaChatClient] | None = None,
    ) -> None:
        self._sessions, self._authority, self._stories, self._projects = sessions, authority, stories, projects
        self._client_for = client_for

    async def plan(self, *, run: RunSnapshot) -> StepPlan:
        writer = route_for(run, "writer")
        if writer is None:
            raise OwnerBlocked("MISSING_MODEL_ROLE")
        async with self._sessions() as session:
            command = await ProductionRunRepository(session).start_command(
                RunScope(user_id=run.user_id, project_name=run.project_name, run_id=run.run_id)
            )
        if command.idea_mode != "auto":
            return StepPlan(
                unit_key="brief",
                estimated_cost_minor_units=0,
                estimated_model_calls=0,
                estimated_tasks=0,
                estimated_runtime_seconds=10,
            )
        # ADR-0125: the drawn idea spends up to DRAW_ATTEMPTS generations, each with its count call.
        try:
            cost = await self._stories.draw_cost_bound(provider_id=writer[0], model_id=writer[1])
        except StoryActionRefused as refused:
            raise OwnerBlocked(refused.code) from None
        return StepPlan(
            unit_key="brief",
            estimated_cost_minor_units=cost,
            estimated_model_calls=DRAW_ATTEMPTS * 2,
            estimated_tasks=0,
            estimated_runtime_seconds=10 + DRAW_ATTEMPTS * SECONDS_PER_CALL,
        )

    async def _profile(
        self, intent: DispatchIntent, run: RunSnapshot, command: RunCommand, writer: tuple[str, str]
    ) -> ProjectProfile:
        """The run's drawn profile: the one pinned for the run, else a new draw pinned before the brief is drafted."""
        blobs = _blobs(self._projects, run.project_name)
        key = profile_pin(run.run_id)
        try:
            pinned = blobs.pinned(key)
        except BlobStoreError:
            raise OwnerBlocked("STORY_PROFILE_UNAVAILABLE") from None
        if pinned is None:
            avoid = await asyncio.to_thread(recent_ideas, self._projects, exclude=run.project_name)
            try:
                drawn = await self._stories.draw_profile(
                    provider_id=writer[0],
                    model_id=writer[1],
                    max_cost_minor_units=run.policy.max_cost_minor_units,
                    scope=StoryScope(user_id=run.user_id, project_name=run.project_name, actor_id=actor_scope(intent)),
                    draw_key=command.command_id,
                    seed=profile_seed(command.command_id),
                    avoid=avoid,
                    book_chapters=command.book_chapters,
                    client_for=self._client_for,
                )
            except (StoryActionRefused, ProfileRefused) as refused:
                raise OwnerBlocked(refused.code) from None
            record = DrawRecord(
                profile=drawn.profile,
                model_calls=drawn.usage.model_calls,
                cost_minor_units=drawn.usage.cost_minor_units,
                runtime_seconds=drawn.usage.runtime_seconds,
            )
            try:
                pinned = blobs.pin(key, blobs.put(record_bytes(record)))
            except BlobStoreError:
                raise OwnerBlocked("STORY_PROFILE_UNAVAILABLE") from None
        profile = _read_record(blobs, pinned).profile
        try:
            await asyncio.to_thread(record_profile, self._projects, run.project_name, run.run_id, profile)
        except (OSError, ValueError):
            raise OwnerBlocked("STORY_PROFILE_UNAVAILABLE") from None
        return profile

    async def dispatch(self, intent: DispatchIntent) -> OwnerReceipt:
        run = await current_run(self._sessions, intent)
        command = await start_command(self._sessions, intent)
        # Quality reviewers never take part in writing, so the story's own reviews use the writer route.
        writer = route_for(run, "writer")
        if writer is None:
            raise OwnerBlocked("MISSING_MODEL_ROLE")
        # ADR-0115: a continuation reads this project's story; a variant reads its source project's.
        prior_mode: Literal["continuation", "variant"] | None = (
            "continuation"
            if command.story_source == "continue"
            else "variant"
            if command.story_source == "variant"
            else None
        )
        genre, book_chapters = STORY_GENRE, command.book_chapters
        if command.idea_mode == "auto":
            profile = await self._profile(intent, run, command, writer)
            idea = profile_idea(profile)
            genre, book_chapters = profile.pack().label, profile.book_chapters
        else:
            idea = brief_idea(command.idea, command.variant_profile)
        story_only = command.end_stage == "HANDOFF"
        sizes = PART_SIZES if story_only and book_chapters is not None else (None,)
        drafted = None
        for size in sizes:
            book = None
            if book_chapters is not None:
                book = BookSpec(chapters=book_chapters, **({} if size is None else {"part_chapters": size}))
            try:
                drafted = await self._stories.draft_brief(
                    idea=idea,
                    genre=genre,
                    provider_id=writer[0],
                    model_id=writer[1],
                    max_cost_minor_units=max(1, min(10_000, run.policy.max_cost_minor_units)),
                    project_name=run.project_name,
                    prior_mode=prior_mode,
                    prior_project=command.source_project,
                    prior_origin=command.variant_profile or "instruction",
                    book=book,
                    user_id=run.user_id,
                )
            except StoryActionRefused as refused:
                raise OwnerBlocked(refused.code) from None
            if not story_only or fits_run(run.policy, drafted.limits, spent_calls=DRAW_ATTEMPTS * 2):
                break
        assert drafted is not None
        if drafted.limits.cloud_prices is not None and run.policy.currency != "USD":
            raise OwnerBlocked("CURRENCY_MISMATCH")
        if story_only:
            # ADR-0127: a story-only run keeps its story's whole structural bound; caps that cannot hold even the
            # smallest part stop the run now instead of hours into it.
            if not fits_run(run.policy, drafted.limits, spent_calls=DRAW_ATTEMPTS * 2):
                raise OwnerBlocked("RUN_CAPS_BELOW_STORY_BOUND")
            brief = drafted.model_copy(
                update={"limits": whole_story(run.policy, drafted.limits, spent_seconds=10 + DRAW_ATTEMPTS * 120)}
            )
        else:
            brief = drafted.model_copy(update={"limits": story_limits(run.policy, drafted.limits)})
        brief = StoryBrief.model_validate(brief.model_dump(mode="json"))
        digest = _blobs(self._projects, run.project_name).put(brief_bytes(brief))
        if digest != brief.digest():
            raise OwnerBlocked("STORY_BRIEF_UNAVAILABLE")
        subject = await current_subject(
            self._sessions, intent, subject_digest=greenlight_subject_digest(source_digest=digest)
        )
        decision = await greenlight_automatically(
            sessions=self._sessions, authority=self._authority, subject=subject, source_digest=digest
        )
        return OwnerReceipt(owner=self.owner, receipt_ref=decision.decision_id, digest=digest)

    async def inspect(self, *, intent: DispatchIntent, receipt: OwnerReceipt) -> StageOutcome:
        _load_brief(self._projects, intent.scope.project_name, receipt.digest)
        return outcome(intent, "PASS", receipts=(receipt,), owner_state="GREENLIT")

    async def usage(self, *, receipt: OwnerReceipt, reservation: BudgetReservation) -> UsageReceipt | None:
        """A drawn idea's calls, cost and time are the step's usage; a brief from a given idea spends none."""
        blobs = _blobs(self._projects, reservation.scope.project_name)
        try:
            pinned = blobs.pinned(profile_pin(reservation.scope.run_id))
            record = None if pinned is None else _read_record(blobs, pinned)
        except (BlobStoreError, OwnerBlocked):
            return usage_receipt(receipt, reservation, known=False)
        if record is None:
            return usage_receipt(receipt, reservation)
        return usage_receipt(
            receipt,
            reservation,
            cost_minor_units=record.cost_minor_units,
            model_calls=record.model_calls,
            runtime_seconds=record.runtime_seconds,
        )


class StoryAdapter:
    owner = "story-run"

    def __init__(
        self,
        sessions: Sessions,
        *,
        authority: RunAutomationAuthority,
        stories: StoryAuthoringService,
        projects: ProjectManager,
    ) -> None:
        self._sessions, self._authority, self._stories, self._projects = sessions, authority, stories, projects

    async def _brief(self, run: RunSnapshot) -> tuple[OwnerReceipt, StoryBrief]:
        greenlight = await required_receipt(self._sessions, run, RunStage.BRIEF)
        return greenlight, _load_brief(self._projects, run.project_name, greenlight.digest)

    async def plan(self, *, run: RunSnapshot) -> StepPlan:
        greenlight, brief = await self._brief(run)
        blocked = await self._blocked_story(run, greenlight)
        if blocked is not None:
            target = await self._top_up_target(run, blocked, brief)
            if target is None:
                raise OwnerBlocked("STORY_BUDGET_EXHAUSTED")
            before = blocked.limits
            return StepPlan(
                unit_key="story",
                input_refs=(greenlight,),
                estimated_cost_minor_units=0,
                estimated_model_calls=(target.generate_calls_max - before.generate_calls_max)
                + (target.count_calls_max - before.count_calls_max),
                estimated_tasks=1,
                estimated_runtime_seconds=target.wall_clock_max_seconds - before.wall_clock_max_seconds,
            )
        limits = brief.limits
        return StepPlan(
            unit_key="story",
            input_refs=(greenlight,),
            estimated_cost_minor_units=limits.max_cost_minor_units,
            estimated_model_calls=limits.generate_calls_max + limits.count_calls_max,
            estimated_tasks=1,
            estimated_runtime_seconds=limits.wall_clock_max_seconds,
        )

    async def dispatch(self, intent: DispatchIntent) -> OwnerReceipt:
        [greenlight] = intent.input_refs
        brief = _load_brief(self._projects, intent.scope.project_name, greenlight.digest)
        subject = await current_subject(self._sessions, intent, subject_digest=greenlight.digest)
        async with self._sessions() as session, session.begin():
            await self._authority.require_locked(session, subject=subject)
        try:
            ref = await self._stories.start_greenlit(
                user_id=intent.scope.user_id,
                project_name=intent.scope.project_name,
                brief=brief,
                gate_a_decision_id=greenlight.receipt_ref,
                command=(actor_scope(intent), sub_command(intent, "story")),
            )
        except StoryActionRefused as refused:
            raise OwnerBlocked(refused.code) from None
        state = await RunStateStore(self._sessions, task_id=ref.task_id).load()
        caller = intent.identity.command_id
        done = next((t for t in state.top_ups if t.caller_ref == caller), None)
        if done is None and state.phase is RunPhase.BLOCKED_BUDGET:
            # ADR-0127: this step reserved the difference; the story goes on from where it stopped.
            limits = _grown(
                state.limits,
                calls=intent.estimated_model_calls // 2,
                seconds=intent.estimated_runtime_seconds,
            )
            try:
                state = await self._stories.top_up(
                    user_id=intent.scope.user_id,
                    project_name=intent.scope.project_name,
                    run_id=ref.run_id,
                    caller_ref=caller,
                    limits=limits,
                )
            except StoryActionRefused as refused:
                raise OwnerBlocked(refused.code) from None
            done = next(t for t in state.top_ups if t.caller_ref == caller)
        receipt_ref = ref.run_id if done is None else f"{ref.run_id}#top-up-{done.number}"
        return OwnerReceipt(owner=self.owner, receipt_ref=receipt_ref, digest=greenlight.digest, task_id=ref.task_id)

    async def inspect(self, *, intent: DispatchIntent, receipt: OwnerReceipt) -> StageOutcome:
        state = await self._state(receipt)
        if state.phase is RunPhase.BLOCKED_BUDGET:
            run = await current_run(self._sessions, intent)
            [greenlight] = intent.input_refs
            brief = _load_brief(self._projects, intent.scope.project_name, greenlight.digest)
            if await self._top_up_target(run, state, brief) is not None:
                # The step settles what the story spent; the story stage runs again and tops the story up.
                passing = outcome(intent, "PASS", receipts=(receipt,), owner_state=state.phase.value).model_dump(
                    mode="python"
                )
                return StageOutcome.model_validate(
                    {**passing, "kind": "REWORK", "reason": "STORY_BUDGET_TOP_UP", "repair_stage": RunStage.STORY}
                )
        if state.phase is RunPhase.RUNNING:
            async with self._sessions() as session:
                task = await TaskRepository(session).get(str(receipt.task_id))
            if task is not None and task.get("status") in _FINISHED_TASK:
                return outcome(intent, "BLOCK", reason="OUTCOME_UNKNOWN", owner_state=state.phase.value)
            return outcome(intent, "WAIT", owner_state=state.phase.value)
        evidence = receipt
        if state.phase is RunPhase.READY_FOR_APPROVAL and state.commit is not None:
            evidence = receipt.model_copy(update={"digest": state.commit.offered_manifest_digest})
        # The phase decides; transitions turn any phase other than READY_FOR_APPROVAL into the run's block.
        return outcome(intent, "PASS", receipts=(evidence,), owner_state=state.phase.value)

    async def usage(self, *, receipt: OwnerReceipt, reservation: BudgetReservation) -> UsageReceipt | None:
        state = await self._state(receipt)
        used = _since_top_up(state, receipt.receipt_ref)
        prices = state.limits.cloud_prices
        return usage_receipt(
            receipt,
            reservation,
            cost_minor_units=prices.minor_units(used.input_tokens, used.output_tokens) if prices else 0,
            model_calls=used.generate_calls + used.count_calls,
            tasks=1,
            runtime_seconds=math.ceil(used.model_milliseconds / 1000),
            known=state.phase is not RunPhase.RECOVERY_INCONSISTENT,
        )

    async def _blocked_story(self, run: RunSnapshot, greenlight: OwnerReceipt) -> RunState | None:
        """The run's story when an earlier attempt of the stage left it blocked on its budget."""
        try:
            _ref, state = await self._stories.get(
                user_id=run.user_id, project_name=run.project_name, run_id=run_id_for(greenlight.receipt_ref)
            )
        except StoryActionRefused:
            return None
        return state if state.phase is RunPhase.BLOCKED_BUDGET else None

    async def _top_up_target(self, run: RunSnapshot, state: RunState, brief: StoryBrief) -> StoryLimits | None:
        """ADR-0127: a story on a free route whose limits were set below its structural bound goes on up to that
        bound, within what the run's own caps leave, at most TOP_UP_LIMIT times. A paid route never spends more
        than its approved cap without a Showrunner."""
        reworks = sum(r.count for r in run.repair_counts if r.stage is RunStage.STORY)
        if (
            state.limits.cloud_prices is not None
            or len(state.top_ups) >= TOP_UP_LIMIT
            or reworks >= run.policy.unit_repair_limit
        ):
            return None
        bound = run_call_bound(state.limits.chapters, book=brief.book)
        if state.limits.generate_calls_max >= bound:
            return None
        async with self._sessions() as session:
            _cost, calls, _tasks, seconds = await ProductionRunRepository(session).usage_totals(
                RunScope(user_id=run.user_id, project_name=run.project_name, run_id=run.run_id)
            )
        room_calls = max(0, run.policy.max_model_calls - calls) // 2
        room_seconds = max(0, run.policy.max_runtime_seconds - seconds)
        extra = min(bound - state.limits.generate_calls_max, room_calls)
        if extra <= 0 or room_seconds <= 0:
            return None
        return _grown(state.limits, calls=extra, seconds=room_seconds)

    async def _state(self, receipt: OwnerReceipt) -> RunState:
        return await RunStateStore(self._sessions, task_id=str(receipt.task_id)).load()


class StoryCommitAdapter:
    owner = "story-commit"

    def __init__(
        self,
        sessions: Sessions,
        *,
        authority: RunAutomationAuthority,
        stories: StoryAuthoringService,
        projects: ProjectManager,
    ) -> None:
        self._sessions, self._authority, self._stories, self._projects = sessions, authority, stories, projects

    async def plan(self, *, run: RunSnapshot) -> StepPlan:
        story = await required_receipt(self._sessions, run, RunStage.STORY)
        state = await RunStateStore(self._sessions, task_id=str(story.task_id)).load()
        if state.phase is not RunPhase.READY_FOR_APPROVAL or state.commit is None:
            raise OwnerBlocked("STORY_NOT_OFFERED")
        # The commit is bound to the manifest offered when the story stage passed; a later revision blocks it.
        offered = story.model_copy(update={"digest": state.commit.offered_manifest_digest})
        return StepPlan(
            unit_key="story-commit",
            input_refs=(offered,),
            estimated_cost_minor_units=0,
            estimated_model_calls=0,
            estimated_tasks=0,
            estimated_runtime_seconds=120,
        )

    async def dispatch(self, intent: DispatchIntent) -> OwnerReceipt:
        [story] = intent.input_refs
        scope = intent.scope
        state = await RunStateStore(self._sessions, task_id=str(story.task_id)).load()
        if state.commit is None or state.commit.offered_manifest_digest != story.digest:
            raise OwnerBlocked("EXTERNAL_INPUT_CHANGED")
        if state.phase is RunPhase.COMMITTED:
            # Committed by an earlier attempt of this step or by the Showrunner on the story owner.
            return story.model_copy(update={"owner": self.owner})
        blobs = _blobs(self._projects, scope.project_name)
        manifest = load_offered_manifest(blobs, state)
        quality = blobs.read_exact(manifest.quality_record_digest) if manifest.quality_record_digest else None
        subject = await current_subject(self._sessions, intent, subject_digest=manifest.digest())
        try:
            narrative = await AutomaticNarrativeAuthority.bind(
                sessions=self._sessions,
                authority=self._authority,
                subject=subject,
                manifest=manifest,
                quality_record=quality,
            )
        except NarrativeDecisionAuthorizationError as refused:
            reason = str(refused)
            if "UNRESOLVED_STORY_FINDINGS" in reason:
                raise OwnerBlocked("STORY_FINDINGS_NOT_RECORDED") from None
            if "AUTOMATION_AUTHORITY_NOT_CURRENT" in reason:
                raise OwnerBlocked("AUTOMATION_GRANT_NOT_CURRENT") from None
            raise OwnerBlocked("STORY_MANIFEST_BINDING_MISMATCH") from None
        committer = await self._stories.committer(
            user_id=scope.user_id, project_name=scope.project_name, run_id=story.receipt_ref
        )
        try:
            await committer.approve_automatically(narrative=narrative, manifest_digest_seen=story.digest)
        except CommitRefused as refused:
            raise OwnerBlocked(f"STORY_COMMIT_{refused.code.value}") from None
        return story.model_copy(update={"owner": self.owner})

    async def inspect(self, *, intent: DispatchIntent, receipt: OwnerReceipt) -> StageOutcome:
        state = await RunStateStore(self._sessions, task_id=str(receipt.task_id)).load()
        if state.phase is RunPhase.COMMIT_BLOCKED:
            # A story whose project MAIN Canon was taken first needs its story run retried (rebased) by a Showrunner.
            reason = (
                "STORY_CANON_BASE_MOVED" if CANON_BASE_MOVED in (state.block_reason or "") else "STORY_COMMIT_BLOCKED"
            )
            return outcome(intent, "BLOCK", reason=reason, owner_state=state.phase.value)
        if state.phase in {RunPhase.APPROVING, RunPhase.PARTIALLY_COMMITTED}:
            return outcome(intent, "BLOCK", reason="OUTCOME_UNKNOWN", owner_state=state.phase.value)
        return outcome(intent, "PASS", receipts=(receipt,), owner_state=state.phase.value)

    async def usage(self, *, receipt: OwnerReceipt, reservation: BudgetReservation) -> UsageReceipt | None:
        return usage_receipt(receipt, reservation)


class HandoffAdapter:
    owner = "story-handoff"

    def __init__(
        self,
        sessions: Sessions,
        *,
        authority: RunAutomationAuthority,
        projects: ProjectManager,
        upload_for: Callable[[DispatchIntent], SourceUpload],
    ) -> None:
        self._sessions, self._authority, self._projects = sessions, authority, projects
        self._upload_for = upload_for

    async def plan(self, *, run: RunSnapshot) -> StepPlan:
        commit = await required_receipt(self._sessions, run, RunStage.STORY_COMMIT)
        return StepPlan(
            unit_key="handoff",
            input_refs=(commit,),
            estimated_cost_minor_units=0,
            estimated_model_calls=0,
            estimated_tasks=0,
            estimated_runtime_seconds=30,
        )

    async def dispatch(self, intent: DispatchIntent) -> OwnerReceipt:
        [commit] = intent.input_refs
        project_name = intent.scope.project_name
        store = RunStateStore(self._sessions, task_id=str(commit.task_id))
        state = await store.load()
        if state.phase is not RunPhase.COMMITTED or state.commit is None:
            raise OwnerBlocked("STORY_NOT_COMMITTED")
        blobs = _blobs(self._projects, project_name)
        export_digest = load_offered_manifest(blobs, state).export_digest
        subject = await current_subject(self._sessions, intent, subject_digest=export_digest)
        async with self._sessions() as session, session.begin():
            await self._authority.require_locked(session, subject=subject)
        try:
            record = await send_to_video(
                store=store,
                blobs=blobs,
                project=self._projects.load_project(project_name),
                source_dir=self._projects.get_project_path(project_name) / "source",
                command_id=intent.identity.command_id,
                upload=self._upload_for(intent),
                on_conflict="rename",
                after_existing=(await start_command(self._sessions, intent)).story_source == "continue",
            )
        except HandoffRefused as refused:
            raise OwnerBlocked(f"HANDOFF_{refused.code.value}") from None

        def record_language(project: dict) -> None:
            if not isinstance(project.get("source_language"), str) or not project["source_language"].strip():
                project["source_language"] = STORY_SOURCE_LANGUAGE

        self._projects.update_project(project_name, record_language)
        return OwnerReceipt(
            owner=self.owner, receipt_ref=str(record.path), digest=export_digest, task_id=commit.task_id
        )

    async def inspect(self, *, intent: DispatchIntent, receipt: OwnerReceipt) -> StageOutcome:
        state = await RunStateStore(self._sessions, task_id=str(receipt.task_id)).load()
        handoff = state.handoff
        if handoff is None or not handoff.done or handoff.path != receipt.receipt_ref:
            return outcome(intent, "BLOCK", reason="OUTCOME_UNKNOWN")
        source = self._projects.get_project_path(intent.scope.project_name) / Path(receipt.receipt_ref)
        if not source.is_file():
            return outcome(intent, "BLOCK", reason="EXTERNAL_INPUT_CHANGED")
        return outcome(intent, "PASS", receipts=(receipt,), owner_state="HANDED_OFF")

    async def usage(self, *, receipt: OwnerReceipt, reservation: BudgetReservation) -> UsageReceipt | None:
        return usage_receipt(receipt, reservation)


__all__ = [
    "PART_SIZES",
    "STORY_SHARE",
    "BriefAdapter",
    "HandoffAdapter",
    "StoryAdapter",
    "StoryCommitAdapter",
    "brief_bytes",
    "fits_run",
    "story_limits",
    "whole_story",
]
