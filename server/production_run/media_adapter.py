"""``MEDIA``: asset sheets, storyboards, narration audio and video units for every target episode.

The workflow planner owns what each episode still needs (with the run's narration delivery, ``use_tts``); the step
submits that action through the same media tools the agent uses and waits while the planner reports active tasks.
An episode is done when its plan asks for ``export``. Each owner action is recorded write-ahead before it is sent
and is tried at most ``max_attempts`` times; a plan that still asks for it after that blocks the run. Actions that
need a script edit, a paid-duration confirmation or provider configuration are never taken automatically.

Every target's final script is pinned when the stage is planned; a different current script is an external change.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from lib.config.resolver import ConfigResolver
from lib.db.repositories.production_runs import ProductionRunRepository
from lib.generation_queue import GenerationQueue, get_generation_queue
from lib.narration_delivery import USE_TTS
from lib.project_manager import ProjectManager
from lib.workflow_plan import WorkflowPlan, WorkflowPlanRequest
from lib.workflow_state import WorkflowActionType
from r2.automation.identity import digest_value
from r2.contracts.automation import (
    BudgetReservation,
    DispatchIntent,
    OwnerReceipt,
    RunSnapshot,
    StageOutcome,
    UsageReceipt,
)
from r2.contracts.common import ensure_json_value
from server.media_tools.assets import handle_generate_assets
from server.media_tools.context import ToolContext
from server.media_tools.narration_audio import handle_generate_narration_audio
from server.media_tools.storyboards import handle_generate_storyboards
from server.media_tools.videos import handle_generate_videos
from server.production_run.owner_support import (
    OwnerBlocked,
    Sessions,
    current_subject,
    outcome,
    script_revision,
    step_intent,
)
from server.production_run.owner_tasks import attempt_window_tasks, tasks_usage
from server.production_run.ports import StepPlan
from server.production_run.text_adapter import episode_number, receipt_revision, revision_receipt
from server.services.automation_grants import RunAutomationAuthority
from server.services.workflow_planner import WorkflowPlanner
from server.tool_runtime import CallerContext, ToolOutcome

type MediaTool = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolOutcome[Any]]]

A = WorkflowActionType
MEDIA_TOOLS: dict[WorkflowActionType, MediaTool] = {
    A.GENERATE_ASSET_SHEETS: handle_generate_assets,
    A.GENERATE_STORYBOARDS: handle_generate_storyboards,
    A.GENERATE_TTS: handle_generate_narration_audio,
    A.REGENERATE_TTS: handle_generate_narration_audio,
    A.GENERATE_VIDEOS: handle_generate_videos,
}
_UPSTREAM = frozenset(
    {
        A.COLLECT_PROJECT_INPUT,
        A.ANALYZE_ASSETS,
        A.PLAN_EPISODES,
        A.RESET_EPISODE_PLANNING,
        A.PREPARE_SCRIPT_PLAN,
        A.CONFIRM_SCRIPT_PLAN,
        A.GENERATE_SCRIPT,
    }
)


class MediaAdapter:
    owner = "media"
    calls_per_target = 80
    seconds_per_target = 7200

    def __init__(
        self,
        sessions: Sessions,
        *,
        authority: RunAutomationAuthority,
        projects: ProjectManager,
        resolver: ConfigResolver,
        planner: WorkflowPlanner | None = None,
        queue: GenerationQueue | None = None,
        tools: dict[WorkflowActionType, MediaTool] | None = None,
        max_attempts: int = 2,
    ) -> None:
        self._sessions, self._authority, self._projects, self._resolver = sessions, authority, projects, resolver
        self._planner = planner or WorkflowPlanner(projects)
        self._queue = queue or get_generation_queue()
        self._tools = tools or MEDIA_TOOLS
        self._max_attempts = max_attempts

    async def plan(self, *, run: RunSnapshot) -> StepPlan:
        pins = []
        for target in run.targets:
            episode = episode_number(target)
            status = await self._plan(run.user_id, run.project_name, episode)
            fingerprint = self._script_fingerprint(run.project_name, status)
            pins.append(revision_receipt("script-writer", f"episode:{episode}:script", fingerprint))
        units = len(run.targets)
        return StepPlan(
            unit_key="media",
            input_refs=tuple(pins),
            estimated_cost_minor_units=0,
            estimated_model_calls=self.calls_per_target * units,
            estimated_tasks=self.calls_per_target * units,
            estimated_runtime_seconds=self.seconds_per_target * units,
        )

    async def dispatch(self, intent: DispatchIntent) -> OwnerReceipt:
        digest = digest_value(
            "r2.production-media-stage.v1",
            ensure_json_value({"input_refs": [ref.model_dump(mode="json") for ref in intent.input_refs]}),
        )
        subject = await current_subject(self._sessions, intent, subject_digest=digest)
        async with self._sessions() as session, session.begin():
            await self._authority.require_locked(session, subject=subject)
        return OwnerReceipt(owner=self.owner, receipt_ref=intent.identity.command_id, digest=digest)

    async def inspect(self, *, intent: DispatchIntent, receipt: OwnerReceipt) -> StageOutcome:
        evidence: list[OwnerReceipt] = []
        for pin in intent.input_refs:
            episode = int(pin.receipt_ref.split(":")[1])
            plan = await self._plan(intent.scope.user_id, intent.scope.project_name, episode)
            if self._script_fingerprint(intent.scope.project_name, plan) != receipt_revision(pin):
                raise OwnerBlocked("EXTERNAL_INPUT_CHANGED")
            action = plan.next_action
            if action.type is A.EXPORT:
                artifacts = digest_value("r2.production-media-artifacts.v1", ensure_json_value(plan.status.artifacts))
                evidence.append(revision_receipt(self.owner, f"episode:{episode}:media", artifacts))
                continue
            if action.type is A.WAIT_FOR_TASK:
                return outcome(intent, "WAIT", owner_state="OWNER_TASK_ACTIVE")
            if action.type in _UPSTREAM:
                raise OwnerBlocked("EXTERNAL_INPUT_CHANGED")
            if action.type not in self._tools:
                if plan.blockers:
                    raise OwnerBlocked("WORKFLOW_" + plan.blockers[0].code.upper())
                raise OwnerBlocked("WORKFLOW_" + action.type.value.upper())
            await self._submit(intent, receipt.digest, plan)
            return outcome(intent, "WAIT", owner_state="OWNER_TASK_SUBMITTED")
        return outcome(intent, "PASS", receipts=tuple(evidence), owner_state="EXPORT_READY")

    async def usage(self, *, receipt: OwnerReceipt, reservation: BudgetReservation) -> UsageReceipt | None:
        intent = await step_intent(self._sessions, reservation)
        tasks = await attempt_window_tasks(self._sessions, intent)
        return await tasks_usage(self._sessions, tasks, receipt, reservation)

    # --- helpers -------------------------------------------------------------------------------------

    async def _plan(self, user_id: str, project_name: str, episode: int) -> WorkflowPlan:
        return await self._planner.get_plan(
            project_name,
            WorkflowPlanRequest(episode=episode, narration_delivery=USE_TTS),
            user_id=user_id,
            queue=self._queue,
            config_resolver=self._resolver,
        )

    def _script_fingerprint(self, project_name: str, plan: WorkflowPlan) -> str:
        target = plan.status.target
        fingerprint = (
            script_revision(self._projects.get_project_path(project_name) / target.script)
            if target is not None
            else None
        )
        if fingerprint is None:
            raise OwnerBlocked("UPSTREAM_RECEIPT_MISSING")
        return fingerprint

    async def _submit(self, intent: DispatchIntent, subject_digest: str, plan: WorkflowPlan) -> None:
        action = plan.next_action
        target = plan.status.target
        assert target is not None
        for sub_key, args in self._requests(plan, target.script_filename):
            async with self._sessions() as session:
                attempts = await ProductionRunRepository(session).owner_attempts(intent=intent, sub_key=sub_key)
            if attempts >= self._max_attempts:
                raise OwnerBlocked("MEDIA_RETRY_LIMIT")
            subject = await current_subject(self._sessions, intent, subject_digest=subject_digest)
            async with self._sessions() as session, session.begin():
                await self._authority.require_locked(session, subject=subject)
                await ProductionRunRepository(session).record_owner_attempt(intent=intent, sub_key=sub_key)
            context = ToolContext(
                intent.scope.project_name,
                Path(self._projects.projects_root),
                self._projects,
                config_resolver=self._resolver,
                caller=CallerContext(user_id=intent.scope.user_id, source="mcp"),
                queue=self._queue,
            )
            submitted = await self._tools[action.type](context, args)
            if submitted.problem is not None:
                raise OwnerBlocked("MEDIA_" + submitted.problem.code.upper())

    @staticmethod
    def _requests(plan: WorkflowPlan, script: str) -> list[tuple[str, dict[str, Any]]]:
        """The tool calls for the plan's next action, each with the sub key its attempts are counted under."""
        action = plan.next_action
        ids = sorted(action.requested_ids)
        key = (
            action.type.value
            + ":"
            + digest_value("r2.production-media-request.v1", ensure_json_value({"script": script, "ids": ids}))
        )
        if action.type is A.GENERATE_ASSET_SHEETS:
            by_type = MediaAdapter._missing_sheets_by_type(plan, ids)
            return [(f"{key}:{kind}", {"type": kind, "names": names}) for kind, names in sorted(by_type.items())]
        if action.type is A.GENERATE_STORYBOARDS:
            return [(key, {"script": script, **({"segment_ids": ids} if ids else {})})]
        if action.type in {A.GENERATE_TTS, A.REGENERATE_TTS}:
            segments = MediaAdapter._tts_segments(plan) or ids
            if action.type is A.REGENERATE_TTS and not segments:
                raise OwnerBlocked("MEDIA_TTS_SEGMENTS_UNKNOWN")
            return [(key, {"script": script, **({"segment_ids": segments} if segments else {})})]
        episode = plan.status.target.episode if plan.status.target is not None else 0
        scope: dict[str, Any] = {"scope": "selected", "ids": ids} if ids else {"scope": "episode", "episode": episode}
        return [
            (
                key,
                {"script": script, "target": scope, "narration_delivery": USE_TTS, **({"force": True} if ids else {})},
            )
        ]

    @staticmethod
    def _missing_sheets_by_type(plan: WorkflowPlan, ids: list[str]) -> dict[str, list[str]]:
        """Requested asset names grouped by asset type, from the plan's per-type missing sheet ids.

        The action names assets without their type; a name missing under several types is requested under each.
        A name no type lists blocks the step.
        """
        sheets = plan.status.artifacts.get("asset_sheets")
        by_type: dict[str, list[str]] = {}
        for kind, collection in sorted(sheets.items()) if isinstance(sheets, dict) else ():
            missing = collection.get("missing_ids", []) if isinstance(collection, dict) else []
            names = [name for name in ids if name in missing]
            if names:
                by_type[kind] = names
        if {name for names in by_type.values() for name in names} != set(ids):
            raise OwnerBlocked("MEDIA_ASSET_TYPE_UNKNOWN")
        return by_type

    @staticmethod
    def _tts_segments(plan: WorkflowPlan) -> list[str]:
        admission = plan.next_action.args.get("admission")
        units = admission.get("units") if isinstance(admission, dict) else None
        wanted = {A.GENERATE_TTS.value, A.REGENERATE_TTS.value}
        segments = {
            str(unit.get("unit_id"))
            for unit in units or []
            if isinstance(unit, dict)
            and any(isinstance(p, dict) and p.get("action") in wanted for p in unit.get("problems") or [])
        }
        return sorted(segments)


__all__ = ["MEDIA_TOOLS", "MediaAdapter"]
