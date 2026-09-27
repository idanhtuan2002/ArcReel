"""H7 end-to-end correlation: one generation joins request -> task -> provider job
-> usage -> version/master through durable columns and exported spans.

No planted canary reaches exported spans or durable public event payloads.
Application logs, rendered by the production ``RedactingFormatter``, never carry
a credential, bearer header, signed-URL parameter or raw provider job ID.
Received failure detail (paths, provider text) stays in logs with credentials
masked (ADR-0052); generation content is not copied into logs by default."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.base import DEFAULT_USER_ID
from lib.db.models.api_call import ApiCall
from lib.db.models.host_hardening import ProjectEventModel
from lib.generation_queue import GenerationQueue
from lib.generation_worker import GenerationWorker
from lib.ledger import Ledger
from lib.logging_config import RedactingFormatter
from lib.request_context import bound_request_id
from lib.version_manager import VersionManager, version_candidate_ref
from lib.video_backends.base import persist_provider_job_id
from server.telemetry import configure_test_tracer, public_job_ref

type Factory = async_sessionmaker[AsyncSession]

PROJECT = "demo"
REQUEST_ID = "req-h7-chain-0001"

CANARY_PROMPT = "prompt-canary-h7-5d1e"
CANARY_JOB_ID = "provider-job-canary-h7-5d1e"
CANARY_CREDENTIAL = "sk-credential-canary-h7-5d1e"
CANARY_URL = "https://signed.invalid/object?signature=url-canary-h7-5d1e"
CANARY_HEADER = "Bearer header-canary-h7-5d1e"
CANARY_BODY = '{"error": "body-canary-h7-5d1e"}'
CANARY_PATH_SEGMENT = "path-canary-h7-5d1e"

ALL_CANARIES = (
    CANARY_PROMPT,
    CANARY_JOB_ID,
    CANARY_CREDENTIAL,
    CANARY_URL,
    CANARY_HEADER,
    "body-canary-h7-5d1e",
    CANARY_PATH_SEGMENT,
)
# The secret parts of the credential, header and signed-URL canaries: what the log
# formatter must mask wherever they appear.
LOG_SECRET_CANARIES = (
    CANARY_CREDENTIAL,
    "header-canary-h7-5d1e",
    "url-canary-h7-5d1e",
    CANARY_JOB_ID,
)


@dataclass
class _ImageResult:
    usage_tokens: int | None = 1
    quality: str | None = "high"
    image_input_tokens: int | None = None
    image_output_tokens: int | None = None
    text_input_tokens: int | None = None
    text_output_tokens: int | None = None


def _span_text(span: Any) -> str:
    parts = [span.name, json.dumps(dict(span.attributes or {}), default=str)]
    parts.extend(event.name + json.dumps(dict(event.attributes or {}), default=str) for event in span.events)
    parts.append(str(span.status.description or ""))
    return "\n".join(parts)


def _log_text(records: list[logging.LogRecord]) -> str:
    formatter = RedactingFormatter("%(name)s: %(message)s")
    return "\n".join(formatter.format(record) for record in records)


async def _enqueue_and_claim(queue: GenerationQueue, *, resource_id: str) -> dict[str, Any]:
    with bound_request_id(REQUEST_ID):
        enqueued = await queue.enqueue_task(
            project_name=PROJECT,
            task_type="image",
            media_type="image",
            resource_id=resource_id,
            payload={"prompt": CANARY_PROMPT},
            user_id=DEFAULT_USER_ID,
            provider_id="openai",
        )
    claimed = await queue.claim_next_task(media_type="image")
    assert claimed is not None
    assert claimed["task_id"] == enqueued["task_id"]
    return claimed


@pytest.mark.asyncio
async def test_successful_generation_closes_the_chain_without_leaking_canaries(
    session_factory: Factory, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    exporter = configure_test_tracer()
    queue = GenerationQueue(session_factory=session_factory)
    ledger = Ledger(session_factory=session_factory)
    project_path = tmp_path / CANARY_PATH_SEGMENT / PROJECT
    versions = VersionManager(project_path)
    source = project_path / "characters" / "Hero.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"png")
    recorded: dict[str, Any] = {}

    async def _generate(task: dict[str, Any], *, claimed_provider_id: str | None = None) -> dict[str, Any]:
        del claimed_provider_id
        async with ledger.record(
            project_name=PROJECT, call_type="image", model="gpt-image-1", provider="openai", prompt=CANARY_PROMPT
        ) as call:
            recorded["api_call_id"] = call.call_id
            await persist_provider_job_id(task["task_id"], CANARY_JOB_ID, provider="openai")
            recorded["version"] = versions.add_version("characters", "Hero", CANARY_PROMPT, source_file=source)
            call.success(_ImageResult())
        return {"ok": True}

    claimed = await _enqueue_and_claim(queue, resource_id="Hero")
    task_id = claimed["task_id"]
    worker = GenerationWorker(queue=queue, executor=_generate)

    with (
        patch("lib.generation_queue.get_generation_queue", return_value=queue),
        caplog.at_level(logging.DEBUG),
    ):
        await worker._process_task(claimed, claimed_provider_id="openai")

    # Durable joins.
    task = await queue.get_task(task_id)
    assert task is not None
    assert task["status"] == "succeeded"
    assert task["request_id"] == REQUEST_ID
    async with session_factory() as session:
        api_call = (await session.execute(select(ApiCall).where(ApiCall.id == recorded["api_call_id"]))).scalar_one()
        events = (await session.execute(select(ProjectEventModel))).scalars().all()
    assert api_call.task_id == task_id
    assert api_call.request_id == REQUEST_ID
    version_record = versions.get_versions("characters", "Hero")["versions"][-1]
    assert version_record["task_id"] == task_id

    # Span joins, all inside one trace rooted at the task execution.
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert dict(spans["generation.enqueue"].attributes or {})["request_id"] == REQUEST_ID
    assert dict(spans["generation.enqueue"].attributes or {})["task_id"] == task_id
    task_span = spans["generation.task"]
    assert dict(task_span.attributes or {})["request_id"] == REQUEST_ID
    job_span = dict(spans["provider.job_accepted"].attributes or {})
    assert job_span["task_id"] == task_id
    assert job_span["provider_job_ref"] == public_job_ref(CANARY_JOB_ID)
    usage_span = dict(spans["usage.recorded"].attributes or {})
    assert usage_span == {**usage_span, "task_id": task_id, "usage_entry_id": str(recorded["api_call_id"])}
    version_span = dict(spans["version.recorded"].attributes or {})
    assert version_span["task_id"] == task_id
    assert version_span["candidate_id"] == version_candidate_ref("characters", "Hero", recorded["version"])
    assert "Hero" not in version_span["candidate_id"]
    assert version_span["master_version"] == str(recorded["version"])
    for name in ("provider.job_accepted", "usage.recorded", "version.recorded"):
        assert spans[name].context.trace_id == task_span.context.trace_id
        assert spans[name].parent is not None

    # Canaries: telemetry and public events never carry any; rendered logs carry no
    # secret and, with nothing failing, no generation content either.
    telemetry = "\n".join(_span_text(span) for span in exporter.get_finished_spans())
    logs = _log_text(caplog.records)
    public_events = "\n".join(json.dumps(event.public_payload, default=str) for event in events)
    for canary in ALL_CANARIES:
        assert canary not in telemetry, canary
        assert canary not in public_events, canary
    for canary in (*LOG_SECRET_CANARIES, CANARY_PROMPT):
        assert canary not in logs, canary


@pytest.mark.asyncio
async def test_failed_generation_keeps_secrets_out_of_spans_and_logs(
    session_factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    exporter = configure_test_tracer()
    queue = GenerationQueue(session_factory=session_factory)

    async def _fail(_task: dict[str, Any], *, claimed_provider_id: str | None = None) -> dict[str, Any]:
        del claimed_provider_id
        raise RuntimeError(
            f"provider rejected {CANARY_URL} Authorization: {CANARY_HEADER} key={CANARY_CREDENTIAL} "
            f"body={CANARY_BODY} output=/data/{CANARY_PATH_SEGMENT}/x.png prompt={CANARY_PROMPT}"
        )

    claimed = await _enqueue_and_claim(queue, resource_id="Villain")
    worker = GenerationWorker(queue=queue, executor=_fail)

    with caplog.at_level(logging.DEBUG):
        await worker._process_task(claimed, claimed_provider_id="openai")

    task = await queue.get_task(claimed["task_id"])
    assert task is not None
    assert task["status"] == "failed"
    task_span = next(span for span in exporter.get_finished_spans() if span.name == "generation.task")
    assert dict(task_span.attributes or {})["failure.reason_code"] == "RuntimeError"

    telemetry = "\n".join(_span_text(span) for span in exporter.get_finished_spans())
    for canary in ALL_CANARIES:
        assert canary not in telemetry, canary
    logs = _log_text(caplog.records)
    for canary in LOG_SECRET_CANARIES:
        assert canary not in logs, canary
    # The failure is still diagnosable from the rendered log (ADR-0052).
    assert "RuntimeError" in logs
    assert "provider rejected" in logs


@pytest.mark.asyncio
async def test_provider_job_ids_learnt_by_a_task_are_referenced_not_logged(
    session_factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    queue = GenerationQueue(session_factory=session_factory)
    poll_logger = logging.getLogger("lib.video_backends.base")

    async def _submit_then_fail(task: dict[str, Any], *, claimed_provider_id: str | None = None) -> dict[str, Any]:
        del claimed_provider_id
        await persist_provider_job_id(task["task_id"], CANARY_JOB_ID, provider="openai")
        poll_logger.warning("poll failed for https://api.invalid/v1/tasks/%s/creations", CANARY_JOB_ID)
        raise RuntimeError(f"provider task {CANARY_JOB_ID} expired")

    claimed = await _enqueue_and_claim(queue, resource_id="Sidekick")
    worker = GenerationWorker(queue=queue, executor=_submit_then_fail)

    with (
        patch("lib.generation_queue.get_generation_queue", return_value=queue),
        caplog.at_level(logging.DEBUG),
    ):
        await worker._process_task(claimed, claimed_provider_id="openai")

    logs = _log_text(caplog.records)
    assert CANARY_JOB_ID not in logs
    assert public_job_ref(CANARY_JOB_ID) in logs
    assert "expired" in logs
