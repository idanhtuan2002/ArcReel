"""Generic ``ProviderExecutionAdapter`` wrapping backend execution callables.

Adapters return observations and never mutate attempt state. This class
enforces that structurally: it is a thin pass-through to
caller-supplied functions shaped exactly like the M7 contracts, with no
backend-specific HTTP logic of its own. Each real video backend supplies a
small translation layer from that
backend's existing create/poll/cancel functions (``lib.video_backends.base``)
into these callables; wiring bounded retry, ``AmbiguousSubmitError``
classification and the rest of the existing submit/poll machinery is that
translation layer's job, reused as-is rather than duplicated here.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from lib.db.base import utc_now
from r2.contracts.common import JSONValue
from r2.contracts.execution import ProviderRequest
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.host_hardening import (
    AttemptSnapshot,
    ProviderCapabilityProfile,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)
from r2.host_hardening.route_inventory import HOST_VIDEO_ADAPTER_VERSION, require_submit_route

if TYPE_CHECKING:
    from lib.video_backends.base import VideoGenerationRequest
    from r2.host_hardening.host_submit import ProviderSubmitReceipt

SubmitFn = Callable[[AttemptSnapshot, ProviderRequest], Awaitable[ProviderObservation]]
PollFn = Callable[[AttemptSnapshot], Awaitable[ProviderObservation]]
CancelFn = Callable[[AttemptSnapshot], Awaitable[ProviderObservation]]
ReconcileFn = Callable[[AttemptSnapshot], Awaitable[ProviderObservation | None]]


@dataclass(frozen=True)
class BackendExecutionFunctions:
    submit: SubmitFn
    poll: PollFn
    cancel: CancelFn | None = None
    reconcile: ReconcileFn | None = None


class BackendCapabilityUnsupportedError(NotImplementedError):
    """The wrapped backend declared no callable for this capability (e.g. no
    ``cancel`` function was supplied)."""


class AttemptReplayRequiresResume(RuntimeError):
    """An exact attempt replay already crossed submit and must resume by ID."""

    def __init__(self, execution_id: str) -> None:
        super().__init__(f"attempt {execution_id} already submitted; resume is required")
        self.execution_id = execution_id


def _sha256_path(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


async def _semantic_video_payload(request: VideoGenerationRequest) -> dict[str, JSONValue]:
    async def digest(path: Path | None) -> str | None:
        return None if path is None else await asyncio.to_thread(_sha256_path, Path(path))

    return {
        "prompt": request.prompt,
        "aspect_ratio": request.aspect_ratio,
        "duration_seconds": request.duration_seconds,
        "resolution": request.resolution,
        "generate_audio": request.generate_audio,
        "service_tier": request.service_tier,
        "seed": request.seed,
        "start_image_digest": await digest(request.start_image),
        "end_image_digest": await digest(request.end_image),
        "reference_image_digests": [
            value
            for value in await asyncio.gather(*(digest(path) for path in request.reference_images or ()))
            if value is not None
        ],
        "reference_audio_digests": [
            value
            for value in await asyncio.gather(*(digest(path) for path in request.reference_audio_files or ()))
            if value is not None
        ],
        "reference_audio_targets": list(request.reference_audio_targets or ()),
    }


def accepted_submit_receipt[T](value: T, *, provider_job_id: str) -> ProviderSubmitReceipt[T]:
    from r2.host_hardening.host_submit import ProviderSubmitReceipt

    provider_job_id = str(provider_job_id)
    evidence = canonical_json_bytes({"kind": "ACCEPTED", "provider_job_id": provider_job_id})
    return ProviderSubmitReceipt(
        observation=ProviderObservation(
            observation_id=str(uuid.uuid4()),
            kind=ProviderObservationKind.ACCEPTED,
            observed_at=utc_now(),
            provider_job_id=provider_job_id,
            evidence_digest="sha256:" + hashlib.sha256(evidence).hexdigest(),
        ),
        value=value,
    )


def terminal_submit_receipt[T](value: T, *, evidence_value: object) -> ProviderSubmitReceipt[T]:
    from r2.host_hardening.host_submit import ProviderSubmitReceipt

    evidence = canonical_json_bytes({"kind": "SUCCEEDED", "value": str(evidence_value)})
    return ProviderSubmitReceipt(
        observation=ProviderObservation(
            observation_id=str(uuid.uuid4()),
            kind=ProviderObservationKind.SUCCEEDED,
            observed_at=utc_now(),
            evidence_digest="sha256:" + hashlib.sha256(evidence).hexdigest(),
        ),
        value=value,
    )


async def submit_video_attempt[T](
    request: VideoGenerationRequest,
    *,
    provider_id: str,
    provider_model_id: str,
    backend_model_id: str,
    endpoint_id: str,
    submitted_base_url: str,
    submit: Callable[[], Awaitable[ProviderSubmitReceipt[T]]],
) -> T:
    if request.task_id is None:
        return (await submit()).value
    if request.attempt_submitter is None:
        raise RuntimeError("M7_SUBMIT_ROUTE_UNBOUND: worker video request requires an attempt submitter")

    capability = require_submit_route(provider_id, endpoint_id, HOST_VIDEO_ADAPTER_VERSION)
    route = ProviderRouteSnapshot(
        provider_id=provider_id,
        provider_account_ref="default",
        provider_model_id=provider_model_id,
        backend_model_id=backend_model_id,
        endpoint_id=endpoint_id,
        submitted_base_url=submitted_base_url,
        adapter_version=HOST_VIDEO_ADAPTER_VERSION,
        capability_profile_ref=capability.ref,
    )
    provider_request = ProviderRequest(
        id=f"{request.task_id}:video-submit",
        host_task_ref=request.task_id,
        provider=provider_id,
        model=provider_model_id,
        endpoint=endpoint_id,
        payload=await _semantic_video_payload(request),
        adapter_version=HOST_VIDEO_ADAPTER_VERSION,
    )

    async def submit_observation(_attempt: AttemptSnapshot) -> ProviderSubmitReceipt[T]:
        return await submit()

    result = await request.attempt_submitter.submit(
        task_id=request.task_id,
        api_call_id=request.api_call_id,
        route=route,
        request=provider_request,
        submit=submit_observation,
    )
    request.execution_id = result.execution_id
    if result.value is None:
        raise AttemptReplayRequiresResume(result.snapshot.execution_id)
    return result.value


class BackendExecutionAdapter:
    """``ProviderExecutionAdapter`` over one backend's
    :class:`BackendExecutionFunctions`."""

    def __init__(self, capability_profile: ProviderCapabilityProfile, functions: BackendExecutionFunctions) -> None:
        self.capability_profile = capability_profile
        self._functions = functions

    async def submit(self, *, attempt: AttemptSnapshot, request: ProviderRequest) -> ProviderObservation:
        return await self._functions.submit(attempt, request)

    async def poll(self, attempt: AttemptSnapshot) -> ProviderObservation:
        return await self._functions.poll(attempt)

    async def cancel(self, attempt: AttemptSnapshot) -> ProviderObservation:
        if self._functions.cancel is None:
            raise BackendCapabilityUnsupportedError(f"{self.capability_profile.ref} does not support cancel")
        return await self._functions.cancel(attempt)

    async def reconcile(self, attempt: AttemptSnapshot) -> ProviderObservation | None:
        if self._functions.reconcile is None:
            return None
        return await self._functions.reconcile(attempt)


__all__ = [
    "AttemptReplayRequiresResume",
    "BackendCapabilityUnsupportedError",
    "BackendExecutionAdapter",
    "BackendExecutionFunctions",
    "CancelFn",
    "PollFn",
    "ReconcileFn",
    "SubmitFn",
    "accepted_submit_receipt",
    "submit_video_attempt",
    "terminal_submit_receipt",
]
