"""``PACKAGE`` and ``EXPORT``: one immutable archive per target, then verified finality of the whole run.

PACKAGE writes, for each target, a deterministic zip of the final MP4, its subtitle sidecar, the render manifest,
publishing metadata (``publish.json``: title, description, tags, language, duration) with a thumbnail frame,
both quality reviews with their verdict and a lineage manifest naming the run, generation, input, policy and every
upstream owner receipt, plus one run-level manifest of the archives. EXPORT re-reads every archive and passes only
when each target's archive hashes to its package receipt, holds exactly the final the render manifest names and
the quality stage passed for that final; it then reports each target as a verified output. A run with any
missing, changed or failed target never succeeds, and nothing is published at a public URL.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
from typing import Literal

from lib.db.repositories.quality_dispositions import QualityDispositionRepository
from lib.presentation_renderer import sha256_file
from lib.project_manager import ProjectManager
from lib.publish_metadata import publish_metadata, thumbnail_frame
from r2.automation.identity import digest_value, policy_digest
from r2.contracts.automation import (
    BudgetReservation,
    DispatchIntent,
    OwnerReceipt,
    RunSnapshot,
    RunStage,
    StageOutcome,
    TargetOutput,
    UsageReceipt,
)
from r2.contracts.common import ensure_json_value
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
from server.production_run.text_adapter import receipt_revision
from server.services.automation_grants import RunAutomationAuthority

PACKAGE_OWNER = "package"
EXPORT_OWNER = "export"
_EPOCH = (2020, 1, 1, 0, 0, 0)


def _episode(receipt: OwnerReceipt) -> int:
    return int(receipt.receipt_ref.split(":")[1])


def package_dir(run: RunSnapshot) -> Path:
    return Path("production") / "automation" / run.run_id / f"g{run.generation}" / "package"


def _by_episode(receipts: tuple[OwnerReceipt, ...]) -> dict[int, OwnerReceipt]:
    return {_episode(r): r for r in receipts}


def _archive_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=_EPOCH)
            info.external_attr = 0o644 << 16
            archive.writestr(info, members[name])
    return buffer.getvalue()


def _place(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.staging")
    staged.write_bytes(data)
    os.replace(staged, path)


type QualityDecision = Literal["PASS", "REWORK"]


class _Upstream:
    async def _stages(self, sessions: Sessions, run: RunSnapshot) -> tuple[dict, dict, dict]:
        render = _by_episode((await required_outcome(sessions, run, RunStage.RENDER)).receipts)
        master = _by_episode((await required_outcome(sessions, run, RunStage.MASTER)).receipts)
        quality = _by_episode((await required_outcome(sessions, run, RunStage.QUALITY)).receipts)
        targets = {int(t.split(":")[1]) for t in run.targets}
        if not (set(render) == set(master) == set(quality) == targets):
            raise OwnerBlocked("OUTPUTS_INCOMPLETE")
        return render, master, quality

    async def _decisions(
        self, sessions: Sessions, run: RunSnapshot, quality: dict[int, OwnerReceipt]
    ) -> dict[int, QualityDecision]:
        """Each target's recorded M10 disposition decision (PASS, or REWORK under a recording quality gate)."""
        decisions: dict[int, QualityDecision] = {}
        async with sessions() as session:
            repository = QualityDispositionRepository(session)
            for episode, receipt in quality.items():
                disposition = await repository.disposition(
                    user_id=run.user_id,
                    project_name=run.project_name,
                    disposition_id=receipt.receipt_ref.rpartition("@")[2],
                )
                if disposition is None:
                    raise OwnerBlocked("QUALITY_DISPOSITION_MISSING")
                decision = disposition.decision.value
                if decision not in ("PASS", "REWORK"):
                    raise OwnerBlocked("QUALITY_DISPOSITION_NOT_AUTOMATIC")
                decisions[episode] = decision
        return decisions


class PackagingAdapter(_Upstream):
    owner = PACKAGE_OWNER

    def __init__(self, sessions: Sessions, *, authority: RunAutomationAuthority, projects: ProjectManager) -> None:
        self._sessions, self._authority, self._projects = sessions, authority, projects

    async def plan(self, *, run: RunSnapshot) -> StepPlan:
        render, master, quality = await self._stages(self._sessions, run)
        return StepPlan(
            unit_key="package",
            input_refs=(*render.values(), *master.values(), *quality.values()),
            estimated_cost_minor_units=0,
            estimated_model_calls=0,
            estimated_tasks=0,
            estimated_runtime_seconds=60 * len(run.targets),
        )

    async def dispatch(self, intent: DispatchIntent) -> OwnerReceipt:
        digest = digest_value(
            "r2.production-package-stage.v1",
            ensure_json_value({"input_refs": [r.model_dump(mode="json") for r in intent.input_refs]}),
        )
        subject = await current_subject(self._sessions, intent, subject_digest=digest)
        async with self._sessions() as session, session.begin():
            await self._authority.require_locked(session, subject=subject)
        run = await current_run(self._sessions, intent)
        quality = _by_episode(tuple(r for r in intent.input_refs if r.owner == "quality"))
        self._package(run, intent, await self._decisions(self._sessions, run, quality))
        return OwnerReceipt(owner=self.owner, receipt_ref=intent.identity.command_id, digest=digest)

    async def inspect(self, *, intent: DispatchIntent, receipt: OwnerReceipt) -> StageOutcome:
        run = await current_run(self._sessions, intent)
        root = self._projects.get_project_path(run.project_name) / package_dir(run)
        evidence = []
        for target in run.targets:
            episode = int(target.split(":")[1])
            archive = root / f"episode_{episode}.zip"
            if not archive.is_file():
                raise OwnerBlocked("OUTCOME_UNKNOWN")
            relative = (package_dir(run) / archive.name).as_posix()
            evidence.append(
                OwnerReceipt(
                    owner=self.owner,
                    receipt_ref=f"episode:{episode}:archive@{relative}",
                    digest="sha256:" + sha256_file(archive),
                )
            )
        return outcome(intent, "PASS", receipts=tuple(evidence), owner_state="PACKAGED")

    async def usage(self, *, receipt: OwnerReceipt, reservation: BudgetReservation) -> UsageReceipt | None:
        return usage_receipt(receipt, reservation)

    def _package(self, run: RunSnapshot, intent: DispatchIntent, decisions: dict[int, QualityDecision]) -> None:
        project = self._projects.get_project_path(run.project_name)
        project_data = self._projects.load_project(run.project_name)
        refs: dict[str, dict[int, OwnerReceipt]] = {"renderer": {}, "gate-c": {}, "quality": {}}
        for ref in intent.input_refs:
            refs.setdefault(ref.owner, {})[_episode(ref)] = ref
        index = []
        for episode, render in sorted(refs["renderer"].items()):
            final = project / receipt_revision(render)
            manifest_path = final.with_name(f"episode_{episode}.manifest.json")
            if "sha256:" + sha256_file(manifest_path) != render.digest:
                raise OwnerBlocked("RENDER_OUTPUT_CHANGED")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if sha256_file(final) != manifest["final_sha256"]:
                raise OwnerBlocked("RENDER_OUTPUT_CHANGED")
            reviews = sorted((final.parent / "quality").glob("*.json"))
            lineage = {
                "schema": "r2.production-lineage.v1",
                "run_id": run.run_id,
                "generation": run.generation,
                "input_digest": run.input_digest,
                "policy_digest": policy_digest(run.policy),
                "target": f"episode:{episode}",
                "render": render.model_dump(mode="json"),
                "master": refs["gate-c"][episode].model_dump(mode="json"),
                "quality": refs["quality"][episode].model_dump(mode="json"),
                "quality_decision": decisions[episode],
            }
            members = {
                f"episode_{episode}.mp4": final.read_bytes(),
                f"episode_{episode}.srt": final.with_suffix(".srt").read_bytes(),
                "render_manifest.json": manifest_path.read_bytes(),
                "lineage.json": json.dumps(lineage, ensure_ascii=False, sort_keys=True, indent=2).encode(),
                "quality.json": json.dumps(
                    [json.loads(r.read_text(encoding="utf-8")) for r in reviews], ensure_ascii=False, sort_keys=True
                ).encode(),
                "publish.json": json.dumps(
                    publish_metadata(
                        project_data, project, episode, duration_seconds=float(manifest.get("duration_seconds") or 0)
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                ).encode(),
                "thumbnail.jpg": thumbnail_frame(final),
            }
            data = _archive_bytes(members)
            target = project / package_dir(run) / f"episode_{episode}.zip"
            if not target.is_file() or sha256_file(target) != hashlib.sha256(data).hexdigest():
                _place(target, data)
            index.append({"target": f"episode:{episode}", "archive_sha256": hashlib.sha256(data).hexdigest()})
        run_manifest = json.dumps(
            {"schema": "r2.production-run-package.v1", "run_id": run.run_id, "archives": index}, sort_keys=True
        ).encode()
        _place(project / package_dir(run) / "run_manifest.json", run_manifest)


def verify_run_outputs(
    *,
    run: RunSnapshot,
    project_root: Path,
    packages: dict[int, OwnerReceipt],
    masters: dict[int, OwnerReceipt],
    qualities: dict[int, OwnerReceipt],
    renders: dict[int, OwnerReceipt],
    decisions: dict[int, QualityDecision],
) -> tuple[TargetOutput, ...]:
    """Every target's verified output, or ``OwnerBlocked`` naming the first target that cannot be verified."""
    outputs = []
    for target in run.targets:
        episode = int(target.split(":")[1])
        if not all(episode in group for group in (packages, masters, qualities, renders)):
            raise OwnerBlocked("OUTPUTS_INCOMPLETE")
        archive = project_root / receipt_revision(packages[episode])
        if not archive.is_file() or "sha256:" + sha256_file(archive) != packages[episode].digest:
            raise OwnerBlocked("ARCHIVE_CHANGED")
        final_path = project_root / receipt_revision(renders[episode])
        manifest = json.loads(final_path.with_name(f"episode_{episode}.manifest.json").read_text(encoding="utf-8"))
        with zipfile.ZipFile(archive) as opened:
            final_bytes = opened.read(f"episode_{episode}.mp4")
            lineage = json.loads(opened.read("lineage.json"))
        final_sha = hashlib.sha256(final_bytes).hexdigest()
        if (
            final_sha != manifest["final_sha256"]
            or lineage.get("master", {}).get("digest") != masters[episode].digest
            or lineage.get("quality_decision") != decisions[episode]
        ):
            raise OwnerBlocked("ARCHIVE_CHANGED")
        outputs.append(
            TargetOutput(
                target=target,
                generation=run.generation,
                input_digest=run.input_digest,
                policy_digest=policy_digest(run.policy),
                master_digest=masters[episode].digest,
                quality_run=qualities[episode],
                quality_decision=decisions[episode],
                export=packages[episode].model_copy(update={"owner": EXPORT_OWNER}),
                final_digest="sha256:" + final_sha,
                archive_digest=packages[episode].digest,
                archive_size=archive.stat().st_size,
                verified=True,
            )
        )
    return tuple(outputs)


class ExportAdapter(_Upstream):
    owner = EXPORT_OWNER

    def __init__(self, sessions: Sessions, *, authority: RunAutomationAuthority, projects: ProjectManager) -> None:
        self._sessions, self._authority, self._projects = sessions, authority, projects

    async def plan(self, *, run: RunSnapshot) -> StepPlan:
        packages = await required_outcome(self._sessions, run, RunStage.PACKAGE)
        return StepPlan(
            unit_key="export",
            input_refs=packages.receipts,
            estimated_cost_minor_units=0,
            estimated_model_calls=0,
            estimated_tasks=0,
            estimated_runtime_seconds=30 * len(run.targets),
        )

    async def dispatch(self, intent: DispatchIntent) -> OwnerReceipt:
        digest = digest_value(
            "r2.production-export-stage.v1",
            ensure_json_value({"input_refs": [r.model_dump(mode="json") for r in intent.input_refs]}),
        )
        subject = await current_subject(self._sessions, intent, subject_digest=digest)
        async with self._sessions() as session, session.begin():
            await self._authority.require_locked(session, subject=subject)
        return OwnerReceipt(owner=self.owner, receipt_ref=intent.identity.command_id, digest=digest)

    async def inspect(self, *, intent: DispatchIntent, receipt: OwnerReceipt) -> StageOutcome:
        run = await current_run(self._sessions, intent)
        render, master, quality = await self._stages(self._sessions, run)
        outputs = verify_run_outputs(
            run=run,
            project_root=self._projects.get_project_path(run.project_name),
            packages=_by_episode(intent.input_refs),
            masters=master,
            qualities=quality,
            renders=render,
            decisions=await self._decisions(self._sessions, run, quality),
        )
        verified = outcome(intent, "PASS", receipts=intent.input_refs or (receipt,), owner_state="EXPORTED")
        return verified.model_copy(update={"outputs": outputs})

    async def usage(self, *, receipt: OwnerReceipt, reservation: BudgetReservation) -> UsageReceipt | None:
        return usage_receipt(receipt, reservation)


__all__ = ["EXPORT_OWNER", "PACKAGE_OWNER", "ExportAdapter", "PackagingAdapter", "package_dir", "verify_run_outputs"]
