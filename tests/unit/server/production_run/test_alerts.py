"""Alerts outside the app go once per state change to the host's webhook, as text or JSON."""

from __future__ import annotations

import json

import httpx
import pytest

from server.production_run.alerts import AlertGate, WebhookAlerts, alerts_from_env, message


class _Recorder:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str | None, str | None]] = []

    async def send(self, *, project_name, event, run_id, reason) -> None:
        self.sent.append((project_name, event, run_id, reason))


async def test_the_same_state_is_sent_once_and_a_new_halt_after_a_run_is_sent_again():
    recorder = _Recorder()
    gate = AlertGate(recorder)
    for _ in range(3):
        await gate.observe(user_id="u", project_name="p", event="halted", run_id="r1", reason="BLOCKED_RESOURCE")
    await gate.observe(user_id="u", project_name="p", event=None)
    await gate.observe(user_id="u", project_name="p", event="halted", run_id="r1", reason="BLOCKED_RESOURCE")
    await gate.observe(user_id="u", project_name="p", event="halted", run_id="r2", reason="FAILED_QUALITY")

    assert [entry[2:] for entry in recorder.sent] == [
        ("r1", "BLOCKED_RESOURCE"),
        ("r1", "BLOCKED_RESOURCE"),
        ("r2", "FAILED_QUALITY"),
    ]


async def test_without_a_webhook_nothing_is_sent():
    await AlertGate(None).observe(user_id="u", project_name="p", event="finished")


@pytest.mark.parametrize("body_format", ["text", "json"])
async def test_the_webhook_gets_the_message_in_its_format(body_format):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    alerts = WebhookAlerts(
        "https://hooks.example.test/x", body_format=body_format, transport=httpx.MockTransport(handler)
    )
    await alerts.send(project_name="phim-1", event="halted", run_id="run-9", reason="BLOCKED_BUDGET")

    text = message(project_name="phim-1", event="halted", run_id="run-9", reason="BLOCKED_BUDGET")
    assert "phim-1" in text
    assert "BLOCKED_BUDGET" in text
    if body_format == "text":
        assert seen[0].content.decode("utf-8") == text
    else:
        body = json.loads(seen[0].content)
        assert (body["text"], body["content"], body["event"], body["run_id"]) == (text, text, "halted", "run-9")


async def test_a_failing_webhook_never_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    alerts = WebhookAlerts("https://hooks.example.test/x", transport=httpx.MockTransport(handler))
    await alerts.send(project_name="p", event="finished", run_id=None, reason=None)


def test_the_webhook_comes_from_the_host_settings(monkeypatch):
    monkeypatch.delenv("ARCREEL_ALERT_WEBHOOK_URL", raising=False)
    assert alerts_from_env() is None
    monkeypatch.setenv("ARCREEL_ALERT_WEBHOOK_URL", "https://ntfy.example.test/topic")
    assert isinstance(alerts_from_env(), WebhookAlerts)
