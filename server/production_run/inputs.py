"""The production input witness: the project inputs a run consumes but does not own.

The digest covers the project's user-controlled production settings and every root source file except those a
production run's hand-off wrote. Run-owned writes (story hand-off, inventory, episode ledger, scripts, media) never
move it; a user editing a setting or adding, changing or removing a source file does.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import select

from lib.character_voice import SPEECH_DELIVERY_FIELD
from lib.db.models.production_run import ProductionStepModel
from lib.episode_adaptation import SETTING as ADAPTATION_SETTING
from lib.episode_ledger import normalize_source_text
from lib.episode_target_duration import EPISODE_TARGET_DURATION_FIELD
from lib.episode_target_volume import EPISODE_TARGET_UNITS_FIELD
from lib.project_manager import ProjectManager
from lib.source_revision import SourceScope, compute_source_revision
from lib.text_metrics import detect_source_language
from r2.automation.identity import digest_value
from r2.contracts.automation import OwnerReceipt, RunStage
from r2.contracts.common import ensure_json_value
from server.production_run.owner_support import Sessions
from server.story_authoring.artifacts import StoryBlobStore
from server.story_authoring.handoff import narration_source

#: Witnessed only when present (ADR-0114's ``episode_adaptation``).
LATER_WITNESSED_SETTINGS = (ADAPTATION_SETTING, SPEECH_DELIVERY_FIELD)
# Production settings the user owns; a run reads them and never writes them.
WITNESSED_SETTINGS = (
    "content_mode",
    "generation_mode",
    "source_kind",
    "aspect_ratio",
    "style",
    "style_template_id",
    "style_image",
    "style_description",
    "model_settings",
    "video_model_settings",
    "grid_storyboard",
    "brief",
    EPISODE_TARGET_UNITS_FIELD,
    EPISODE_TARGET_DURATION_FIELD,
    "planning_window_chars",
    "planning_max_episodes",
    "narration_voice",
    "narration_speed",
    "character_voice_binding",
)


class ProjectInputWitness:
    def __init__(self, sessions: Sessions, *, projects: ProjectManager) -> None:
        self._sessions, self._projects = sessions, projects

    async def has_source_text(self, project_name: str) -> bool:
        """Whether the project's sources hold story text a run can film (ADR-0115 ``story_source = project``)."""

        def read() -> bool:
            project = self._projects.load_project(project_name)
            path = self._projects.get_project_path(project_name)
            revision = compute_source_revision(path, project, SourceScope(kind="all"))
            return any(doc.text.strip() for doc in revision.documents)

        return await asyncio.to_thread(read)

    async def settle_source_language(self, project_name: str) -> None:
        """Record the language of the project's story text as ``source_language`` when none is recorded, so a run of
        an uploaded story plans, counts and writes in the story's language; a recorded language is kept."""

        def settle() -> None:
            project = self._projects.load_project(project_name)
            recorded = project.get("source_language")
            if isinstance(recorded, str) and recorded.strip():
                return
            path = self._projects.get_project_path(project_name)
            revision = compute_source_revision(path, project, SourceScope(kind="all"))
            language = detect_source_language("\n".join(doc.text for doc in revision.documents))
            if language is None:
                return

            def record(current: dict) -> None:
                value = current.get("source_language")
                if not isinstance(value, str) or not value.strip():
                    current["source_language"] = language

            self._projects.update_project(project_name, record)

        await asyncio.to_thread(settle)

    async def digest(self, *, user_id: str, project_name: str) -> str:
        handed_off = await self._run_sources(user_id, project_name)
        return await asyncio.to_thread(self._digest, project_name, handed_off)

    async def _run_sources(self, user_id: str, project_name: str) -> frozenset[tuple[str, str]]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(ProductionStepModel.receipt_json).where(
                        ProductionStepModel.user_id == user_id,
                        ProductionStepModel.project_name == project_name,
                        ProductionStepModel.stage == RunStage.HANDOFF.value,
                        ProductionStepModel.receipt_json.is_not(None),
                    )
                )
            ).scalars()
            receipts = [OwnerReceipt.model_validate_json(row) for row in rows if row is not None]
            return frozenset((receipt.receipt_ref, receipt.digest) for receipt in receipts)

    def _handed_off_unchanged(self, project_path: Path, handed_off: frozenset[tuple[str, str]]) -> dict[str, str]:
        """Each handed-off source path with the text the hand-off wrote, rebuilt from its export (ADR-0115): a run's
        own hand-off never moves its input, but an edit to any handed-off story part does."""
        blobs = StoryBlobStore(project_path)
        written: dict[str, str] = {}
        for path, export_digest in handed_off:
            try:
                markdown = blobs.read_exact(export_digest).decode("utf-8")
            except Exception:  # an export that cannot be read leaves the file an ordinary input
                continue
            written[path] = normalize_source_text(narration_source(markdown))
        return written

    def _digest(self, project_name: str, handed_off: frozenset[tuple[str, str]]) -> str:
        project = self._projects.load_project(project_name)
        project_path = self._projects.get_project_path(project_name)
        revision = compute_source_revision(project_path, project, SourceScope(kind="all"))
        written = self._handed_off_unchanged(project_path, handed_off)
        sources: list[dict[str, Any]] = [
            {"path": doc.rel_path, "sha256": hashlib.sha256(doc.text.encode("utf-8")).hexdigest()}
            for doc in revision.documents
            if written.get(doc.rel_path) != normalize_source_text(doc.text)
        ]
        body = {
            "settings": {key: project.get(key) for key in WITNESSED_SETTINGS}
            # Settings added later enter the witness only when set, so earlier projects keep their digest.
            | {key: project[key] for key in LATER_WITNESSED_SETTINGS if project.get(key) is not None},
            "sources": sorted(sources, key=lambda item: item["path"]),
            "source_blockers": sorted(blocker.code + ":" + blocker.path for blocker in revision.blockers),
        }
        return digest_value("r2.production-input-witness.v1", ensure_json_value(body))


__all__ = ["WITNESSED_SETTINGS", "ProjectInputWitness"]
