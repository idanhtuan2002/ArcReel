"""The host's managed GPU admission across Ollama, ComfyUI and local TTS jobs.

One job holds a device at a time, in arrival order. Acquire also waits until every registered provider probe
reports the device free of work the host did not admit (a job left by a crashed process, another app's request),
so a restart never assumes a lease ended just because it is old. A job releases only after its provider has no
queued or running work; the model it loaded stays resident and counts as occupying the device, so the next job of
another workload first unloads it through that provider's documented API and verifies the unload. Nothing outside
the host-managed resident model is ever killed or unloaded.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx

from lib.generation_resources import DeviceJob, DeviceLease, JobReceipt, workload_for

logger = logging.getLogger(__name__)


class ProviderProbe(Protocol):
    """Busy state and managed quiescence of one local provider."""

    def owns(self, workload: str) -> bool: ...

    async def busy(self, *, resident: str | None) -> bool:
        """Work on the device other than the host-managed ``resident`` workload's loaded model."""
        ...

    async def quiesce(self, workload: str) -> None:
        """Unload what ``workload`` left on the device; raises ``httpx.HTTPError`` until verified."""
        ...


class DeviceAdmissionStale(RuntimeError):
    """A lease that is no longer the device's current holder."""


@dataclass
class _Device:
    lock: asyncio.Lock
    holder: DeviceLease | None = None
    resident: str | None = None


class ManagedDeviceAdmission:
    """Consecutive jobs of one workload share its resident model; a different workload first unloads it."""

    def __init__(
        self,
        probes: tuple[ProviderProbe, ...],
        *,
        poll_seconds: float = 1.0,
        quiescence_timeout_seconds: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._probes = probes
        self._poll = poll_seconds
        self._timeout = quiescence_timeout_seconds
        self._clock = clock
        self._devices: dict[str, _Device] = {}

    def _device(self, device_id: str) -> _Device:
        return self._devices.setdefault(device_id, _Device(asyncio.Lock()))

    def holder(self, device_id: str) -> DeviceLease | None:
        return self._device(device_id).holder

    def resident(self, device_id: str) -> str | None:
        return self._device(device_id).resident

    def require_holder(self, lease: DeviceLease) -> None:
        """Owners call this before committing a job's result; a late holder cannot commit."""
        if self._device(lease.device_id).holder != lease:
            raise DeviceAdmissionStale(lease.device_id)

    async def acquire(self, *, device_id: str, job: DeviceJob) -> DeviceLease:
        device = self._device(device_id)
        await device.lock.acquire()
        try:
            if device.resident is not None and device.resident != job.workload:
                await self._quiesce(device.resident)
                device.resident = None
            await self._idle(device.resident)
        except BaseException:
            device.lock.release()
            raise
        lease = DeviceLease(device_id=device_id, job=job)
        device.holder = lease
        return lease

    async def release_after_quiescence(self, *, lease: DeviceLease, receipt: JobReceipt) -> None:
        """Release once the job's provider has no queued or running work left; its loaded model stays resident
        and holds the device for the next job of the same workload only."""
        del receipt
        device = self._device(lease.device_id)
        if device.holder != lease:
            raise DeviceAdmissionStale(lease.device_id)
        try:
            await self._idle(lease.job.workload)
        finally:
            device.resident = lease.job.workload
            device.holder = None
            device.lock.release()

    async def _idle(self, resident: str | None) -> None:
        """Return once no provider reports work beyond ``resident``'s loaded model."""
        while True:
            if not await self._busy(resident):
                return
            await asyncio.sleep(self._poll)

    async def _busy(self, resident: str | None) -> bool:
        for probe in self._probes:
            try:
                if await probe.busy(resident=resident if resident is not None and probe.owns(resident) else None):
                    return True
            except httpx.HTTPError:
                # An unreachable provider holds no device memory the host can see; it is not busy.
                continue
        return False

    async def _quiesce(self, workload: str) -> None:
        deadline = self._clock() + self._timeout
        for probe in self._probes:
            if not probe.owns(workload):
                continue
            while True:
                try:
                    await probe.quiesce(workload)
                    break
                except httpx.HTTPError:
                    if self._clock() >= deadline:
                        raise
                    await asyncio.sleep(self._poll)


class OllamaProbe:
    """Ollama on loopback: busy while any model is loaded; quiescence unloads the job's model (``keep_alive=0``)."""

    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._prefix = workload_for(base_url, "")
        self._client = client or httpx.AsyncClient(timeout=30)

    def owns(self, workload: str) -> bool:
        return workload.startswith(self._prefix)

    async def _loaded(self) -> list[str]:
        response = await self._client.get(self._base + "/api/ps")
        response.raise_for_status()
        return [str(model.get("name") or model.get("model")) for model in response.json().get("models") or []]

    async def busy(self, *, resident: str | None) -> bool:
        model = resident.partition("/")[2] if resident else None
        return any(name != model for name in await self._loaded())

    async def quiesce(self, workload: str) -> None:
        model = workload.partition("/")[2]
        if model in await self._loaded():
            response = await self._client.post(self._base + "/api/generate", json={"model": model, "keep_alive": 0})
            response.raise_for_status()
        if model in await self._loaded():
            raise httpx.HTTPError("model still loaded")


class ComfyuiProbe:
    """ComfyUI on loopback: busy while its queue runs or holds work; quiescence frees the models it loaded."""

    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._prefix = workload_for(base_url, "")
        self._client = client or httpx.AsyncClient(timeout=30)

    def owns(self, workload: str) -> bool:
        return workload.startswith(self._prefix)

    async def busy(self, *, resident: str | None) -> bool:
        del resident
        response = await self._client.get(self._base + "/queue")
        response.raise_for_status()
        queue = response.json()
        return bool(queue.get("queue_running") or queue.get("queue_pending"))

    async def quiesce(self, workload: str) -> None:
        del workload
        if await self.busy(resident=None):
            raise httpx.HTTPError("queue not empty")
        response = await self._client.post(self._base + "/free", json={"unload_models": True, "free_memory": True})
        response.raise_for_status()


__all__ = ["ComfyuiProbe", "DeviceAdmissionStale", "ManagedDeviceAdmission", "OllamaProbe", "ProviderProbe"]
