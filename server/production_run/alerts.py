"""Alerts outside the app when a project's autopilot needs the Showrunner or has finished (ADR-0137).

The host names one webhook: ``ARCREEL_ALERT_WEBHOOK_URL``. ``ARCREEL_ALERT_WEBHOOK_FORMAT`` is ``text`` (default; the
message is the plain-text body, as ntfy topics take it) or ``json`` (``{"text", "content", ...}``, as Slack and
Discord incoming webhooks and Telegram's ``sendMessage?chat_id=...`` take it). Each project's state is sent once per
change: the same halt (run and reason) is not sent again, so a scan every minute does not repeat it; after a restart
a standing halt is sent once more. Sending never raises; a failed send is logged and retried at the next change only.
"""

from __future__ import annotations

import logging
import os
from typing import Literal, Protocol

import httpx

logger = logging.getLogger(__name__)

URL_ENV = "ARCREEL_ALERT_WEBHOOK_URL"
FORMAT_ENV = "ARCREEL_ALERT_WEBHOOK_FORMAT"

type Event = Literal["halted", "refused", "finished"]

_HEADLINES: dict[Event, str] = {
    "halted": "ArcReel: autopilot dừng, cần bạn xử lý",
    "refused": "ArcReel: autopilot không khởi động được run",
    "finished": "ArcReel: autopilot đã xong dự án",
}


class Alerts(Protocol):
    async def send(self, *, project_name: str, event: Event, run_id: str | None, reason: str | None) -> None: ...


def message(*, project_name: str, event: Event, run_id: str | None, reason: str | None) -> str:
    lines = [_HEADLINES[event], f"Dự án: {project_name}"]
    if run_id:
        lines.append(f"Run: {run_id}")
    if reason:
        lines.append(f"Lý do: {reason}")
    return "\n".join(lines)


class WebhookAlerts:
    def __init__(
        self,
        url: str,
        *,
        body_format: Literal["text", "json"] = "text",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        self._url, self._format, self._transport, self._timeout = url, body_format, transport, timeout_seconds

    async def send(self, *, project_name: str, event: Event, run_id: str | None, reason: str | None) -> None:
        text = message(project_name=project_name, event=event, run_id=run_id, reason=reason)
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
                if self._format == "json":
                    fields = {"project": project_name, "event": event, "run_id": run_id, "reason": reason}
                    response = await client.post(self._url, json={"text": text, "content": text, **fields})
                else:
                    response = await client.post(
                        self._url, content=text.encode("utf-8"), headers={"Content-Type": "text/plain; charset=utf-8"}
                    )
                response.raise_for_status()
        except httpx.HTTPError as error:
            logger.warning("alert for %s not sent: %s", project_name, type(error).__name__)


def alerts_from_env() -> WebhookAlerts | None:
    """The host's webhook, or ``None`` when none is configured."""
    url = os.environ.get(URL_ENV, "").strip()
    if not url:
        return None
    body_format = "json" if os.environ.get(FORMAT_ENV, "").strip().lower() == "json" else "text"
    return WebhookAlerts(url, body_format=body_format)


class AlertGate:
    """Sends a project's alert only when its state differs from the last one sent for it."""

    def __init__(self, alerts: Alerts | None) -> None:
        self._alerts = alerts
        self._sent: dict[tuple[str, str], tuple[str, str | None, str | None]] = {}

    async def observe(
        self,
        *,
        user_id: str,
        project_name: str,
        event: Event | None,
        run_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Record the project's state; ``event=None`` (running, waiting or ready) clears it, so a later halt is new."""
        key = (user_id, project_name)
        if event is None:
            self._sent.pop(key, None)
            return
        state = (event, run_id, reason)
        if self._alerts is None or self._sent.get(key) == state:
            return
        self._sent[key] = state
        await self._alerts.send(project_name=project_name, event=event, run_id=run_id, reason=reason)


__all__ = ["AlertGate", "Alerts", "WebhookAlerts", "alerts_from_env", "message"]
