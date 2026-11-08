from __future__ import annotations

import asyncio

import httpx
import pytest

from lib.generation_resources import (
    DeviceJob,
    JobReceipt,
    configure_device_admission,
    device_job,
    local_job,
    workload_for,
)
from server.production_run.resource_admission import DeviceAdmissionStale, ManagedDeviceAdmission

OLLAMA = workload_for("http://127.0.0.1:11434", "qwen3:8b")
COMFY = workload_for("http://127.0.0.1:8188", "flux2")


class Probe:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.working = False
        self.loaded: str | None = None
        self.quiesced: list[str] = []
        self.unreachable = False

    def owns(self, workload: str) -> bool:
        return workload.startswith(self.prefix)

    async def busy(self, *, resident: str | None) -> bool:
        if self.unreachable:
            raise httpx.ConnectError("down")
        return self.working or (self.loaded is not None and self.loaded != resident)

    async def quiesce(self, workload: str) -> None:
        self.quiesced.append(workload)
        self.loaded = None


@pytest.fixture
def probes():
    return Probe("127.0.0.1:11434/"), Probe("127.0.0.1:8188/")


def _admission(probes, clock=None):
    return ManagedDeviceAdmission(probes, poll_seconds=0.001, clock=clock or (lambda: 0.0))


async def test_busy_gpu_lease_is_not_freed_by_expiry(probes):
    now = [0.0]
    admission = _admission(probes, clock=lambda: now[0])
    _ollama, comfy = probes
    first = await admission.acquire(device_id="gpu0", job=DeviceJob("gpu0", COMFY))
    comfy.working = True
    second_acquire = asyncio.create_task(admission.acquire(device_id="gpu0", job=DeviceJob("gpu0", OLLAMA)))
    now[0] = 10_000.0
    await asyncio.sleep(0.05)

    assert not second_acquire.done()
    releasing = asyncio.create_task(admission.release_after_quiescence(lease=first, receipt=JobReceipt(completed=True)))
    await asyncio.sleep(0.02)
    assert not releasing.done()
    assert not second_acquire.done()

    comfy.working = False
    await releasing
    second = await asyncio.wait_for(second_acquire, 1)
    assert admission.holder("gpu0") == second
    assert comfy.quiesced == [COMFY]
    with pytest.raises(DeviceAdmissionStale):
        admission.require_holder(first)


async def test_a_resident_model_serves_its_own_workload_and_is_unloaded_for_another(probes):
    admission = _admission(probes)
    ollama, _comfy = probes
    lease = await admission.acquire(device_id="gpu0", job=DeviceJob("gpu0", OLLAMA))
    ollama.loaded = OLLAMA
    await admission.release_after_quiescence(lease=lease, receipt=JobReceipt(completed=True))

    again = await asyncio.wait_for(admission.acquire(device_id="gpu0", job=DeviceJob("gpu0", OLLAMA)), 1)
    await admission.release_after_quiescence(lease=again, receipt=JobReceipt(completed=True))
    assert ollama.quiesced == []

    image = await asyncio.wait_for(admission.acquire(device_id="gpu0", job=DeviceJob("gpu0", COMFY)), 1)
    assert ollama.quiesced == [OLLAMA]
    assert admission.holder("gpu0") == image


async def test_work_left_by_another_process_holds_the_device_until_it_ends(probes):
    admission = _admission(probes)
    _ollama, comfy = probes
    comfy.working = True
    acquiring = asyncio.create_task(admission.acquire(device_id="gpu0", job=DeviceJob("gpu0", OLLAMA)))
    await asyncio.sleep(0.02)
    assert not acquiring.done()
    comfy.working = False
    await asyncio.wait_for(acquiring, 1)


async def test_an_unreachable_provider_holds_no_device(probes):
    admission = _admission(probes)
    probes[1].unreachable = True
    lease = await asyncio.wait_for(admission.acquire(device_id="gpu0", job=DeviceJob("gpu0", OLLAMA)), 1)
    assert admission.holder("gpu0") == lease


class CountingPort:
    def __init__(self) -> None:
        self.acquired: list[str] = []
        self.released = 0

    async def acquire(self, *, device_id, job):
        self.acquired.append(job.workload)
        from lib.generation_resources import DeviceLease

        return DeviceLease(device_id=device_id, job=job)

    async def release_after_quiescence(self, *, lease, receipt):
        self.released += 1


async def test_nested_wrappers_acquire_once_per_physical_job():
    port = CountingPort()
    configure_device_admission(port)
    try:
        job = local_job("http://localhost:11434", "qwen3:8b")
        async with device_job(job), device_job(job):
            pass
        async with device_job(local_job("https://api.example.com", "gemini")):
            pass
    finally:
        configure_device_admission(None)
    assert (port.acquired, port.released) == ([workload_for("http://localhost:11434", "qwen3:8b")], 1)


async def test_a_failed_job_still_releases_after_quiescence():
    port = CountingPort()
    configure_device_admission(port)
    try:
        with pytest.raises(RuntimeError):
            async with device_job(local_job("http://127.0.0.1:8188", "flux2")):
                raise RuntimeError("provider failed")
    finally:
        configure_device_admission(None)
    assert port.released == 1


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_every_loopback_spelling_of_one_server_is_one_workload(host):
    assert workload_for(f"http://{host}:11434", "qwen3:8b") == OLLAMA


async def test_ollama_probe_owns_and_keeps_a_model_called_through_localhost():
    from server.production_run.resource_admission import OllamaProbe

    def loaded(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})

    probe = OllamaProbe("http://127.0.0.1:11434", client=httpx.AsyncClient(transport=httpx.MockTransport(loaded)))
    resident = workload_for("http://localhost:11434", "qwen3:8b")

    assert probe.owns(resident)
    assert await probe.busy(resident=resident) is False
