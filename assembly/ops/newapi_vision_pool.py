"""Spread DramaClaw's vision features over several free Gemini models (ASSEMBLY_MODELS vision slot).

Gemini's free tier counts requests per model (about 20 a day each, docs/r2/cloud-free-quota-registry.md); one episode
needs ~36 vision calls (video prompt optimizer + sketch identity detector, one per beat), more than one model allows.
NewAPI retries a failed request on another channel serving the same model name when `RetryTimes` > 0
(gateway `controller/relay.go` shouldRetry). This script sets `RetryTimes` and keeps one cloned Gemini channel per
extra model (cloned server-side with `/api/channel/copy/:id`, so the key is never read), each mapping the vision
names to its model, auto-ban off (a quota 429 must not disable a channel). Clones are named `assembly-gemini-*`;
DramaClaw only manages its `DC-*` channels. Run on the host: `python assembly/ops/newapi_vision_pool.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

NEWAPI = "http://127.0.0.1:3000"
RETRY_TIMES = 5
VISION_NAMES = [
    "DC-video-prompt-optimizer-LLM",
    "DC-video-identity-detector-LLM",
    "DC-freezone-vision-LLM",
    "DC-style-analyzer-LLM",
]
# model -> NewAPI priority (higher is tried first). gemini-2.5-flash answered every call on 2026-11-24 while the
# others returned 503s; DramaClaw's own DC-gemini channel (priority 0) is tried last.
EXTRA_MODELS = {"gemini-2.5-flash": 20, "gemini-3.5-flash-lite": 10, "gemini-3-flash-preview": 5}
# DramaClaw's default model (MODEL_NAME, used by its verifiers, which ask for a strict JSON schema). gemini-2.5-flash
# returned list items as strings instead of objects on the episode overview (2026-11-24), so this name is served only
# by the newer models.
VERIFIER_NAME = "DC-verifier-LLM"
VERIFIER_MODELS = {"gemini-3-flash-preview", "gemini-3.5-flash-lite"}


def _session() -> tuple[httpx.Client, dict[str, str]]:
    password = (Path.home() / "assembly-data/secrets/newapi-root").read_text().strip()
    client = httpx.Client(base_url=NEWAPI, timeout=30)
    data = client.post("/api/user/login", json={"username": "root", "password": password}).json()["data"]
    return client, {"Authorization": f"Bearer {data['access_token']}", "New-Api-User": str(data["user"]["id"])}


def _update(client: httpx.Client, headers: dict[str, str], channel: dict) -> None:
    channel = {k: v for k, v in channel.items() if k not in {"status", "key"}}
    for body in (channel, {"channel": channel}):
        if client.put("/api/channel/", json=body, headers=headers).json().get("success"):
            return
    raise RuntimeError(f"channel {channel.get('id')} update refused")


def main() -> None:
    client, headers = _session()
    result = client.put("/api/option/", json={"key": "RetryTimes", "value": str(RETRY_TIMES)}, headers=headers).json()
    print("RetryTimes", RETRY_TIMES, "ok" if result.get("success") else result.get("message"))
    items = client.get("/api/channel/", params={"p": 1, "page_size": 100}, headers=headers).json()["data"]["items"]
    origin = next(c for c in items if c["name"] == "DC-gemini")
    for model in EXTRA_MODELS:
        name = f"assembly-gemini-{model}"
        existing = next((c for c in items if c["name"] == name), None)
        if existing is None:
            copied = client.post(
                f"/api/channel/copy/{origin['id']}", params={"suffix": f"-{model}"}, headers=headers
            ).json()
            if not copied.get("success"):
                raise RuntimeError(f"copy failed: {copied.get('message')}")
            items = client.get("/api/channel/", params={"p": 1, "page_size": 100}, headers=headers).json()["data"][
                "items"
            ]
            existing = next(c for c in items if c["name"] == f"DC-gemini-{model}")
        detail = client.get(f"/api/channel/{existing['id']}", headers=headers).json()["data"]
        names = VISION_NAMES + ([VERIFIER_NAME] if model in VERIFIER_MODELS else [])
        detail.update(
            {
                "name": name,
                "models": ",".join(names),
                "model_mapping": json.dumps(dict.fromkeys(names, model)),
                "auto_ban": 0,
                "priority": EXTRA_MODELS[model],
            }
        )
        _update(client, headers, detail)
        print("channel", existing["id"], name)


if __name__ == "__main__":
    main()
