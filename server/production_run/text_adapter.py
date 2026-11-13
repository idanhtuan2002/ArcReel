"""Owner adapters for the text stages, driven by the workflow status owner.

``WorkflowStateService`` decides each target's next action from the project's real artifacts; a stage passes only
when every target's next action has moved past the stage, never because a queue task succeeded. While a target
still needs the stage's action, the step submits that action's owner task under an exact sub-command and waits.
A task that succeeded while the status still asks for its action is missing output and blocks the run; so does
a status that moved backwards, a planning reset, a project blocker or an action this stage does not own.

- ``ASSET_ANALYSIS`` (``AssetsAdapter`` in ``assets_adapter``): schema-bound inventory of the whole source.
- ``EPISODE_PLAN``: planner windows until every target episode exists in the ledger.
- ``ADAPTATION``: each target's screen adaptation (ADR-0114) when the project adapts; a verbatim project passes.
- ``SCRIPT_PLAN``: each target's formal script plan, then its content confirmation under the run's grant.
- ``SCRIPT``: each target's final script.

Every stage after ``ASSET_ANALYSIS`` pins the source revision that inventory completed against; a different
current revision is an external input change.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.config.resolver import ConfigResolver
from lib.draft_quarantine import generated_and_unchanged
from lib.episode_adaptation import (
    MAX_ATTEMPTS,
    AdaptationError,
    adaptation_mode,
    adaptation_state,
    adaptation_text_relpath,
    read_inputs,
)
from lib.project_manager import ProjectManager
from lib.script_batch_edit import script_revision as batch_script_revision
from lib.script_review import content_fingerprint, script_plan_path, script_plan_quarantine_path
from lib.speech_composition import SpeechProblemCode, admit_script_unit
from lib.text_backends.base import TextTaskType
from lib.text_backends.factory import project_text_fallbacks
from lib.workflow_state import WorkflowActionType, WorkflowStateService, WorkflowStatus
from r2.automation.identity import digest_value
from r2.contracts.automation import (
    BudgetReservation,
    DispatchIntent,
    OwnerReceipt,
    RunSnapshot,
    RunStage,
    StageOutcome,
    UsageReceipt,
)
from r2.contracts.common import ensure_json_value
from server.production_run.owner_support import (
    OwnerBlocked,
    Sessions,
    current_run,
    current_subject,
    outcome,
    required_receipt,
    route_for,
    script_revision,
    step_intent,
)
from server.production_run.owner_tasks import ACTIVE, find_task, step_usage, submit_task
from server.production_run.ports import StepPlan
from server.services.automation_grants import RunAutomationAuthority
from server.services.workflow_planner import WorkflowPlanner
from server.text_generation import TextGenerationRequest
from server.tool_runtime import (
    TEXT_EPISODE_ADAPTATION,
    AdaptEpisodeRequest,
    CallerContext,
    PatchEpisodeScriptRequest,
    ProjectScope,
    Services,
    ToolRequest,
    patch_episode_script,
)

type StatusReader = Callable[[str, int | None], WorkflowStatus]

A = WorkflowActionType
# Position of each orchestration action in the episode pipeline; actions absent here are not stage work.
RANK: dict[WorkflowActionType, int] = {
    A.COLLECT_PROJECT_INPUT: 0,
    A.ANALYZE_ASSETS: 1,
    A.PLAN_EPISODES: 2,
    A.RESET_EPISODE_PLANNING: 2,
    A.ADAPT_EPISODE: 3,
    A.PREPARE_SCRIPT_PLAN: 4,
    A.CONFIRM_SCRIPT_PLAN: 5,
    A.GENERATE_SCRIPT: 6,
    A.GENERATE_ASSET_SHEETS: 7,
    A.GENERATE_STORYBOARDS: 7,
    A.GENERATE_GRID: 7,
    A.GENERATE_TTS: 7,
    A.REGENERATE_TTS: 7,
    A.GENERATE_VIDEOS: 7,
    A.REPAIR_VIDEO_UNITS: 7,
    A.EXPORT: 7,
}
_SCRIPT_PLAN_TASKS = {
    "narration": "text_narration_script_plan",
    "drama": "text_drama_script_plan",
}


def revision_receipt(owner: str, ref: str, revision: str) -> OwnerReceipt:
    """Evidence of one owner revision; the owner's own revision string stays readable after ``@``."""
    return OwnerReceipt(
        owner=owner,
        receipt_ref=f"{ref}@{revision}",
        digest=digest_value("r2.production-owner-revision.v1", {"ref": ref, "revision": revision}),
    )


def receipt_revision(receipt: OwnerReceipt) -> str:
    return receipt.receipt_ref.rpartition("@")[2]


def episode_number(target: str) -> int:
    prefix, _, number = target.partition(":")
    if prefix != "episode" or not number.isdigit() or int(number) < 1:
        raise OwnerBlocked("UNSUPPORTED_TARGET")
    return int(number)


@dataclass(frozen=True)
class Progress:
    """What one target still needs: ``None`` when it is past this stage."""

    evidence: OwnerReceipt | None


class WorkflowStageAdapter:
    """One text stage over every target; subclasses name the stage's actions and submit their owner tasks."""

    owner: str
    stage: RunStage
    first_rank: int
    done_rank: int
    per_target: bool = True
    calls_per_unit = 8
    seconds_per_unit = 900
    #: Owner tasks a sub-command may run before a failed one blocks the stage; model output varies per run.
    max_task_attempts = 3

    def __init__(
        self,
        sessions: Sessions,
        *,
        authority: RunAutomationAuthority,
        projects: ProjectManager,
        resolver: ConfigResolver,
        status: StatusReader | None = None,
    ) -> None:
        self._sessions, self._authority, self._projects, self._resolver = sessions, authority, projects, resolver
        self._status = status or WorkflowStateService(projects).get_status

    # --- port ----------------------------------------------------------------------------------------

    async def plan(self, *, run: RunSnapshot) -> StepPlan:
        await self._require_script_route(run)
        units = len(run.targets) if self.per_target else 1
        refs = (await self._inventory(run),) if self._pins_source else ()
        return StepPlan(
            unit_key=self.stage.value.lower().replace("_", "-"),
            input_refs=refs,
            estimated_cost_minor_units=0,
            estimated_model_calls=self.calls_per_unit * units,
            estimated_tasks=units + (1 if self.stage is RunStage.EPISODE_PLAN else 0),
            estimated_runtime_seconds=self.seconds_per_unit * units,
        )

    async def dispatch(self, intent: DispatchIntent) -> OwnerReceipt:
        """Authorize the step's scope; owner tasks are submitted while inspecting, one exact command each."""
        digest = digest_value(
            "r2.production-text-stage.v1",
            ensure_json_value(
                {
                    "stage": self.stage.value,
                    "targets": list(await self._targets(intent)),
                    "input_refs": [ref.model_dump(mode="json") for ref in intent.input_refs],
                }
            ),
        )
        subject = await current_subject(self._sessions, intent, subject_digest=digest)
        async with self._sessions() as session, session.begin():
            await self._authority.require_locked(session, subject=subject)
        return OwnerReceipt(owner=self.owner, receipt_ref=intent.identity.command_id, digest=digest)

    async def inspect(self, *, intent: DispatchIntent, receipt: OwnerReceipt) -> StageOutcome:
        evidence: list[OwnerReceipt] = []
        units: tuple[int | None, ...] = tuple(await self._targets(intent)) if self.per_target else (None,)
        for episode in units:
            progress = await self._advance(intent, receipt, episode)
            if progress is None:
                return outcome(intent, "WAIT", owner_state="OWNER_TASK_ACTIVE")
            assert progress.evidence is not None
            evidence.append(progress.evidence)
        return outcome(intent, "PASS", receipts=tuple(evidence), owner_state="CURRENT")

    async def usage(self, *, receipt: OwnerReceipt, reservation: BudgetReservation) -> UsageReceipt | None:
        return await step_usage(self._sessions, await step_intent(self._sessions, reservation), receipt, reservation)

    # --- the stage loop ------------------------------------------------------------------------------

    async def _advance(self, intent: DispatchIntent, receipt: OwnerReceipt, episode: int | None) -> Progress | None:
        """Drive one target until it is past this stage (``Progress``) or waits on an owner task (``None``)."""
        for _ in range(4):
            status = await asyncio.to_thread(self._status, intent.scope.project_name, episode)
            self._check_source(intent, status)
            action = status.next_action
            rank = RANK.get(action.type)
            if rank is None:
                if action.type is A.WAIT_FOR_TASK:
                    return None
                if status.blockers:
                    if await self._set_aside_rejected(intent, status, episode):
                        continue
                    raise OwnerBlocked("WORKFLOW_" + status.blockers[0].code.upper())
                raise OwnerBlocked("WORKFLOW_" + action.type.value.upper())
            if rank > self.done_rank:
                await self._settle(intent, status)
                return Progress(await asyncio.to_thread(self._evidence, intent, status, episode))
            if rank < self.first_rank or action.type is A.RESET_EPISODE_PLANNING:
                raise OwnerBlocked("EXTERNAL_INPUT_CHANGED")
            if not await self._act(intent, receipt.digest, status, episode):
                return None
        raise OwnerBlocked("OWNER_OUTPUT_MISSING")

    async def _settle(self, intent: DispatchIntent, status: WorkflowStatus) -> None:
        """Last owner edits before the stage's output is pinned; none by default."""

    async def _set_aside_rejected(self, intent: DispatchIntent, status: WorkflowStatus, episode: int | None) -> bool:
        """Clear a blocker left by this run's own rejected output so the next attempt can run; none by default."""
        return False

    async def _failed_attempt(self, intent: DispatchIntent, sub_key: str) -> tuple[int, dict[str, Any]] | None:
        """The attempt number and task of the sub-command's latest task when that task failed, else ``None``."""
        latest: tuple[int, dict[str, Any]] | None = None
        for attempt in range(1, self.max_task_attempts + 1):
            task = await find_task(self._sessions, intent, sub_key if attempt == 1 else f"{sub_key}#attempt-{attempt}")
            if task is None:
                break
            latest = (attempt, task)
        if latest is None or latest[1]["status"] != "failed":
            return None
        return latest

    async def _submit_once(
        self,
        intent: DispatchIntent,
        subject: str,
        *,
        sub_key: str,
        task_type: str,
        resource_id: str,
        payload: dict[str, Any],
    ) -> bool:
        """Submit the sub-command's task; ``False`` while it runs. A failed task is submitted again under the next
        attempt key, up to ``max_task_attempts``; a succeeded task the status still asks for produced nothing."""
        for attempt in range(1, self.max_task_attempts + 1):
            key = sub_key if attempt == 1 else f"{sub_key}#attempt-{attempt}"
            task = await find_task(self._sessions, intent, key)
            if task is None:
                await submit_task(
                    self._sessions,
                    self._authority,
                    intent,
                    sub_key=key,
                    task_type=task_type,
                    resource_id=resource_id,
                    payload={**payload, "projects_root": str(self._projects.projects_root)},
                    subject_digest=subject,
                )
                return False
            if task["status"] in ACTIVE:
                return False
            if task["status"] == "succeeded":
                raise OwnerBlocked("OWNER_OUTPUT_MISSING")
        raise OwnerBlocked("OWNER_TASK_FAILED")

    async def _act(self, intent: DispatchIntent, subject: str, status: WorkflowStatus, episode: int | None) -> bool:
        """Do the stage's next action; ``True`` when it completed synchronously and the status is re-read."""
        raise NotImplementedError

    def _evidence(self, intent: DispatchIntent, status: WorkflowStatus, episode: int | None) -> OwnerReceipt:
        raise NotImplementedError

    # --- helpers -------------------------------------------------------------------------------------

    @property
    def _pins_source(self) -> bool:
        return self.stage is not RunStage.ASSET_ANALYSIS

    async def _inventory(self, run: RunSnapshot) -> OwnerReceipt:
        """The completed inventory's source revision, read when the stage is planned. The run's inventory stage
        passed in this lineage, and the input witness has held since, so this is the revision it completed."""
        await required_receipt(self._sessions, run, RunStage.ASSET_ANALYSIS)
        project = await asyncio.to_thread(self._project, run.project_name)
        workflow = project.get("workflow")
        marker = workflow.get("asset_inventory") if isinstance(workflow, dict) else None
        revision = marker.get("source_revision") if isinstance(marker, dict) else None
        if not isinstance(revision, str):
            raise OwnerBlocked("UPSTREAM_RECEIPT_MISSING")
        return revision_receipt("asset-inventory", "asset-inventory", revision)

    def _check_source(self, intent: DispatchIntent, status: WorkflowStatus) -> None:
        if not self._pins_source:
            return
        [inventory] = intent.input_refs
        if status.source_revision is not None and status.source_revision != receipt_revision(inventory):
            raise OwnerBlocked("EXTERNAL_INPUT_CHANGED")

    async def _targets(self, intent: DispatchIntent) -> tuple[int, ...]:
        run = await current_run(self._sessions, intent)
        return tuple(episode_number(target) for target in run.targets)

    async def _require_script_route(self, run: RunSnapshot) -> None:
        """The project's script text route must still be the one the policy froze."""
        frozen = route_for(run, "script")
        if frozen is None:
            raise OwnerBlocked("MISSING_MODEL_ROLE")
        current = await self._resolver.text_backend_for_task(TextTaskType.SCRIPT, run.project_name)
        if tuple(current) != frozen:
            raise OwnerBlocked("MODEL_CONFIG_CHANGED")
        # ADR-0139: the owner tasks fall back to the project's text fallbacks, which must be the ones frozen.
        frozen_fallbacks = tuple(
            (route.provider_id, route.model_id) for route in run.policy.fallback_routes if route.role == "script"
        )
        if await asyncio.to_thread(project_text_fallbacks, run.project_name) != frozen_fallbacks:
            raise OwnerBlocked("MODEL_CONFIG_CHANGED")

    def _project(self, project_name: str) -> dict[str, Any]:
        return self._projects.load_project(project_name)


class EpisodePlanAdapter(WorkflowStageAdapter):
    owner = "episode-planner"
    stage = RunStage.EPISODE_PLAN
    first_rank = 2
    done_rank = 2
    calls_per_unit = 6
    seconds_per_unit = 600

    async def _act(self, intent: DispatchIntent, subject: str, status: WorkflowStatus, episode: int | None) -> bool:
        episodes = self._project(intent.scope.project_name).get("episodes")
        planned = len(episodes) if isinstance(episodes, list) else 0
        return await self._submit_once(
            intent,
            subject,
            sub_key=f"plan:{planned}",
            task_type="text_episode_plan",
            resource_id="episode-planning",
            payload={"instructions": None},
        )

    def _evidence(self, intent: DispatchIntent, status: WorkflowStatus, episode: int | None) -> OwnerReceipt:
        if status.target is None:
            raise OwnerBlocked("OWNER_OUTPUT_MISSING")
        project = self._project(intent.scope.project_name)
        entry = next(
            (e for e in project.get("episodes") or [] if isinstance(e, dict) and e.get("episode") == episode), None
        )
        if entry is None:
            raise OwnerBlocked("OWNER_OUTPUT_MISSING")
        return OwnerReceipt(
            owner=self.owner,
            receipt_ref=f"episode:{episode}:plan",
            digest=digest_value("r2.production-episode-plan.v1", ensure_json_value(entry)),
        )


class AdaptationAdapter(WorkflowStageAdapter):
    """``ADAPTATION``: each target episode's screen adaptation (ADR-0114), one exact task per basis it reads.

    A project that keeps ``verbatim`` episodes has no adaptation action, so the stage passes with that fact as its
    evidence; an adapted episode's evidence is its adapted script's digest, which script planning then reads."""

    owner = "episode-adapter"
    stage = RunStage.ADAPTATION
    first_rank = 3
    done_rank = 3
    calls_per_unit = MAX_ATTEMPTS
    seconds_per_unit = 600

    async def _act(self, intent: DispatchIntent, subject: str, status: WorkflowStatus, episode: int | None) -> bool:
        assert episode is not None
        project_path = self._projects.get_project_path(intent.scope.project_name)
        project = await asyncio.to_thread(self._project, intent.scope.project_name)
        try:
            basis = (await asyncio.to_thread(read_inputs, project_path, project, episode)).basis()
        except AdaptationError:
            raise OwnerBlocked("ADAPTATION_INPUT_MISSING") from None
        try:
            return await self._submit_once(
                intent,
                subject,
                sub_key=f"adaptation:{episode}:{basis.removeprefix('sha256:')[:24]}",
                task_type=TEXT_EPISODE_ADAPTATION,
                resource_id=f"episode-{episode}",
                payload=AdaptEpisodeRequest(episode=episode).model_dump(mode="json"),
            )
        except OwnerBlocked as blocked:
            if blocked.reason == "OWNER_TASK_FAILED":
                raise OwnerBlocked("ADAPTATION_FAILED") from None
            raise

    def _evidence(self, intent: DispatchIntent, status: WorkflowStatus, episode: int | None) -> OwnerReceipt:
        project_path = self._projects.get_project_path(intent.scope.project_name)
        project = self._project(intent.scope.project_name)
        if adaptation_mode(project) != "screen":
            return revision_receipt(self.owner, f"episode:{episode}:adaptation", "verbatim")
        assert episode is not None
        text = project_path / adaptation_text_relpath(episode)
        if adaptation_state(project_path, project, episode) != "current" or not text.is_file():
            raise OwnerBlocked("OWNER_OUTPUT_MISSING")
        revision = "sha256:" + hashlib.sha256(text.read_bytes()).hexdigest()
        return revision_receipt(self.owner, f"episode:{episode}:adaptation", revision)


class ScriptPlanAdapter(WorkflowStageAdapter):
    owner = "script-planner"
    stage = RunStage.SCRIPT_PLAN
    first_rank = 4
    done_rank = 5

    def __init__(
        self,
        sessions: Sessions,
        *,
        authority: RunAutomationAuthority,
        projects: ProjectManager,
        resolver: ConfigResolver,
        status: StatusReader | None = None,
        confirm: Callable[[str, int], Awaitable[object]] | None = None,
    ) -> None:
        super().__init__(sessions, authority=authority, projects=projects, resolver=resolver, status=status)
        self._confirm_plan = confirm or self._review_confirm

    async def _review_confirm(self, project_name: str, episode: int) -> object:
        from server.services.script_review import ScriptReviewError, ScriptReviewService

        try:
            return await ScriptReviewService(self._projects, config_resolver=self._resolver).confirm(
                project_name, episode
            )
        except ScriptReviewError:
            raise OwnerBlocked("SCRIPT_PLAN_NOT_CONFIRMABLE") from None

    async def _act(self, intent: DispatchIntent, subject: str, status: WorkflowStatus, episode: int | None) -> bool:
        assert episode is not None
        action = status.next_action
        if action.type is A.CONFIRM_SCRIPT_PLAN:
            await self._confirm(intent, subject, status, episode)
            return True
        if action.args.get("expected_stale_script_plan_revision") is not None:
            raise OwnerBlocked("SCRIPT_PLAN_REBUILD_REQUIRED")
        mode = str(self._project(intent.scope.project_name).get("content_mode", "narration"))
        task_type = _SCRIPT_PLAN_TASKS.get(mode)
        if task_type is None:
            raise OwnerBlocked("UNSUPPORTED_CONTENT_MODE")
        return await self._submit_once(
            intent,
            subject,
            sub_key=f"script-plan:{episode}",
            task_type=task_type,
            resource_id=f"episode-{episode}",
            payload=TextGenerationRequest(episode=episode).to_payload(),
        )

    async def _confirm(self, intent: DispatchIntent, subject: str, status: WorkflowStatus, episode: int) -> None:
        """Confirm the exact script plan revision the status shows, under the run's current grant."""
        plan = status.artifacts.get("script_plan") or {}
        revision = plan.get("revision")
        if not isinstance(revision, str):
            raise OwnerBlocked("OWNER_OUTPUT_MISSING")
        current_proof = await current_subject(self._sessions, intent, subject_digest=subject)
        async with self._sessions() as session, session.begin():
            await self._authority.require_locked(session, subject=current_proof)
        project_path = self._projects.get_project_path(intent.scope.project_name)
        if (current := self._plan_revision(project_path, intent.scope.project_name, episode)) != revision:
            raise OwnerBlocked("EXTERNAL_INPUT_CHANGED" if current is not None else "OWNER_OUTPUT_MISSING")
        await self._confirm_plan(intent.scope.project_name, episode)

    async def _set_aside_rejected(self, intent: DispatchIntent, status: WorkflowStatus, episode: int | None) -> bool:
        """A script plan this run generated and the owner quarantined is renamed beside it (kept as evidence) and
        generated again under the next attempt; a draft no failed task of this run left, or whose content no longer
        matches the generator's stamp (a Human edited or replaced it), is the Human's."""
        if episode is None or status.blockers[0].code != "script_plan_quarantined":
            return False
        failed = await self._failed_attempt(intent, f"script-plan:{episode}")
        if failed is None or failed[0] >= self.max_task_attempts:
            return False
        attempt = failed[0]
        project_path = self._projects.get_project_path(intent.scope.project_name)
        path = script_plan_quarantine_path(project_path, self._project(intent.scope.project_name), episode)
        if path is None or not path.exists() or not generated_and_unchanged(path):
            return False
        path.rename(path.with_name(f"{path.name}.rejected-{attempt}"))
        return True

    def _plan_revision(self, project_path: Path, project_name: str, episode: int) -> str | None:
        path = script_plan_path(project_path, self._project(project_name), episode)
        return content_fingerprint(path) if path is not None else None

    def _evidence(self, intent: DispatchIntent, status: WorkflowStatus, episode: int | None) -> OwnerReceipt:
        revision = (status.artifacts.get("script_plan") or {}).get("revision")
        if not isinstance(revision, str):
            raise OwnerBlocked("OWNER_OUTPUT_MISSING")
        return revision_receipt(self.owner, f"episode:{episode}:script-plan", revision)


def _named_characters(text: str, characters: Sequence[str]) -> list[str]:
    """Registered character names that occur in ``text`` as whole, case-sensitive words; a name inside a longer
    matched name ("Nam" in "Mẹ Nam") does not count."""
    taken: list[tuple[int, int]] = []
    found: list[str] = []
    for name in sorted(characters, key=len, reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")
        spans = [
            m.span()
            for m in pattern.finditer(text)
            if not any(start <= m.start() and m.end() <= end for start, end in taken)
        ]
        if spans:
            taken.extend(spans)
            found.append(name)
    return found


def _narration_segment_fixes(segment: dict[str, Any], characters: Sequence[str] = ()) -> dict[str, Any]:
    """The fields to replace on one narration segment (see ``ScriptAdapter._settle``); empty when none."""
    fields: dict[str, Any] = {}
    listed = segment.get("characters_in_segment")
    if isinstance(listed, list):
        named = [n for n in _named_characters(str(segment.get("novel_text") or ""), characters) if n not in listed]
        if named:
            fields["characters_in_segment"] = [*listed, *named]
    novel_text = str(segment.get("novel_text") or "").strip()
    image_prompt = segment.get("image_prompt")
    scene = ""
    if isinstance(image_prompt, dict):
        scene = str(image_prompt.get("scene") or "").strip()
        if not scene and novel_text:
            scene = novel_text
            fields["image_prompt"] = {**image_prompt, "scene": scene}
    video_prompt = segment.get("video_prompt")
    if isinstance(video_prompt, dict):
        changed = dict(video_prompt)
        dialogue = changed.get("dialogue")
        if isinstance(dialogue, list):
            spoken = [d for d in dialogue if not isinstance(d, dict) or str(d.get("line") or "").strip()]
            if spoken != dialogue:
                changed["dialogue"] = spoken
        if segment.get("needs_replan"):
            problems = admit_script_unit("segments", {**segment, "video_prompt": changed}, ignore_marker=True).problems
            if problems and all(problem.code is SpeechProblemCode.MIXED_SPEECH for problem in problems):
                changed["dialogue"] = []
        if not str(changed.get("action") or "").strip() and (scene or novel_text):
            changed["action"] = scene or novel_text
        if changed != video_prompt:
            fields["video_prompt"] = changed
    return fields


class ScriptAdapter(WorkflowStageAdapter):
    owner = "script-writer"
    stage = RunStage.SCRIPT
    first_rank = 6
    done_rank = 6
    calls_per_unit = 12
    seconds_per_unit = 1200

    async def _act(self, intent: DispatchIntent, subject: str, status: WorkflowStatus, episode: int | None) -> bool:
        assert episode is not None
        revision = (status.artifacts.get("script_plan") or {}).get("revision")
        return await self._submit_once(
            intent,
            subject,
            sub_key=f"script:{episode}:{revision}",
            task_type="text_episode_script",
            resource_id=f"episode-{episode}",
            payload=TextGenerationRequest(episode=episode).to_payload(),
        )

    async def _settle(self, intent: DispatchIntent, status: WorkflowStatus) -> None:
        """Narration segments get the owner edits a writer would make before media, through the script edit tool:

        - a segment whose only speech problem is a character line also written into ``video_prompt`` loses that
          line; the narrator already reads it in ``novel_text``;
        - a registered character named in ``novel_text`` but missing from ``characters_in_segment`` is added, so the
          storyboard receives its reference sheet;
        - an empty ``image_prompt.scene`` or ``video_prompt.action`` is filled from the segment's own text
          (``novel_text``, or the scene for the action), since media refuses empty prompts.

        Any other replanning need is left for the media stage to report."""
        if status.project.content_mode != "narration" or status.target is None:
            return
        name = intent.scope.project_name
        script = await asyncio.to_thread(self._projects.load_script, name, status.target.script_filename)
        project = await asyncio.to_thread(self._projects.load_project, name)
        registered = project.get("characters")
        characters = [str(n) for n in registered] if isinstance(registered, dict) else []
        operations = []
        for segment in script.get("segments") or []:
            if isinstance(segment, dict):
                fields = _narration_segment_fixes(segment, characters)
                if fields:
                    operations.append({"op": "update", "id": segment["segment_id"], "fields": fields})
        if not operations:
            return
        request = PatchEpisodeScriptRequest.model_validate(
            {
                "script": status.target.script_filename,
                "base_revision": batch_script_revision(script),
                "operations": operations,
            }
        )
        edited = await patch_episode_script(
            ToolRequest(request),
            ProjectScope(name, Path(self._projects.projects_root)),
            CallerContext(user_id=intent.scope.user_id, source="mcp"),
            Services(
                projects=self._projects, workflow_planner=WorkflowPlanner(self._projects), capabilities=self._resolver
            ),
        )
        if edited.problem is not None or edited.value is None or not edited.value.success:
            raise OwnerBlocked("SCRIPT_SETTLE_PATCH_REFUSED")

    def _evidence(self, intent: DispatchIntent, status: WorkflowStatus, episode: int | None) -> OwnerReceipt:
        if status.target is None:
            raise OwnerBlocked("OWNER_OUTPUT_MISSING")
        project_path = self._projects.get_project_path(intent.scope.project_name)
        revision = script_revision(project_path / status.target.script)
        if revision is None:
            raise OwnerBlocked("OWNER_OUTPUT_MISSING")
        return revision_receipt(self.owner, f"episode:{episode}:script", revision)


__all__ = [
    "RANK",
    "AdaptationAdapter",
    "EpisodePlanAdapter",
    "ScriptAdapter",
    "ScriptPlanAdapter",
    "WorkflowStageAdapter",
    "episode_number",
    "receipt_revision",
    "revision_receipt",
]
