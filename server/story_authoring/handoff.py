"""Hand an approved manuscript to the video flow as a novel source.

Only a ``COMMITTED`` run hands off, and each run hands off once. The exported bytes are read by their digest,
checked against the manifest's export digest and re-scanned for CJK before the upload. The source file name is
an ASCII slug of the title; when a different file already holds that name, a short digest suffix is added.

The hand-off is recorded ``PENDING`` with its file name before the upload and ``DONE`` after it. A repeated call
with the same command id returns the recorded result; a resumed ``PENDING`` hand-off whose file already holds
exactly the exported text is completed without a second upload, so a crash between the upload and the record
never writes a second source.

Before uploading, a request claims the pending hand-off in the run state. While another request holds a claim
younger than ``UPLOAD_CLAIM_TTL`` the call is refused ``IN_PROGRESS`` and withdrawal is refused, so one hand-off
writes at most one source. A failed upload releases its claim; a claim left by a killed process expires.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
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
# 故事以越南语写成；交接时项目源文语言按此登记
STORY_SOURCE_LANGUAGE = "vi"

SLUG_MAX = 80
SOURCE_SUFFIX = ".txt"
UPLOAD_CLAIM_TTL = timedelta(seconds=120)


class HandoffRefusal(StrEnum):
    NOT_COMMITTED = "NOT_COMMITTED"
    ALREADY_HANDED_OFF = "ALREADY_HANDED_OFF"
    EXPORT_MISMATCH = "EXPORT_MISMATCH"
    CJK_IN_EXPORT = "CJK_IN_EXPORT"
    NOT_A_NOVEL_PROJECT = "NOT_A_NOVEL_PROJECT"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    IN_PROGRESS = "IN_PROGRESS"


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
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
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
    claim: str | None = None
    if _source_text(target) == text:
        result_path = f"source/{target.name}"
    else:
        claim = await _claim_upload(store, command_id, now=clock())
        try:
            result = await upload(pending.filename, text, on_conflict)
        except Exception as error:
            await _release_upload(store, claim)
            raise HandoffRefused(HandoffRefusal.UPLOAD_FAILED, str(error)) from error
        result_path = str(result["path"])
    return await _record_done(store, command_id, claim, result_path)


def upload_in_flight(state: RunState, *, now: datetime) -> bool:
    """Whether a request holds a live claim to upload this run's pending hand-off."""
    record = state.handoff
    return (
        record is not None
        and not record.done
        and record.upload_claim is not None
        and record.upload_claimed_at is not None
        and now - record.upload_claimed_at < UPLOAD_CLAIM_TTL
    )


async def _claim_upload(store: RunStateStore, command_id: str, *, now: datetime) -> str:
    token = uuid.uuid4().hex

    def change(state: RunState) -> tuple[RunState, HandoffRefused | None]:
        record = state.handoff
        if state.phase is not RunPhase.COMMITTED:
            return state, HandoffRefused(HandoffRefusal.NOT_COMMITTED, f"run is {state.phase.value}")
        if record is None or record.command_id != command_id or record.done:
            return state, HandoffRefused(HandoffRefusal.ALREADY_HANDED_OFF, "the hand-off changed")
        if upload_in_flight(state, now=now):
            return state, HandoffRefused(HandoffRefusal.IN_PROGRESS, f"the upload of {record.filename} is running")
        claimed = record.model_copy(update={"upload_claim": token, "upload_claimed_at": now})
        return state.model_copy(update={"handoff": claimed}), None

    _, refused = await store.apply(change)
    if refused is not None:
        raise refused
    return token


async def _release_upload(store: RunStateStore, claim: str) -> None:
    def change(state: RunState) -> tuple[RunState, None]:
        record = state.handoff
        if record is None or record.upload_claim != claim:
            return state, None
        released = record.model_copy(update={"upload_claim": None, "upload_claimed_at": None})
        return state.model_copy(update={"handoff": released}), None

    await store.apply(change)


async def _record_done(store: RunStateStore, command_id: str, claim: str | None, path: str) -> HandoffRecord:
    def change(state: RunState) -> tuple[RunState, HandoffRecord | HandoffRefused]:
        record = state.handoff
        if record is None or record.command_id != command_id:
            return state, HandoffRefused(HandoffRefusal.ALREADY_HANDED_OFF, "the hand-off changed")
        if record.done:
            return state, record
        if claim is not None and record.upload_claim != claim:
            return state, HandoffRefused(HandoffRefusal.IN_PROGRESS, "another request took over the upload")
        done = record.model_copy(update={"done": True, "path": path, "upload_claim": None, "upload_claimed_at": None})
        return state.model_copy(update={"handoff": done}), done

    _, outcome = await store.apply(change)
    if isinstance(outcome, HandoffRefused):
        raise outcome
    return outcome


async def _record_pending(store: RunStateStore, pending: HandoffRecord) -> HandoffRecord:
    def change(state: RunState) -> tuple[RunState, HandoffRecord]:
        if state.handoff is not None:
            return state, state.handoff
        return state.model_copy(update={"handoff": pending}), pending

    _, recorded = await store.apply(change)
    if recorded.command_id != pending.command_id:
        raise HandoffRefused(HandoffRefusal.ALREADY_HANDED_OFF, f"a hand-off as {recorded.filename} is in progress")
    return recorded
