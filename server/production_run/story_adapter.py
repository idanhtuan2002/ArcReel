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

import json
import math
from collections.abc import Callable
from pathlib import Path

from lib.db.repositories.task_repo import TaskRepository
from lib.project_manager import ProjectManager
from r2.contracts.automation import (
    BudgetReservation,
    DispatchIntent,
    OwnerReceipt,
    RunPolicy,
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
from server.production_run.ports import StepPlan
from server.services.automation_grants import RunAutomationAuthority
from server.story_authoring.artifacts import StoryBlobStore
from server.story_authoring.commit import CommitRefused, load_offered_manifest
from server.story_authoring.contracts import StoryLimits
from server.story_authoring.driver import StoryBrief
from server.story_authoring.handoff import STORY_SOURCE_LANGUAGE, HandoffRefused, SourceUpload, send_to_video
from server.story_authoring.runtime import RunPhase, RunState, RunStateStore
from server.story_authoring.service import StoryActionRefused, StoryAuthoringService

STORY_GENRE = "truyện ngắn"
# Share of the run's caps the story may spend; the rest belongs to script, media and Quality.
STORY_SHARE = 0.5
_FINISHED_TASK = frozenset({"succeeded", "failed", "cancelled"})


def brief_bytes(brief: StoryBrief) -> bytes:
    """The exact bytes whose sha256 is ``brief.digest()``; stored so later stages read the greenlit brief itself."""
    content = brief.model_dump(mode="json", exclude={"gate_a_decision_id"})
    return json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def story_limits(policy: RunPolicy, drafted: StoryLimits) -> StoryLimits:
    """The drafted story limits, cut to the story's share of the run caps; never larger than drafted."""
    calls = max(1, math.floor(policy.max_model_calls * STORY_SHARE) // 2)
    seconds = max(1, math.floor(policy.max_runtime_seconds * STORY_SHARE))
    values = drafted.model_dump()
    values["generate_calls_max"] = min(drafted.generate_calls_max, calls)
    values["count_calls_max"] = min(drafted.count_calls_max, calls)
    values["wall_clock_max_seconds"] = min(drafted.wall_clock_max_seconds, seconds)
    if drafted.cloud_prices is not None:
        values["max_cost_minor_units"] = min(
            drafted.max_cost_minor_units, max(1, math.floor(policy.max_cost_minor_units * STORY_SHARE))
        )
    return StoryLimits.model_validate({**values, "cloud_prices": drafted.cloud_prices})


def _blobs(projects: ProjectManager, project_name: str) -> StoryBlobStore:
    return StoryBlobStore(projects.get_project_path(project_name))


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
    ) -> None:
        self._sessions, self._authority, self._stories, self._projects = sessions, authority, stories, projects

    async def plan(self, *, run: RunSnapshot) -> StepPlan:
        if route_for(run, "writer") is None:
            raise OwnerBlocked("MISSING_MODEL_ROLE")
        return StepPlan(
            unit_key="brief",
            estimated_cost_minor_units=0,
            estimated_model_calls=0,
            estimated_tasks=0,
            estimated_runtime_seconds=10,
        )

    async def dispatch(self, intent: DispatchIntent) -> OwnerReceipt:
        run = await current_run(self._sessions, intent)
        command = await start_command(self._sessions, intent)
        # Quality reviewers never take part in writing, so the story's own reviews use the writer route.
        writer = route_for(run, "writer")
        if writer is None or command.idea is None:
            raise OwnerBlocked("MISSING_MODEL_ROLE")
        try:
            drafted = await self._stories.draft_brief(
                idea=command.idea,
                genre=STORY_GENRE,
                provider_id=writer[0],
                model_id=writer[1],
                max_cost_minor_units=max(1, min(10_000, run.policy.max_cost_minor_units)),
            )
        except StoryActionRefused as refused:
            raise OwnerBlocked(refused.code) from None
        if drafted.limits.cloud_prices is not None and run.policy.currency != "USD":
            raise OwnerBlocked("CURRENCY_MISMATCH")
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
        return usage_receipt(receipt, reservation)


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
            )
        except StoryActionRefused as refused:
            raise OwnerBlocked(refused.code) from None
        return OwnerReceipt(owner=self.owner, receipt_ref=ref.run_id, digest=greenlight.digest, task_id=ref.task_id)

    async def inspect(self, *, intent: DispatchIntent, receipt: OwnerReceipt) -> StageOutcome:
        state = await self._state(receipt)
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
        used = state.usage
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
                raise OwnerBlocked("STORY_EXCEPTION_REQUIRES_HUMAN") from None
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
    "STORY_SHARE",
    "BriefAdapter",
    "HandoffAdapter",
    "StoryAdapter",
    "StoryCommitAdapter",
    "brief_bytes",
    "story_limits",
]
