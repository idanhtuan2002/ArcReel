"""``QUALITY``: two blind qualified model reviews of every target's approved final, combined into one verdict.

Each episode's final (from the render evidence the master was promoted from) is reviewed by the policy's
``reviewer_a`` and ``reviewer_b`` routes off the controller lease. A review is stored beside the final under the
master's digest, so a restart reuses it instead of paying again; a review of another master is never reused.
Verdicts combine with ``r2.automation.assessment.combine`` against the profile's qualified reviewer identities:
every target must pass for the stage to pass, the earliest repairable rejection reworks its stage and unit, and
anything else blocks. Model evidence never satisfies a Human slot and is never waived.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from lib.db.repositories.production_runs import ProductionRunRepository
from lib.db.repositories.reviewer_qualifications import ReviewerQualificationRepository, qualification_digest
from lib.project_manager import ProjectManager
from r2.automation.assessment import AssessmentVerdict, ModelAssessment, combine
from r2.automation.identity import digest_value
from r2.contracts.automation import (
    BudgetReservation,
    DispatchIntent,
    ModelRoute,
    OwnerReceipt,
    ReviewerQualification,
    RunSnapshot,
    RunStage,
    StageOutcome,
    UsageReceipt,
)
from r2.contracts.common import ensure_json_value
from r2.quality.errors import M10Error
from server.production_run.evaluators import FinalEvidence, QualifiedEvaluator
from server.production_run.owner_support import (
    OwnerBlocked,
    Sessions,
    current_run,
    current_subject,
    outcome,
    required_outcome,
    usage_receipt,
)
from server.production_run.ports import StepPlan
from server.production_run.quality_record import record_quality
from server.production_run.text_adapter import receipt_revision
from server.services.automation_grants import RunAutomationAuthority

QUALITY_OWNER = "quality"
REVIEWER_ROLES = ("reviewer_a", "reviewer_b")


def final_segments(final: Path, episode: int) -> tuple[tuple[str, float], ...]:
    """The final's segments in play order as (unit id, end second) from its render manifest; the renderer
    concatenates units in manifest order, each lasting its ``video.duration_us``. Empty when unreadable: findings
    then name the episode."""
    try:
        manifest = json.loads(final.with_name(f"episode_{episode}.manifest.json").read_text(encoding="utf-8"))
        segments, end = [], 0.0
        for unit in manifest["units"]:
            end += int(unit["video"]["duration_us"]) / 1_000_000
            segments.append((str(unit["unit_id"]), end))
    except (OSError, ValueError, KeyError, TypeError):
        return ()
    return tuple(segments)


def _episode(receipt: OwnerReceipt) -> int:
    return int(receipt.receipt_ref.split(":")[1])


class QualityAdapter:
    owner = QUALITY_OWNER
    seconds_per_target = 900

    def __init__(
        self,
        sessions: Sessions,
        *,
        authority: RunAutomationAuthority,
        projects: ProjectManager,
        evaluator: QualifiedEvaluator,
        max_attempts: int = 2,
    ) -> None:
        self._sessions, self._authority, self._projects = sessions, authority, projects
        self._evaluator = evaluator
        self._max_attempts = max_attempts
        self._jobs: dict[str, asyncio.Task[None]] = {}

    async def plan(self, *, run: RunSnapshot) -> StepPlan:
        render = await required_outcome(self._sessions, run, RunStage.RENDER)
        master = await required_outcome(self._sessions, run, RunStage.MASTER)
        if {_episode(r) for r in render.receipts} != {_episode(m) for m in master.receipts}:
            raise OwnerBlocked("UPSTREAM_RECEIPT_MISSING")
        return StepPlan(
            unit_key="quality",
            input_refs=(*render.receipts, *master.receipts),
            estimated_cost_minor_units=0,
            estimated_model_calls=len(REVIEWER_ROLES) * len(master.receipts),
            estimated_tasks=0,
            estimated_runtime_seconds=self.seconds_per_target * len(master.receipts),
        )

    async def dispatch(self, intent: DispatchIntent) -> OwnerReceipt:
        digest = digest_value(
            "r2.production-quality-stage.v1",
            ensure_json_value({"input_refs": [ref.model_dump(mode="json") for ref in intent.input_refs]}),
        )
        subject = await current_subject(self._sessions, intent, subject_digest=digest)
        async with self._sessions() as session, session.begin():
            await self._authority.require_locked(session, subject=subject)
        return OwnerReceipt(owner=self.owner, receipt_ref=intent.identity.command_id, digest=digest)

    async def inspect(self, *, intent: DispatchIntent, receipt: OwnerReceipt) -> StageOutcome:
        job = self._jobs.get(intent.identity.command_id)
        if job is not None and not job.done():
            return outcome(intent, "WAIT", owner_state="REVIEWING")
        if job is not None:
            self._jobs.pop(intent.identity.command_id, None)
            if job.exception() is not None:
                raise OwnerBlocked("ASSESSOR_FAILED")
        run = await current_run(self._sessions, intent)
        targets = self._targets(run, intent)
        reviews = {episode: self._stored(evidence) for episode, evidence in targets.items()}
        if any(review is None for review in reviews.values()):
            await self._start(intent, receipt.digest, run, targets)
            return outcome(intent, "WAIT", owner_state="REVIEWING")
        records = await self._qualified_records(run)
        identities = frozenset(records)
        writers = frozenset(r.model_identity for r in run.policy.routes if r.role in {"writer", "script"})
        verdicts: dict[int, AssessmentVerdict] = {}
        for episode, evidence in targets.items():
            assessments = reviews[episode] or ()
            verdicts[episode] = combine(
                assessments=assessments,
                subject_digest=evidence.subject_digest,
                language=run.policy.language,
                writer_identities=writers,
                qualified_identities=identities,
            )
        recording = run.policy.quality_gate == "record"
        if recording:
            # A judged rejection becomes a recorded REWORK disposition; evidence and integrity failures still block.
            verdicts = {
                episode: AssessmentVerdict(kind="REWORK", unit_key=f"episode:{episode}")
                if verdict.kind == "BLOCK" and verdict.reason in QUALITY_JUDGEMENTS
                else verdict
                for episode, verdict in verdicts.items()
            }
        blocked = [v for v in verdicts.values() if v.kind == "BLOCK"]
        if blocked:
            raise OwnerBlocked(blocked[0].reason or "REQUIRED_EVIDENCE_MISSING")
        project_root = self._projects.get_project_path(run.project_name)
        try:
            dispositions = await self._record(intent, receipt, run, project_root, targets, reviews, verdicts, records)
        except M10Error:
            raise OwnerBlocked("QUALITY_EVIDENCE_REFUSED") from None
        reworks = [v for v in verdicts.values() if v.kind == "REWORK"]
        identity = intent.identity
        if reworks and recording:
            evidence = tuple(dispositions[episode] for episode in sorted(targets))
            return outcome(intent, "PASS", receipts=evidence, owner_state="QUALITY_RECORDED_REWORK")
        if reworks:
            if any(_unchanged_since_last_generation(evidence.final_path) for evidence in targets.values()):
                # Reworking again would review the same final; the reviewers' rejection stands.
                raise OwnerBlocked("REWORK_WITHOUT_CHANGE")
            first = reworks[0]
            return StageOutcome(
                stage=identity.stage,
                generation=identity.generation,
                input_digest=identity.input_digest,
                policy_digest=identity.policy_digest,
                kind="REWORK",
                owner_state="REWORK",
                unit_key=first.unit_key,
                repair_stage=first.repair_stage,
                receipts=(receipt,),
            )
        evidence = tuple(dispositions[episode] for episode in sorted(targets))
        return outcome(intent, "PASS", receipts=evidence, owner_state="PASS")

    async def usage(self, *, receipt: OwnerReceipt, reservation: BudgetReservation) -> UsageReceipt | None:
        scope = reservation.scope
        async with self._sessions() as session:
            run = await ProductionRunRepository(session).get(
                user_id=scope.user_id, project_name=scope.project_name, run_id=scope.run_id
            )
            intent = await ProductionRunRepository(session).intent(scope=scope, command_id=reservation.command_id)
        if run is None or intent is None:
            return None
        calls = sum(
            1
            for evidence in self._targets(run, intent).values()
            for role in REVIEWER_ROLES
            if self._review_path(evidence, role).is_file()
        )
        return usage_receipt(receipt, reservation, model_calls=calls)

    # --- helpers -------------------------------------------------------------------------------------

    async def _record(
        self,
        intent: DispatchIntent,
        receipt: OwnerReceipt,
        run: RunSnapshot,
        project_root: Path,
        targets: dict[int, FinalEvidence],
        reviews: dict[int, tuple[ModelAssessment, ...] | None],
        verdicts: dict[int, AssessmentVerdict],
        records: dict[str, tuple[ReviewerQualification, str]],
    ) -> dict[int, OwnerReceipt]:
        """Each target's M10 disposition receipt, issued from its sealed M10 run."""
        return {
            episode: await record_quality(
                self._sessions,
                authority=self._authority,
                intent=intent,
                subject_digest=receipt.digest,
                project_root=project_root,
                episode=episode,
                profile_id=run.policy.profile_id,
                profile_digest=run.policy.profile_digest,
                assessments=reviews[episode] or (),
                verdict=verdicts[episode],
                qualifications={identity: record for identity, (record, _) in records.items()},
                qualification_digests={identity: digest for identity, (_, digest) in records.items()},
            )
            for episode in sorted(targets)
        }

    def _targets(self, run: RunSnapshot, intent: DispatchIntent) -> dict[int, FinalEvidence]:
        project = self._projects.get_project_path(run.project_name)
        renders = {_episode(r): r for r in intent.input_refs if r.owner == "renderer"}
        masters = {_episode(r): r for r in intent.input_refs if r.owner != "renderer"}
        targets: dict[int, FinalEvidence] = {}
        for episode, master in masters.items():
            final = project / receipt_revision(renders[episode])
            targets[episode] = FinalEvidence(
                unit_key=f"episode:{episode}",
                final_path=final,
                subtitle_path=final.with_suffix(".srt"),
                narration_text=self._narration(run.project_name, episode),
                subject_digest=master.digest,
                segments=final_segments(final, episode),
                target_seconds=run.policy.target_duration_seconds,
            )
        return targets

    def _narration(self, project_name: str, episode: int) -> str:
        project = self._projects.load_project(project_name)
        entry = next((e for e in project.get("episodes") or [] if e.get("episode") == episode), {})
        script_file = entry.get("script_file")
        if not isinstance(script_file, str):
            raise OwnerBlocked("UPSTREAM_RECEIPT_MISSING")
        script = json.loads((self._projects.get_project_path(project_name) / script_file).read_text(encoding="utf-8"))
        return "\n".join(str(item.get("novel_text", "")) for item in script.get("segments") or [])

    @staticmethod
    def _review_path(evidence: FinalEvidence, role: str) -> Path:
        token = evidence.subject_digest.removeprefix("sha256:")[:16]
        return evidence.final_path.parent / "quality" / f"{token}.{role}.json"

    def _stored(self, evidence: FinalEvidence) -> tuple[ModelAssessment, ...] | None:
        found = []
        for role in REVIEWER_ROLES:
            path = self._review_path(evidence, role)
            if not path.is_file():
                return None
            review = ModelAssessment.model_validate_json(path.read_text(encoding="utf-8"))
            if review.subject_digest != evidence.subject_digest:
                return None
            found.append(review)
        return tuple(found)

    async def _qualified_records(self, run: RunSnapshot) -> dict[str, tuple[ReviewerQualification, str]]:
        """The run's reviewer routes that hold a current qualification of the profile scope, by model identity."""
        async with self._sessions() as session:
            records = await ReviewerQualificationRepository(session).qualified(
                profile_digest=run.policy.profile_digest,
                launch_profile_id=run.policy.launch_profile_id,
                language=run.policy.language,
            )
        routes = {r.role: r for r in run.policy.routes}
        found: dict[str, tuple[ReviewerQualification, str]] = {}
        for record in records:
            for role in REVIEWER_ROLES:
                route = routes.get(role)
                if route is not None and (
                    record.provider_id,
                    record.model_id,
                    record.model_identity,
                    record.config_digest,
                ) == (route.provider_id, route.model_id, route.model_identity, route.config_digest):
                    found[record.model_identity] = (record, qualification_digest(record))
        return found

    async def _start(
        self, intent: DispatchIntent, subject_digest: str, run: RunSnapshot, targets: dict[int, FinalEvidence]
    ) -> None:
        key = intent.identity.command_id
        if key in self._jobs:
            return
        routes = {r.role: r for r in run.policy.routes}
        if any(role not in routes for role in REVIEWER_ROLES):
            raise OwnerBlocked("MISSING_MODEL_ROLE")
        subject = await current_subject(self._sessions, intent, subject_digest=subject_digest)
        async with self._sessions() as session, session.begin():
            repository = ProductionRunRepository(session)
            if await repository.owner_attempts(intent=intent, sub_key="review") >= self._max_attempts:
                raise OwnerBlocked("ASSESSMENT_RETRY_LIMIT")
            await self._authority.require_locked(session, subject=subject)
            await repository.record_owner_attempt(intent=intent, sub_key="review")
        self._jobs[key] = asyncio.create_task(self._review_all(targets, routes))

    async def _review_all(self, targets: dict[int, FinalEvidence], routes: dict[str, ModelRoute]) -> None:
        for evidence in targets.values():
            for role in REVIEWER_ROLES:
                path = self._review_path(evidence, role)
                if path.is_file():
                    continue
                review = await self._evaluator.assess(route=routes[role], evidence=evidence)
                path.parent.mkdir(parents=True, exist_ok=True)
                staged = path.with_suffix(".tmp")
                staged.write_text(review.model_dump_json(), encoding="utf-8")
                staged.replace(path)


#: Verdicts that are the reviewers' judgement of the final, as opposed to missing, stale or unqualified evidence.
QUALITY_JUDGEMENTS = frozenset({"REVIEWER_DISAGREEMENT", "FAILED_QUALITY"})


def _unchanged_since_last_generation(final: Path) -> bool:
    """Whether the previous generation rendered byte-identical final video for the same episode."""
    generation = final.parent.parent
    if not generation.name.startswith("g") or not generation.name[1:].isdigit() or int(generation.name[1:]) <= 1:
        return False
    previous = generation.parent / f"g{int(generation.name[1:]) - 1}" / final.parent.name / final.name
    return previous.is_file() and final.is_file() and _sha256(previous) == _sha256(final)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["QUALITY_OWNER", "REVIEWER_ROLES", "QualityAdapter"]
