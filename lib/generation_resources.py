"""Managed device admission for local provider jobs.

A local provider job (loopback ComfyUI, Ollama, TTS server) runs inside ``device_job``: it acquires the device
through the process's configured ``DeviceAdmissionPort`` before submitting and releases only after the port has
verified the device is quiescent again, so a model left resident after a request returns still holds the device.
A lease never lapses by time; a crash leaves the device to be reconciled from the providers' own busy state.

Admission is acquired once per physical job: a nested ``device_job`` for a device the current task already holds
(a wrapper around a backend that also admits) does not acquire again. Without a configured port, jobs run
unadmitted, as before.
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Protocol
from urllib.parse import urlsplit

LOCAL_GPU = "gpu0"


@dataclass(frozen=True)
class DeviceJob:
    """One physical provider job: ``workload`` names the provider and model that will occupy the device."""

    device_id: str
    workload: str
    holder: str = ""


@dataclass(frozen=True)
class DeviceLease:
    device_id: str
    job: DeviceJob
    token: str = field(default_factory=lambda: uuid.uuid4().hex)
    acquired_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class JobReceipt:
    """What the job reported when it returned; ``completed`` is False for a failed or cancelled job."""

    completed: bool
    detail: str = ""


class DeviceAdmissionPort(Protocol):
    async def acquire(self, *, device_id: str, job: DeviceJob) -> DeviceLease: ...

    async def release_after_quiescence(self, *, lease: DeviceLease, receipt: JobReceipt) -> None: ...


_PORT: DeviceAdmissionPort | None = None
_HELD: contextvars.ContextVar[frozenset[str]] = contextvars.ContextVar("device_admission_held", default=frozenset())


def configure_device_admission(port: DeviceAdmissionPort | None) -> None:
    """Install (or remove) the process's admission port; composition calls this once at startup."""
    global _PORT
    _PORT = port


def device_admission_configured() -> bool:
    """Whether local device jobs are admitted one at a time with resident models of other workloads unloaded."""
    return _PORT is not None


def local_device_for(base_url: str | None) -> str | None:
    """The managed device a provider at ``base_url`` runs on, or ``None`` for a remote provider."""
    host = urlsplit(base_url or "").hostname
    if host is None:
        return None
    if host == "localhost":
        return LOCAL_GPU
    try:
        return LOCAL_GPU if ip_address(host).is_loopback else None
    except ValueError:
        return None


def workload_for(base_url: str | None, model: str) -> str:
    """The workload key of ``model`` served at ``base_url``: the same physical server shares one key, so every
    loopback spelling (``localhost``, ``127.0.0.1``, ``::1``) of one port is the same server."""
    parts = urlsplit(base_url or "")
    netloc = parts.netloc
    if local_device_for(base_url) is not None:
        netloc = "127.0.0.1" + (f":{parts.port}" if parts.port is not None else "")
    return f"{netloc}/{model}"


def local_job(base_url: str | None, model: str) -> DeviceJob | None:
    """The device job of a call to ``model`` at ``base_url``, or ``None`` when the provider is not local."""
    device = local_device_for(base_url)
    return None if device is None else DeviceJob(device_id=device, workload=workload_for(base_url, model))


@asynccontextmanager
async def device_job(job: DeviceJob | None) -> AsyncGenerator[None]:
    port = _PORT
    if job is None or port is None or job.device_id in _HELD.get():
        yield
        return
    lease = await port.acquire(device_id=job.device_id, job=job)
    token = _HELD.set(_HELD.get() | {job.device_id})
    completed = False
    try:
        yield
        completed = True
    finally:
        _HELD.reset(token)
        await port.release_after_quiescence(
            lease=lease, receipt=JobReceipt(completed=completed, detail="" if completed else "job did not complete")
        )


__all__ = [
    "LOCAL_GPU",
    "DeviceAdmissionPort",
    "DeviceJob",
    "DeviceLease",
    "JobReceipt",
    "configure_device_admission",
    "device_admission_configured",
    "device_job",
    "local_device_for",
    "local_job",
    "workload_for",
]
