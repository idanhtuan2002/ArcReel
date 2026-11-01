from __future__ import annotations

import json

import httpx

from scripts.r2.qualify_autonomous_production import run_once


def _client(states: list[dict], offer: dict) -> tuple[httpx.Client, list[dict]]:
    posted: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/production-runs"):
            return httpx.Response(200, json={"start": offer, "runs": []})
        if request.method == "POST":
            posted.append(json.loads(request.content))
            return httpx.Response(200, json=states[0])
        return httpx.Response(200, json=states.pop(0) if len(states) > 1 else states[0])

    return httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler)), posted


def _run(**changes) -> dict:
    return {
        "run_id": "r",
        "policy_digest": "sha256:p",
        "input_digest": "sha256:i",
        "status": "RUNNING",
        "stage": "BRIEF",
        "generation": 1,
        **changes,
    }


OFFER = {"enabled": True, "input_digest": "sha256:i", "policy_digests": {"auto": "sha256:p", "semi": "sha256:s"}}


def test_the_record_reports_exactly_what_the_server_reports():
    client, posted = _client(
        [_run(), _run(stage="STORY", status="WAITING_TASK"), _run(stage="EXPORT", status="SUCCEEDED")], OFFER
    )
    ticks = iter(range(100))

    record = run_once(
        client,
        project="p",
        idea="Ý tưởng",
        mode="auto",
        poll_seconds=0,
        timeout_seconds=50,
        clock=lambda: float(next(ticks)),
        sleep=lambda _s: None,
    )

    assert record["status"] == "SUCCEEDED"
    assert [h["stage"] for h in record["history"]] == ["BRIEF", "STORY", "EXPORT"]
    assert posted[0]["policy_digest"] == "sha256:p"


def test_a_disabled_offer_starts_nothing_and_a_checkpoint_is_never_approved():
    client, posted = _client([_run()], {"enabled": False, "reason": "RELEASE_GATE_PENDING"})
    assert run_once(client, project="p", idea="x", mode="auto", poll_seconds=0, timeout_seconds=1) == {
        "started": False,
        "reason": "RELEASE_GATE_PENDING",
    }
    assert posted == []

    client, posted = _client([_run(), _run(status="WAITING_REVIEW", stage="SCRIPT")], OFFER)
    record = run_once(client, project="p", idea="x", mode="semi", poll_seconds=0, timeout_seconds=10)
    assert record["status"] == "WAITING_REVIEW"
    assert len(posted) == 1
