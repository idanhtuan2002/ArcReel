"""Human actions on story runs: brief, start after Gate A, touchpoint 2, the run lifecycle, export and hand-off.

Every action that changes a run is a Human action by a principal holding the project's Showrunner grant (the
principal class that may Approve); reads need only the authenticated user. A run is one ``story_authoring_run``
task whose resource id is the run id; the run id derives from the Gate A decision, so starting the same
greenlit brief twice returns the same run.

Lifecycle (amendment Change C §8):

- ``RUNNING``, ``BLOCKED_*``, ``MODEL_UNAVAILABLE``, ``READY_FOR_APPROVAL``: revise, retry (blocked), discard.
- ``APPROVING``: nothing.
- ``PARTIALLY_COMMITTED``, ``COMMIT_BLOCKED``: resume, revise (successor manifest), abort.
- ``COMMITTED``: export, send to video, withdraw.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.custom_provider import is_custom_provider, parse_provider_id
from lib.db.models.task import Task
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.db.repositories.gates import GreenlightRepository
from lib.db.repositories.task_repo import STORY_RUN_TASK_TYPE, TaskRepository
from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError
from server.story_authoring.artifacts import StoryBlobStore
from server.story_authoring.authority import GrantNarrativeShowrunnerAuthority
from server.story_authoring.commit import ManuscriptCommitter, load_offered_manifest
from server.story_authoring.contracts import OLLAMA_CHAT_ENDPOINT, StoryLimits, StoryModelSelection
from server.story_authoring.driver import CHAPTERS, StoryBrief, run_call_bound, story_bible_input
from server.story_authoring.handoff import OnConflict, SourceUpload, send_to_video
from server.story_authoring.narrative import StoryIdentity
from server.story_authoring.pipeline import intent_targets, node_kind
from server.story_authoring.prompts.schemas import StorySeed, StyleBibleOut
from server.story_authoring.runtime import (
    HandoffRecord,
    RunPhase,
    RunState,
    RunStateStore,
    add_intent,
    new_run_state,
    reopen_unconverged,
    set_phase,
)

type Factory = async_sessionmaker[AsyncSession]

RUN_CALLS = run_call_bound()
SECONDS_PER_CALL = 120
DEFAULT_LIMITS = StoryLimits(
    generate_calls_max=RUN_CALLS,
    count_calls_max=RUN_CALLS,
    input_tokens_max=RUN_CALLS * 24576,
    output_tokens_max=RUN_CALLS * 4096,
    wall_clock_max_seconds=RUN_CALLS * SECONDS_PER_CALL,
)
BLOCKED_PHASES = frozenset(
    {
        RunPhase.BLOCKED_BUDGET,
        RunPhase.BLOCKED_QUALITY,
        RunPhase.BLOCKED_BINDING_MISMATCH,
        RunPhase.BLOCKED_PROPAGATION,
        RunPhase.MODEL_UNAVAILABLE,
    }
)
REVISABLE_PHASES = frozenset({RunPhase.RUNNING, RunPhase.READY_FOR_APPROVAL, RunPhase.COMMIT_BLOCKED, *BLOCKED_PHASES})
DISCARDABLE_PHASES = frozenset(
    {RunPhase.RUNNING, RunPhase.AWAITING_GATE_A, RunPhase.READY_FOR_APPROVAL, RunPhase.RECOVERY_INCONSISTENT}
    | BLOCKED_PHASES
)
PLANNING_TARGETS = frozenset({"seed", "story_bible", "style_bible", "outline", "packaging"})


class StoryActionRefused(Exception):
    """A request the run's state or the Human's evidence does not allow; ``code`` is stable for the API."""

    def __init__(self, code: str, detail: str, *, status: int = 409) -> None:
        self.code = code
        self.detail = detail
        self.status = status
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class StoryRunRef:
    run_id: str
    task_id: str
    brief: StoryBrief


def run_id_for(gate_a_decision_id: str) -> str:
    return "story-" + hashlib.sha256(gate_a_decision_id.encode("utf-8")).hexdigest()[:24]


class StoryAuthoringService:
    def __init__(
        self,
        *,
        session_factory: Factory,
        authority: GrantNarrativeShowrunnerAuthority,
        project_dir_for: Callable[[str], Path],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._factory = session_factory
        self._authority = authority
        self._project_dir_for = project_dir_for
        self._clock = clock

    # --- brief and start ---------------------------------------------------------------------------

    async def draft_brief(
        self,
        *,
        idea: str,
        genre: str,
        provider_id: str,
        model_id: str,
        story_target_syllables: int = 9000,
        judge_provider_id: str | None = None,
        judge_model_id: str | None = None,
    ) -> StoryBrief:
        """The brief with its frozen routes; its digest is what the Human greenlights at Gate A. A judge route is
        optional; without one the writer's route also reviews."""
        if (judge_provider_id is None) != (judge_model_id is None):
            raise StoryActionRefused("ROUTE_INCOMPLETE", "a judge route needs both a provider and a model", status=422)
        selection = await self._selection(provider_id, model_id)
        judge = (
            await self._selection(judge_provider_id, judge_model_id) if judge_provider_id and judge_model_id else None
        )
        return StoryBrief(
            idea=idea,
            genre=genre,
            story_target_syllables=story_target_syllables,
            selection=selection,
            judge_selection=judge if judge != selection else None,
            limits=DEFAULT_LIMITS,
        )

    async def _selection(self, provider_id: str, model_id: str) -> StoryModelSelection:
        if not is_custom_provider(provider_id):
            raise StoryActionRefused("ROUTE_NOT_QUALIFIED", f"{provider_id} is not a custom provider", status=422)
        async with self._factory() as session:
            repo = CustomProviderRepository(session)
            provider = await repo.get_provider(parse_provider_id(provider_id))
            model = await repo.get_model_by_ids(provider.id, model_id) if provider is not None else None
        if provider is None or model is None or not model.is_enabled:
            raise StoryActionRefused("ROUTE_NOT_FOUND", f"{provider_id}/{model_id} is not configured", status=422)
        if model.endpoint != OLLAMA_CHAT_ENDPOINT:
            raise StoryActionRefused(
                "ROUTE_NOT_QUALIFIED", f"story authoring needs the {OLLAMA_CHAT_ENDPOINT} endpoint", status=422
            )
        return StoryModelSelection.create(
            provider_id=provider_id,
            endpoint=model.endpoint,
            base_url=provider.base_url,
            model_id=model_id,
            has_credential=bool(provider.api_key),
        )

    async def start(
        self, *, user_id: str, project_name: str, principal: str, brief: StoryBrief, gate_a_decision_id: str
    ) -> StoryRunRef:
        await self._require_grant(principal, user_id=user_id, project_name=project_name)
        draft = brief.model_copy(update={"gate_a_decision_id": None})
        await self._require_greenlight(user_id, project_name, draft.digest(), gate_a_decision_id)
        run_id = run_id_for(gate_a_decision_id)
        existing = await self._find(user_id, project_name, run_id)
        if existing is not None:
            return existing
        started = draft.model_copy(update={"gate_a_decision_id": gate_a_decision_id})
        async with self._factory() as session:
            task = await TaskRepository(session).enqueue(
                project_name=project_name,
                task_type=STORY_RUN_TASK_TYPE,
                media_type="text",
                resource_id=run_id,
                payload={"brief": started.model_dump(mode="json")},
                user_id=user_id,
            )
        store = RunStateStore(self._factory, task_id=task["task_id"])
        await store.initialize(new_run_state(run_id=run_id, limits=started.limits, now=self._clock()))
        return StoryRunRef(run_id=run_id, task_id=task["task_id"], brief=started)

    async def _require_greenlight(self, user_id: str, project_name: str, digest: str, decision_id: str) -> None:
        async with self._factory() as session:
            history = await GreenlightRepository(session).list_for_project(user_id=user_id, project_name=project_name)
        decision = next((d for d in history if d.decision_id == decision_id), None)
        if decision is None or decision.action != "GREENLIGHT":
            raise StoryActionRefused("GATE_A_MISSING", "no Gate A greenlight with this decision id")
        if decision.source_digest != digest:
            raise StoryActionRefused("GATE_A_DIGEST_MISMATCH", "the greenlight names another brief digest")
        if any(d.source_digest == digest and d.sequence > decision.sequence for d in history):
            raise StoryActionRefused("GATE_A_SUPERSEDED", "a later Gate A decision exists for this brief")

    # --- reads -------------------------------------------------------------------------------------

    async def get(self, *, user_id: str, project_name: str, run_id: str) -> tuple[StoryRunRef, RunState]:
        ref = await self._require(user_id, project_name, run_id)
        return ref, await RunStateStore(self._factory, task_id=ref.task_id).load()

    async def list_runs(self, *, user_id: str, project_name: str) -> list[dict[str, Any]]:
        """The user's runs in a project, newest first, with what a picker shows."""
        async with self._factory() as session:
            tasks = (
                await session.execute(
                    select(Task)
                    .where(
                        Task.task_type == STORY_RUN_TASK_TYPE,
                        Task.project_name == project_name,
                        Task.user_id == user_id,
                    )
                    .order_by(Task.queued_at.desc())
                )
            ).scalars()
            found = [(t.resource_id, t.task_id, t.queued_at, json.loads(t.payload_json or "{}")) for t in tasks]
        runs = []
        for run_id, task_id, queued_at, payload in found:
            state = await RunStateStore(self._factory, task_id=task_id).load()
            brief = StoryBrief.model_validate(payload["brief"])
            runs.append(
                {
                    "run_id": run_id,
                    "phase": state.phase.value,
                    "idea": brief.idea,
                    "genre": brief.genre,
                    "started_at": queued_at.isoformat(),
                }
            )
        return runs

    def offered(self, project_name: str, state: RunState) -> dict[str, Any] | None:
        """The offered manifest with what touchpoint 2 shows: scenes, findings, exceptions and packaging."""
        if state.commit is None:
            return None
        blobs = self._blobs(project_name)
        manifest = load_offered_manifest(blobs, state)
        quality = (
            json.loads(blobs.read_exact(manifest.quality_record_digest))
            if manifest.quality_record_digest is not None
            else {"findings": [], "packaging": None}
        )
        return {
            "manifest_digest": state.commit.offered_manifest_digest,
            "export_digest": manifest.export_digest,
            "scenes": [
                {"node_id": s.node_id, "chapter": s.chapter, "scene": s.scene, "text": s.revision.normalized_content}
                for s in manifest.scenes
            ],
            "findings": quality["findings"],
            "packaging": quality["packaging"],
            "exceptions_offered": list(manifest.exceptions_offered),
            "completed_steps": list(state.commit.completed_steps),
            "blocked_step": state.commit.blocked_step,
        }

    async def export(self, *, user_id: str, project_name: str, run_id: str) -> bytes:
        _, state = await self.get(user_id=user_id, project_name=project_name, run_id=run_id)
        if state.phase is not RunPhase.COMMITTED or state.commit is None:
            raise StoryActionRefused("NOT_COMMITTED", f"run is {state.phase.value}")
        blobs = self._blobs(project_name)
        return blobs.read_exact(load_offered_manifest(blobs, state).export_digest)

    # --- touchpoint 2 and the commit sequence ------------------------------------------------------

    async def approve(
        self,
        *,
        user_id: str,
        project_name: str,
        run_id: str,
        principal: str,
        manifest_digest_seen: str,
        accepted_exceptions: list[str],
    ) -> RunState:
        committer = await self._committer(user_id, project_name, run_id)
        return await committer.approve(
            principal=principal, manifest_digest_seen=manifest_digest_seen, accepted_exceptions=accepted_exceptions
        )

    async def resume(self, *, user_id: str, project_name: str, run_id: str, principal: str) -> RunState:
        return await (await self._committer(user_id, project_name, run_id)).resume(principal=principal)

    async def abort(self, *, user_id: str, project_name: str, run_id: str, principal: str) -> RunState:
        return await (await self._committer(user_id, project_name, run_id)).abort(principal=principal)

    async def _committer(self, user_id: str, project_name: str, run_id: str) -> ManuscriptCommitter:
        ref, state = await self.get(user_id=user_id, project_name=project_name, run_id=run_id)
        store = RunStateStore(self._factory, task_id=ref.task_id)
        blobs = self._blobs(project_name)
        heads = {}
        for node in ("seed", "style_bible"):
            head = state.nodes.get(node)
            if head is None or head.head_revision_id is None:
                raise StoryActionRefused("NOT_READY", "the run has no story bible yet")
            heads[node] = blobs.read_exact(state.revisions[head.head_revision_id].digest)
        bible = story_bible_input(
            StorySeed.model_validate_json(heads["seed"]), StyleBibleOut.model_validate_json(heads["style_bible"])
        )
        return ManuscriptCommitter(
            identity=StoryIdentity(user_id=user_id, project_name=project_name, run_id=run_id),
            bible=bible,
            store=store,
            blobs=blobs,
            session_factory=self._factory,
            authority=self._authority,
            clock=self._clock,
        )

    # --- lifecycle ---------------------------------------------------------------------------------

    async def revise(
        self, *, user_id: str, project_name: str, run_id: str, principal: str, target: str, note: str
    ) -> RunState:
        """Attach a revision note; the run regenerates the target and everything stale after it, then re-offers."""
        if not note.strip():
            raise StoryActionRefused("EMPTY_NOTE", "a revision request needs a note", status=422)
        await self._require_grant(principal, user_id=user_id, project_name=project_name)
        ref, state = await self.get(user_id=user_id, project_name=project_name, run_id=run_id)
        nodes = _intent_nodes(state, target)

        def change(current: RunState) -> tuple[RunState, bool]:
            if current.phase not in REVISABLE_PHASES:
                return current, False
            revised = add_intent(current, node_ids=nodes, note=note.strip())
            return set_phase(revised, RunPhase.RUNNING), True

        return await self._transition(ref, change, "revise", requeue=True)

    async def retry(self, *, user_id: str, project_name: str, run_id: str, principal: str) -> RunState:
        await self._require_grant(principal, user_id=user_id, project_name=project_name)
        ref, _ = await self.get(user_id=user_id, project_name=project_name, run_id=run_id)

        def change(current: RunState) -> tuple[RunState, bool]:
            if current.phase not in BLOCKED_PHASES:
                return current, False
            return set_phase(reopen_unconverged(current), RunPhase.RUNNING), True

        return await self._transition(ref, change, "retry", requeue=True)

    async def discard(self, *, user_id: str, project_name: str, run_id: str, principal: str) -> RunState:
        return await self._terminal(user_id, project_name, run_id, principal, DISCARDABLE_PHASES, RunPhase.DISCARDED)

    async def withdraw(self, *, user_id: str, project_name: str, run_id: str, principal: str) -> RunState:
        return await self._terminal(
            user_id, project_name, run_id, principal, frozenset({RunPhase.COMMITTED}), RunPhase.WITHDRAWN
        )

    async def _terminal(
        self,
        user_id: str,
        project_name: str,
        run_id: str,
        principal: str,
        allowed: frozenset[RunPhase],
        phase: RunPhase,
    ) -> RunState:
        await self._require_grant(principal, user_id=user_id, project_name=project_name)
        ref, _ = await self.get(user_id=user_id, project_name=project_name, run_id=run_id)

        def change(current: RunState) -> tuple[RunState, bool]:
            if current.phase not in allowed:
                return current, False
            return set_phase(current, phase, reason=f"{phase.value.lower()} by {principal}"), True

        return await self._transition(ref, change, phase.value.lower(), requeue=False)

    async def _transition(
        self, ref: StoryRunRef, change: Callable[[RunState], tuple[RunState, bool]], action: str, *, requeue: bool
    ) -> RunState:
        store = RunStateStore(self._factory, task_id=ref.task_id)
        state, allowed = await store.apply(change)
        if not allowed:
            raise StoryActionRefused(
                "ACTION_NOT_ALLOWED", f"{action} is not allowed while the run is {state.phase.value}"
            )
        if requeue:
            async with self._factory() as session:
                await TaskRepository(session).requeue_finished_story_run(ref.task_id)
        return state

    # --- hand-off ----------------------------------------------------------------------------------

    async def send_to_video(
        self,
        *,
        user_id: str,
        project_name: str,
        run_id: str,
        principal: str,
        command_id: str,
        project: dict[str, object],
        upload: SourceUpload,
        on_conflict: OnConflict = "fail",
    ) -> HandoffRecord:
        await self._require_grant(principal, user_id=user_id, project_name=project_name)
        ref = await self._require(user_id, project_name, run_id)
        return await send_to_video(
            store=RunStateStore(self._factory, task_id=ref.task_id),
            blobs=self._blobs(project_name),
            project=project,
            source_dir=self._project_dir_for(project_name) / "source",
            command_id=command_id,
            upload=upload,
            on_conflict=on_conflict,
        )

    # --- helpers -----------------------------------------------------------------------------------

    def _blobs(self, project_name: str) -> StoryBlobStore:
        return StoryBlobStore(self._project_dir_for(project_name))

    async def _require_grant(self, principal: str, *, user_id: str, project_name: str) -> None:
        try:
            await self._authority.require_showrunner(principal, user_id=user_id, project_name=project_name)
        except NarrativeDecisionAuthorizationError as error:
            raise StoryActionRefused("NOT_AUTHORIZED", str(error), status=403) from error

    async def _require(self, user_id: str, project_name: str, run_id: str) -> StoryRunRef:
        ref = await self._find(user_id, project_name, run_id)
        if ref is None:
            raise StoryActionRefused("RUN_NOT_FOUND", f"no story run {run_id}", status=404)
        return ref

    async def _find(self, user_id: str, project_name: str, run_id: str) -> StoryRunRef | None:
        async with self._factory() as session:
            task = (
                await session.execute(
                    select(Task).where(
                        Task.task_type == STORY_RUN_TASK_TYPE,
                        Task.project_name == project_name,
                        Task.user_id == user_id,
                        Task.resource_id == run_id,
                    )
                )
            ).scalar_one_or_none()
        if task is None:
            return None
        payload = json.loads(task.payload_json or "{}")
        return StoryRunRef(run_id=run_id, task_id=task.task_id, brief=StoryBrief.model_validate(payload["brief"]))


def _intent_nodes(state: RunState, target: str) -> tuple[str, ...]:
    """The nodes a revision request lands on; only planning nodes, chapters and existing scenes are targets."""
    scenes = sorted(n for n in state.nodes if node_kind(n) == "scene_draft")
    shape = [sum(1 for n in scenes if n.startswith(f"scene_draft[{c},")) for c in range(1, CHAPTERS + 1)]
    if target in PLANNING_TARGETS or target in scenes:
        return (target,)
    if target.startswith("chapter[") and target.endswith("]") and target[8:-1].isdigit():
        chapter = int(target[8:-1])
        if 1 <= chapter <= CHAPTERS and shape[chapter - 1]:
            return intent_targets(target, shape)
    raise StoryActionRefused("UNKNOWN_TARGET", f"{target!r} is not a revisable part of this story", status=422)
