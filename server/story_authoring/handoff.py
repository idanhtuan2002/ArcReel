"""Hand an approved manuscript to the video flow as a novel source.

Only a ``COMMITTED`` run hands off, and each run hands off once. The exported bytes are read by their digest,
checked against the manifest's export digest and re-scanned for CJK before the upload. The source file name is
an ASCII slug of the title; when a different file already holds that name, a short digest suffix is added.

The hand-off is recorded ``PENDING`` with its file name before the upload and ``DONE`` after it. A repeated call
with the same command id returns the recorded result; a resumed ``PENDING`` hand-off whose file already holds
exactly the exported text is completed without a second upload, so a crash between the upload and the record
never writes a second source.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from typing import Literal

from lib.project_manager import resolve_source_kind
from server.story_authoring.artifacts import StoryBlobStore
from server.story_authoring.commit import load_offered_manifest
from server.story_authoring.runtime import HandoffRecord, RunPhase, RunState, RunStateStore
from server.story_authoring.script_guard import has_cjk

type OnConflict = Literal["fail", "replace", "rename"]
type SourceUpload = Callable[[str, str, OnConflict], Awaitable[dict[str, object]]]

SLUG_MAX = 80
SOURCE_SUFFIX = ".txt"


class HandoffRefusal(StrEnum):
    NOT_COMMITTED = "NOT_COMMITTED"
    ALREADY_HANDED_OFF = "ALREADY_HANDED_OFF"
    EXPORT_MISMATCH = "EXPORT_MISMATCH"
    CJK_IN_EXPORT = "CJK_IN_EXPORT"
    NOT_A_NOVEL_PROJECT = "NOT_A_NOVEL_PROJECT"
    UPLOAD_FAILED = "UPLOAD_FAILED"


class HandoffRefused(Exception):
    def __init__(self, code: HandoffRefusal, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")


def slug_filename(title: str, *, suffix: str = ".md", max_length: int = SLUG_MAX) -> str:
    """An ASCII file name from a title: no separators or control characters, at most ``max_length`` long."""
    folded = unicodedata.normalize("NFKD", title.replace("đ", "d").replace("Đ", "D"))
    ascii_text = folded.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-") or "story"
    return slug[: max_length - len(suffix)].rstrip("-") + suffix


def _source_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() and not path.is_symlink() else None


def _choose_filename(title: str, export_digest: str, source_dir: Path, text: str) -> str:
    base = slug_filename(title)
    existing = _source_text(source_dir / (Path(base).stem + SOURCE_SUFFIX))
    if existing is None or existing == text:
        return base
    hex_digest = export_digest.removeprefix("sha256:")
    return slug_filename(title, suffix=f"-{hex_digest[:8]}.md")


async def send_to_video(
    *,
    store: RunStateStore,
    blobs: StoryBlobStore,
    project: dict[str, object],
    source_dir: Path,
    command_id: str,
    upload: SourceUpload,
    on_conflict: OnConflict = "fail",
) -> HandoffRecord:
    state = await store.load()
    if state.handoff is not None and state.handoff.done:
        if state.handoff.command_id == command_id:
            return state.handoff
        raise HandoffRefused(HandoffRefusal.ALREADY_HANDED_OFF, f"handed off as {state.handoff.path}")
    if state.phase is not RunPhase.COMMITTED or state.commit is None:
        raise HandoffRefused(HandoffRefusal.NOT_COMMITTED, f"run is {state.phase.value}")
    if resolve_source_kind(project) != "novel":
        raise HandoffRefused(HandoffRefusal.NOT_A_NOVEL_PROJECT, "the project's source kind is not novel")
    manifest = load_offered_manifest(blobs, state)
    try:
        text = blobs.read_exact(manifest.export_digest).decode("utf-8")
    except Exception as error:
        raise HandoffRefused(HandoffRefusal.EXPORT_MISMATCH, str(error)) from error
    if has_cjk(text):
        raise HandoffRefused(HandoffRefusal.CJK_IN_EXPORT, "the exported manuscript contains CJK characters")

    pending = state.handoff
    if pending is not None and pending.command_id != command_id:
        raise HandoffRefused(HandoffRefusal.ALREADY_HANDED_OFF, f"a hand-off as {pending.filename} is in progress")
    if pending is None:
        title = text.splitlines()[0].removeprefix("# ") if text else ""
        filename = _choose_filename(title, manifest.export_digest, source_dir, text)
        pending = HandoffRecord(command_id=command_id, filename=filename, export_digest=manifest.export_digest)
        pending = await _record_pending(store, pending)

    target = source_dir / (Path(pending.filename).stem + SOURCE_SUFFIX)
    if _source_text(target) == text:
        result_path = f"source/{target.name}"
    else:
        try:
            result = await upload(pending.filename, text, on_conflict)
        except Exception as error:
            raise HandoffRefused(HandoffRefusal.UPLOAD_FAILED, str(error)) from error
        result_path = str(result["path"])
    done = pending.model_copy(update={"done": True, "path": result_path})
    await store.apply(lambda s: (s.model_copy(update={"handoff": done}), None))
    return done


async def _record_pending(store: RunStateStore, pending: HandoffRecord) -> HandoffRecord:
    def change(state: RunState) -> tuple[RunState, HandoffRecord]:
        if state.handoff is not None:
            return state, state.handoff
        return state.model_copy(update={"handoff": pending}), pending

    _, recorded = await store.apply(change)
    if recorded.command_id != pending.command_id:
        raise HandoffRefused(HandoffRefusal.ALREADY_HANDED_OFF, f"a hand-off as {recorded.filename} is in progress")
    return recorded
